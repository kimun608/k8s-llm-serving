#!/usr/bin/env python3
"""Run a closed-loop streaming benchmark against the Kubernetes vLLM Service."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROMETHEUS_METRICS = (
    "process_cpu_seconds_total",
    "process_resident_memory_bytes",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:kv_cache_usage_perc",
    "vllm:prompt_tokens_total",
    "vllm:prompt_tokens_cached_total",
    "vllm:generation_tokens_total",
    "vllm:num_preemptions_total",
    "vllm:prefix_cache_queries_total",
    "vllm:prefix_cache_hits_total",
    "vllm:request_success_total",
    "vllm:spec_decode_num_drafts_total",
    "vllm:spec_decode_num_draft_tokens_total",
    "vllm:spec_decode_num_accepted_tokens_total",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_text(command: list[str], timeout: float = 30) -> str | None:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def run_json(command: list[str], timeout: float = 30) -> Any:
    output = run_text(command, timeout=timeout)
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def http_bytes(url: str, *, data: dict | None = None, timeout: float = 30) -> bytes:
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def http_json(url: str, *, data: dict | None = None, timeout: float = 30) -> Any:
    return json.loads(http_bytes(url, data=data, timeout=timeout))


def wait_healthy(base_url: str, timeout_seconds: float = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            http_bytes(f"{base_url}/health", timeout=2)
            return
        except Exception as error:  # noqa: BLE001 - report the final connection error
            last_error = error
            time.sleep(0.25)
    raise RuntimeError(f"Service did not become healthy at {base_url}: {last_error}")


class PortForward:
    def __init__(self, namespace: str, service: str, local_port: int, log_path: Path):
        self.namespace = namespace
        self.service = service
        self.local_port = local_port
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self.log_handle = None

    def __enter__(self) -> str:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                "kubectl",
                "-n",
                self.namespace,
                "port-forward",
                f"service/{self.service}",
                f"{self.local_port}:8000",
            ],
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{self.local_port}"
        try:
            wait_healthy(base_url)
        except Exception:
            self.__exit__(*sys.exc_info())
            raise
        return base_url

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log_handle is not None:
            self.log_handle.close()


def parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {name: 0.0 for name in PROMETHEUS_METRICS}
    present: set[str] = set()
    selected = set(PROMETHEUS_METRICS)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        metric_with_labels, raw_value = parts
        name = metric_with_labels.split("{", 1)[0]
        if name not in selected:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if math.isfinite(value):
            values[name] += value
            present.add(name)
    return {name: (values[name] if name in present else math.nan) for name in PROMETHEUS_METRICS}


def read_cgroup(namespace: str) -> dict[str, float]:
    command = [
        "kubectl",
        "-n",
        namespace,
        "exec",
        "deploy/vllm-cpu",
        "--",
        "sh",
        "-c",
        "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events",
    ]
    output = run_text(command, timeout=10)
    result = {
        "pod_cpu_usage_usec": math.nan,
        "pod_memory_current_bytes": math.nan,
        "pod_memory_events_max": math.nan,
        "pod_memory_events_oom": math.nan,
        "pod_memory_events_oom_kill": math.nan,
    }
    if not output:
        return result
    memory_value_seen = False
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 1 and parts[0].isdigit() and not memory_value_seen:
            result["pod_memory_current_bytes"] = float(parts[0])
            memory_value_seen = True
        elif len(parts) == 2 and parts[0] == "usage_usec":
            result["pod_cpu_usage_usec"] = float(parts[1])
        elif len(parts) == 2 and parts[0] == "max":
            result["pod_memory_events_max"] = float(parts[1])
        elif len(parts) == 2 and parts[0] == "oom":
            result["pod_memory_events_oom"] = float(parts[1])
        elif len(parts) == 2 and parts[0] == "oom_kill":
            result["pod_memory_events_oom_kill"] = float(parts[1])
    return result


class MetricsSampler:
    def __init__(self, base_url: str, namespace: str, interval: float, collect_cgroup: bool):
        self.base_url = base_url
        self.namespace = namespace
        self.interval = interval
        self.collect_cgroup = collect_cgroup
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.started = 0.0

    def sample(self) -> None:
        sample: dict[str, Any] = {
            "timestamp_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - self.started,
        }
        try:
            metrics_text = http_bytes(f"{self.base_url}/metrics", timeout=5).decode("utf-8")
            sample.update(parse_prometheus(metrics_text))
        except Exception as error:  # noqa: BLE001 - preserve benchmark despite one scrape failure
            sample.update({name: math.nan for name in PROMETHEUS_METRICS})
            self.errors.append(f"prometheus: {type(error).__name__}: {error}")
        if self.collect_cgroup:
            sample.update(read_cgroup(self.namespace))
        else:
            sample.update(
                {
                    "pod_cpu_usage_usec": math.nan,
                    "pod_memory_current_bytes": math.nan,
                    "pod_memory_events_max": math.nan,
                    "pod_memory_events_oom": math.nan,
                    "pod_memory_events_oom_kill": math.nan,
                }
            )
        self.samples.append(sample)

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.sample()

    def start(self) -> None:
        self.started = time.monotonic()
        # Capture counter baselines before measured requests can begin.
        self.sample()
        self.thread = threading.Thread(target=self._loop, name="metrics-sampler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(10, self.interval * 3))
        self.sample()


def stream_completion(
    base_url: str,
    config: dict,
    prompt: dict,
    concurrency: int,
    *,
    max_tokens: int | None = None,
    warmup: bool = False,
) -> dict[str, Any]:
    output_limit = int(max_tokens if max_tokens is not None else config["max_tokens"])
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": config["system_prompt"]},
            {"role": "user", "content": prompt["prompt"]},
        ],
        "max_tokens": output_limit,
        "temperature": config["temperature"],
        "seed": config["seed"],
        "ignore_eos": config["ignore_eos"],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    request_started_at_utc = utc_now()
    started = time.perf_counter()
    first_content_at: float | None = None
    last_content_at: float | None = None
    content_chunks = 0
    content_hasher = hashlib.sha256()
    content_chars = 0
    usage: dict[str, int] = {}
    finish_reason: str | None = None
    status = "success"
    error_text: str | None = None

    try:
        with urllib.request.urlopen(request, timeout=float(config["request_timeout_seconds"])) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                event = json.loads(data)
                if event.get("usage"):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                content = (choice.get("delta") or {}).get("content")
                if content:
                    now = time.perf_counter()
                    if first_content_at is None:
                        first_content_at = now
                    last_content_at = now
                    content_chunks += 1
                    encoded = content.encode("utf-8")
                    content_hasher.update(encoded)
                    content_chars += len(content)
    except urllib.error.HTTPError as error:
        status = "error"
        error_body = error.read().decode("utf-8", errors="replace")[:1000]
        error_text = f"HTTP {error.code}: {error_body}"
    except Exception as error:  # noqa: BLE001 - record per-request transport failures
        status = "error"
        error_text = f"{type(error).__name__}: {error}"

    ended = time.perf_counter()
    e2e = ended - started
    ttft = None if first_content_at is None else first_content_at - started
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    tpot = None
    if ttft is not None and completion_tokens > 1:
        tpot = max(0.0, e2e - ttft) / (completion_tokens - 1)

    if status == "success" and (completion_tokens == 0 or first_content_at is None):
        status = "error"
        error_text = "Streaming response completed without content or usage tokens"

    return {
        "sequence": prompt["sequence"],
        "prompt_id": prompt["id"],
        "source": prompt["source"],
        "concurrency": concurrency,
        "warmup": warmup,
        "status": status,
        "error": error_text,
        "e2e_seconds": e2e,
        "ttft_seconds": ttft,
        "tpot_seconds": tpot,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "content_chunks": content_chunks,
        "content_chars": content_chars,
        "content_sha256": content_hasher.hexdigest() if content_chars else None,
        "finish_reason": finish_reason,
        "first_to_last_content_seconds": (
            None
            if first_content_at is None or last_content_at is None
            else last_content_at - first_content_at
        ),
        "started_at_utc": request_started_at_utc,
    }


def tokenize_prompts(base_url: str, config: dict, prompts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    max_model_len: int | None = None
    for prompt in prompts:
        response = http_json(
            f"{base_url}/tokenize",
            data={
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": config["system_prompt"]},
                    {"role": "user", "content": prompt["prompt"]},
                ],
            },
            timeout=30,
        )
        counts[prompt["id"]] = int(response["count"])
        if response.get("max_model_len") is not None:
            max_model_len = int(response["max_model_len"])
    if max_model_len is not None:
        invalid = [
            (prompt_id, count)
            for prompt_id, count in counts.items()
            if count + int(config["max_tokens"]) > max_model_len
        ]
        if invalid:
            raise RuntimeError(
                f"{len(invalid)} prompts exceed max_model_len={max_model_len} with output tokens: {invalid[:5]}"
            )
    return counts


def wait_idle(base_url: str, timeout_seconds: float = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        metrics = parse_prometheus(http_bytes(f"{base_url}/metrics", timeout=5).decode("utf-8"))
        running = metrics.get("vllm:num_requests_running", 0.0)
        waiting = metrics.get("vllm:num_requests_waiting", 0.0)
        if (not math.isfinite(running) or running == 0) and (not math.isfinite(waiting) or waiting == 0):
            return
        time.sleep(0.5)
    raise RuntimeError("vLLM did not become idle within 60 seconds")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_metrics_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "timestamp_utc",
        "elapsed_seconds",
        *PROMETHEUS_METRICS,
        "pod_cpu_usage_usec",
        "pod_memory_current_bytes",
        "pod_memory_events_max",
        "pod_memory_events_oom",
        "pod_memory_events_oom_kill",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def system_metadata(namespace: str) -> dict[str, Any]:
    docker_info = run_json(["docker", "info", "--format", "{{json .}}"])
    deployment = run_json(["kubectl", "-n", namespace, "get", "deployment", "vllm-cpu", "-o", "json"])
    pods = run_json(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=vllm-cpu",
            "-o",
            "json",
        ]
    )
    nodes = run_json(["kubectl", "get", "nodes", "-o", "json"])
    container = None
    if deployment:
        container = deployment["spec"]["template"]["spec"]["containers"][0]
    pod_items = []
    for pod in (pods or {}).get("items", []):
        statuses = pod.get("status", {}).get("containerStatuses", [])
        pod_items.append(
            {
                "name": pod["metadata"]["name"],
                "uid": pod["metadata"]["uid"],
                "node": pod.get("spec", {}).get("nodeName"),
                "phase": pod.get("status", {}).get("phase"),
                "restart_count": sum(item.get("restartCount", 0) for item in statuses),
                "image_id": statuses[0].get("imageID") if statuses else None,
            }
        )
    node_items = []
    for node in (nodes or {}).get("items", []):
        node_items.append(
            {
                "name": node["metadata"]["name"],
                "architecture": node["status"]["nodeInfo"]["architecture"],
                "kubelet_version": node["status"]["nodeInfo"]["kubeletVersion"],
                "container_runtime": node["status"]["nodeInfo"]["containerRuntimeVersion"],
                "capacity": node["status"].get("capacity"),
            }
        )
    return {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_brand": run_text(["sysctl", "-n", "machdep.cpu.brand_string"]),
            "logical_cpu": run_text(["sysctl", "-n", "hw.logicalcpu"]),
            "memory_bytes": run_text(["sysctl", "-n", "hw.memsize"]),
        },
        "docker": (
            {
                "cpus": docker_info.get("NCPU"),
                "memory_bytes": docker_info.get("MemTotal"),
                "architecture": docker_info.get("Architecture"),
                "operating_system": docker_info.get("OperatingSystem"),
                "server_version": docker_info.get("ServerVersion"),
            }
            if docker_info
            else None
        ),
        "kubernetes": {
            "nodes": node_items,
            "pods": pod_items,
            "deployment_generation": deployment["metadata"].get("generation") if deployment else None,
            "container": (
                {
                    "image": container.get("image"),
                    "args": container.get("args"),
                    "resources": container.get("resources"),
                    "env": container.get("env"),
                }
                if container
                else None
            ),
        },
        "git": {
            "commit": run_text(["git", "rev-parse", "HEAD"]),
            "status_porcelain": run_text(["git", "status", "--porcelain"]),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--config", type=Path, default=root / "config" / "baseline.json")
    parser.add_argument("--prompts", type=Path, default=root / "data" / "prompts.jsonl")
    parser.add_argument("--output", type=Path, default=root / "results" / "baseline")
    parser.add_argument("--base-url", help="Use an existing reachable endpoint; otherwise manage port-forward")
    parser.add_argument("--concurrencies", nargs="+", type=int)
    parser.add_argument("--limit", type=int, help="Run only the first N prompts for a quick functional check")
    parser.add_argument("--no-cgroup", action="store_true", help="Skip kubectl cgroup collection")
    return parser.parse_args()


def execute(args: argparse.Namespace, base_url: str, config: dict, prompts: list[dict]) -> int:
    raw_dir = args.output / "raw"
    manifest_path = args.output / "run-manifest.json"
    raw_dir.mkdir(parents=True, exist_ok=True)

    model_info = http_json(f"{base_url}/v1/models")
    server_version = http_json(f"{base_url}/version")
    print("Tokenizing prompts and validating the 2,048-token context limit...", flush=True)
    input_token_counts = tokenize_prompts(base_url, config, prompts)
    token_values = list(input_token_counts.values())

    concurrencies = args.concurrencies or [int(value) for value in config["concurrencies"]]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "base_url": base_url,
        "config": config,
        "config_sha256": sha256_file(args.config),
        "prompts_file": str(args.prompts),
        "prompts_sha256": sha256_file(args.prompts),
        "prompt_count": len(prompts),
        "input_token_validation": {
            "minimum": min(token_values),
            "maximum": max(token_values),
            "mean": sum(token_values) / len(token_values),
            "counts_by_prompt_id": input_token_counts,
        },
        "concurrencies": concurrencies,
        "model_endpoint": model_info,
        "server_version": server_version,
        "environment": system_metadata(config["namespace"]),
        "phases": [],
    }
    write_json(manifest_path, manifest)

    failures = 0
    for concurrency in concurrencies:
        print(f"[concurrency={concurrency}] warmup ({config['warmup_requests']} requests)", flush=True)
        warmup_prompts = prompts[: min(int(config["warmup_requests"]), len(prompts))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(warmup_prompts))) as executor:
            warmup_results = list(
                executor.map(
                    lambda prompt: stream_completion(
                        base_url,
                        config,
                        prompt,
                        concurrency,
                        max_tokens=int(config["warmup_max_tokens"]),
                        warmup=True,
                    ),
                    warmup_prompts,
                )
            )
        warmup_failures = sum(row["status"] != "success" for row in warmup_results)
        if warmup_failures:
            raise RuntimeError(f"Warmup failed for concurrency={concurrency}: {warmup_results}")
        wait_idle(base_url)
        time.sleep(float(config["cooldown_seconds"]))

        sampler = MetricsSampler(
            base_url,
            config["namespace"],
            float(config["metrics_interval_seconds"]),
            not args.no_cgroup,
        )
        print(f"[concurrency={concurrency}] running {len(prompts)} measured requests", flush=True)
        sampler.start()
        phase_started_utc = utc_now()
        phase_started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(stream_completion, base_url, config, prompt, concurrency)
                for prompt in prompts
            ]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        duration = time.perf_counter() - phase_started
        phase_finished_utc = utc_now()
        sampler.stop()
        results.sort(key=lambda row: row["sequence"])

        label = f"c{concurrency:02d}"
        requests_file = raw_dir / f"requests-{label}.jsonl"
        metrics_file = raw_dir / f"server-metrics-{label}.csv"
        phase_file = raw_dir / f"phase-{label}.json"
        write_jsonl(requests_file, results)
        write_metrics_csv(metrics_file, sampler.samples)

        failed = sum(row["status"] != "success" for row in results)
        failures += failed
        phase = {
            "concurrency": concurrency,
            "started_at_utc": phase_started_utc,
            "finished_at_utc": phase_finished_utc,
            "duration_seconds": duration,
            "request_count": len(results),
            "success_count": len(results) - failed,
            "failure_count": failed,
            "warmup_request_count": len(warmup_results),
            "warmup_results": warmup_results,
            "metrics_sample_count": len(sampler.samples),
            "metrics_scrape_errors": sampler.errors,
            "requests_file": str(requests_file.relative_to(args.output)),
            "metrics_file": str(metrics_file.relative_to(args.output)),
        }
        write_json(phase_file, phase)
        manifest["phases"].append(phase)
        write_json(manifest_path, manifest)
        print(
            f"[concurrency={concurrency}] completed in {duration:.2f}s; "
            f"success={len(results) - failed}/{len(results)}",
            flush=True,
        )
        wait_idle(base_url)

    manifest["status"] = "completed" if failures == 0 else "completed_with_failures"
    manifest["finished_at_utc"] = utc_now()
    manifest["total_failures"] = failures
    write_json(manifest_path, manifest)
    return 0 if failures == 0 else 2


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    prompts = [json.loads(line) for line in args.prompts.read_text(encoding="utf-8").splitlines() if line]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        prompts = prompts[: args.limit]
    expected = int(config["request_count"])
    if args.limit is None and len(prompts) != expected:
        raise RuntimeError(f"Expected {expected} prompts, found {len(prompts)}")
    if any(value < 1 for value in (args.concurrencies or config["concurrencies"])):
        raise ValueError("All concurrency values must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"Output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    if args.base_url:
        base_url = args.base_url.rstrip("/")
        wait_healthy(base_url)
        return execute(args, base_url, config, prompts)

    with PortForward(
        config["namespace"],
        config["service"],
        int(config["local_port"]),
        args.output / "raw" / "port-forward.log",
    ) as base_url:
        return execute(args, base_url, config, prompts)


if __name__ == "__main__":
    raise SystemExit(main())
