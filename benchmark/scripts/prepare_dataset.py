#!/usr/bin/env python3
"""Build a deterministic 100-prompt serving workload from official benchmarks."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import random
import shutil
import ssl
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SEED = 20260828
PER_SOURCE = 25


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    cache_name: str
    project_url: str
    revision: str


SOURCES = (
    Source(
        name="gsm8k",
        url=(
            "https://raw.githubusercontent.com/openai/grade-school-math/"
            "3101c7d5072418e28b9008a6636bde82a006892c/"
            "grade_school_math/data/test.jsonl"
        ),
        cache_name="gsm8k-test.jsonl",
        project_url="https://github.com/openai/grade-school-math",
        revision="3101c7d5072418e28b9008a6636bde82a006892c",
    ),
    Source(
        name="humaneval",
        url=(
            "https://raw.githubusercontent.com/openai/human-eval/"
            "6d43fb980f9fee3c892a914eda09951f772ad10d/"
            "data/HumanEval.jsonl.gz"
        ),
        cache_name="HumanEval.jsonl.gz",
        project_url="https://github.com/openai/human-eval",
        revision="6d43fb980f9fee3c892a914eda09951f772ad10d",
    ),
    Source(
        name="truthfulqa",
        url=(
            "https://raw.githubusercontent.com/sylinrl/TruthfulQA/"
            "d71c110897f5d31c5d7f309e7bc316c152f6f031/TruthfulQA.csv"
        ),
        cache_name="TruthfulQA.csv",
        project_url="https://github.com/sylinrl/TruthfulQA",
        revision="d71c110897f5d31c5d7f309e7bc316c152f6f031",
    ),
    Source(
        name="longbench_qasper",
        url=(
            "https://huggingface.co/datasets/zai-org/LongBench/resolve/"
            "5e628be450b7e67fb7ae6e201bd6d8f7056f7672/data.zip"
        ),
        cache_name="LongBench-data.zip",
        project_url="https://github.com/THUDM/LongBench",
        revision="5e628be450b7e67fb7ae6e201bd6d8f7056f7672",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(source: Source, cache_dir: Path) -> tuple[Path, bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / source.cache_name
    if destination.exists() and destination.stat().st_size > 0:
        return destination, False

    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        source.url,
        headers={"User-Agent": "k8s-llm-serving-benchmark/1.0"},
    )
    print(f"Downloading {source.name}: {source.url}", file=sys.stderr)
    # The python.org macOS installer does not always install its CA symlinks.
    # Prefer certifi when available, without ever disabling TLS verification.
    try:
        import certifi  # type: ignore[import-not-found]

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=120, context=ssl_context) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    temporary.replace(destination)
    return destination, True


def jsonl_rows(handle: Iterable[str]) -> list[dict]:
    return [json.loads(line) for line in handle if line.strip()]


def load_gsm8k(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return jsonl_rows(handle)


def load_humaneval(path: Path) -> list[dict]:
    with gzip.open(path, mode="rt", encoding="utf-8") as handle:
        return jsonl_rows(handle)


def load_truthfulqa(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_qasper(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.endswith("qasper.jsonl")]
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one qasper.jsonl in {path}, found {candidates}")
        with archive.open(candidates[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            return jsonl_rows(text)


def choose(rows: list[dict], seed_offset: int) -> list[tuple[int, dict]]:
    rng = random.Random(SEED + seed_offset)
    indices = rng.sample(range(len(rows)), PER_SOURCE)
    return [(index, rows[index]) for index in indices]


def build_prompt(source: str, row: dict, selected_position: int) -> str:
    if source == "gsm8k":
        return (
            "Solve the following grade-school math problem. Show only the essential "
            "reasoning and the final answer.\n\n"
            f"{row['question'].strip()}"
        )
    if source == "humaneval":
        return (
            "Complete the following Python function. Return only the completed code.\n\n"
            f"{row['prompt'].rstrip()}"
        )
    if source == "truthfulqa":
        return (
            "Answer the following question truthfully and concisely. If the premise is "
            "false or you are uncertain, state that clearly.\n\n"
            f"{row['Question'].strip()}"
        )
    if source == "longbench_qasper":
        # Five deterministic context sizes produce a useful long-prompt distribution
        # while leaving room for the chat template and 64 output tokens in 2,048 tokens.
        context_budgets = (1800, 2400, 3000, 3600, 4200)
        context = row["context"].strip()[: context_budgets[selected_position % len(context_budgets)]]
        return (
            "Use only the research-paper context below to answer the question. Answer "
            "concisely.\n\n"
            f"Context:\n{context}\n\nQuestion:\n{row['input'].strip()}"
        )
    raise ValueError(f"Unknown source: {source}")


def source_item_id(source: str, source_index: int, row: dict) -> str:
    if source == "humaneval":
        return str(row.get("task_id", source_index))
    if source == "longbench_qasper":
        return str(row.get("_id", source_index))
    return str(source_index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--output", type=Path, default=root / "data" / "prompts.jsonl")
    parser.add_argument("--manifest", type=Path, default=root / "data" / "source-manifest.json")
    parser.add_argument("--cache-dir", type=Path, default=root / "data" / "cache")
    parser.add_argument("--force-download", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.force_download and args.cache_dir.exists():
        for source in SOURCES:
            cached = args.cache_dir / source.cache_name
            cached.unlink(missing_ok=True)

    paths: dict[str, Path] = {}
    source_metadata: list[dict] = []
    for source in SOURCES:
        path, _downloaded = download(source, args.cache_dir)
        paths[source.name] = path
        source_metadata.append(
            {
                "name": source.name,
                "project_url": source.project_url,
                "download_url": source.url,
                "revision": source.revision,
                "cache_file": source.cache_name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    loaders = {
        "gsm8k": load_gsm8k,
        "humaneval": load_humaneval,
        "truthfulqa": load_truthfulqa,
        "longbench_qasper": load_qasper,
    }
    prompts: list[dict] = []
    for source_offset, source in enumerate(SOURCES):
        rows = loaders[source.name](paths[source.name])
        selected = choose(rows, source_offset * 1000)
        for selected_position, (source_index, row) in enumerate(selected):
            prompt = build_prompt(source.name, row, selected_position)
            prompts.append(
                {
                    "id": f"{source.name}-{selected_position + 1:02d}",
                    "source": source.name,
                    "source_item_id": source_item_id(source.name, source_index, row),
                    "source_index": source_index,
                    "prompt": prompt,
                    "prompt_chars": len(prompt),
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                }
            )

    if len(prompts) != 100:
        raise RuntimeError(f"Expected exactly 100 prompts, got {len(prompts)}")
    if len({item["prompt_sha256"] for item in prompts}) != len(prompts):
        raise RuntimeError("Duplicate prompt content detected")

    # Interleave sources so every concurrency phase sees the same balanced order.
    prompts = [prompts[source_index * PER_SOURCE + position] for position in range(PER_SOURCE) for source_index in range(4)]
    for sequence, item in enumerate(prompts):
        item["sequence"] = sequence

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for item in prompts:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    workload_digest = hashlib.sha256(
        "\n".join(item["prompt_sha256"] for item in prompts).encode("ascii")
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Serving performance workload; model answer quality is not scored.",
        "seed": SEED,
        "samples_per_source": PER_SOURCE,
        "prompt_count": len(prompts),
        "source_order": [source.name for source in SOURCES],
        "workload_sha256": workload_digest,
        "sources": source_metadata,
    }
    # Rebuilding an unchanged deterministic workload should not create a noisy
    # timestamp-only Git diff. Preserve the original creation time when every
    # substantive manifest field is identical.
    if args.manifest.is_file():
        try:
            previous_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_manifest = None
        if isinstance(previous_manifest, dict):
            previous_without_time = {
                key: value for key, value in previous_manifest.items() if key != "created_at_utc"
            }
            current_without_time = {
                key: value for key, value in manifest.items() if key != "created_at_utc"
            }
            if previous_without_time == current_without_time and previous_manifest.get("created_at_utc"):
                manifest["created_at_utc"] = previous_manifest["created_at_utc"]
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = {source.name: sum(item["source"] == source.name for item in prompts) for source in SOURCES}
    print(f"Wrote {len(prompts)} prompts to {args.output}")
    print(f"Source counts: {counts}")
    print(f"Workload SHA-256: {workload_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
