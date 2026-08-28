#!/usr/bin/env python3
"""Validate Markdown tables and local relative links without external packages."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(")
REFERENCE_DEFINITION_RE = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:\s*(.+)$")


@dataclass(frozen=True)
class Issue:
    path: Path
    line: int
    message: str


def mask_fenced_code(lines: list[str]) -> list[str | None]:
    """Replace fenced-code lines with None while preserving physical line numbers."""
    masked: list[str | None] = []
    fence_character: str | None = None
    fence_length = 0

    for line in lines:
        if fence_character is None:
            match = FENCE_OPEN_RE.match(line)
            if match:
                fence_character = match.group(1)[0]
                fence_length = len(match.group(1))
                masked.append(None)
                continue
            masked.append(line)
            continue

        closing = re.match(
            rf"^[ ]{{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*$",
            line,
        )
        masked.append(None)
        if closing:
            fence_character = None
            fence_length = 0

    return masked


def mask_inline_code(line: str) -> str:
    """Mask backtick code spans so their pipes and link-like text are ignored."""
    characters = list(line)
    active_run: int | None = None
    index = 0
    while index < len(line):
        if line[index] != "`" or (index > 0 and line[index - 1] == "\\"):
            if active_run is not None:
                characters[index] = " "
            index += 1
            continue

        end = index
        while end < len(line) and line[end] == "`":
            end += 1
        run_length = end - index
        if active_run is None:
            active_run = run_length
        elif active_run == run_length:
            active_run = None
        for position in range(index, end):
            characters[position] = " "
        index = end
    return "".join(characters)


def split_table_row(line: str) -> list[str] | None:
    """Split a pipe table row, respecting escaped pipes and inline code spans."""
    cells: list[str] = []
    current: list[str] = []
    active_backticks: int | None = None
    delimiter_count = 0
    index = 0

    while index < len(line):
        character = line[index]
        if character == "\\" and index + 1 < len(line):
            current.extend((character, line[index + 1]))
            index += 2
            continue
        if character == "`":
            end = index
            while end < len(line) and line[end] == "`":
                end += 1
            run = line[index:end]
            if active_backticks is None:
                active_backticks = len(run)
            elif active_backticks == len(run):
                active_backticks = None
            current.append(run)
            index = end
            continue
        if character == "|" and active_backticks is None:
            cells.append("".join(current).strip())
            current = []
            delimiter_count += 1
        else:
            current.append(character)
        index += 1

    if delimiter_count == 0:
        return None
    cells.append("".join(current).strip())
    if cells and not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return cells


def is_separator_row(cells: list[str] | None) -> bool:
    return bool(cells) and all(TABLE_SEPARATOR_RE.fullmatch(cell.strip()) for cell in cells)


def validate_tables(path: Path, lines: list[str | None]) -> list[Issue]:
    issues: list[Issue] = []
    index = 0
    while index + 1 < len(lines):
        header_line = lines[index]
        separator_line = lines[index + 1]
        if header_line is None or separator_line is None:
            index += 1
            continue

        header = split_table_row(header_line)
        separator = split_table_row(separator_line)
        if header is None or not is_separator_row(separator):
            index += 1
            continue

        expected_columns = len(header)
        if len(separator) != expected_columns:
            issues.append(
                Issue(
                    path,
                    index + 2,
                    "table separator has "
                    f"{len(separator)} columns; header has {expected_columns}",
                )
            )

        row_index = index + 2
        while row_index < len(lines):
            row_line = lines[row_index]
            if row_line is None or not row_line.strip():
                break
            row = split_table_row(row_line)
            if row is None:
                break
            if len(row) != expected_columns:
                issues.append(
                    Issue(
                        path,
                        row_index + 1,
                        f"table row has {len(row)} columns; header has {expected_columns}",
                    )
                )
            row_index += 1
        index = max(index + 1, row_index)
    return issues


def parse_link_destination(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if value.startswith("<"):
        closing = value.find(">", 1)
        return value[1:closing] if closing >= 0 else None

    destination: list[str] = []
    escaped = False
    for character in value:
        if escaped:
            destination.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character.isspace():
            break
        else:
            destination.append(character)
    return "".join(destination) or None


def inline_link_destinations(line: str) -> list[str]:
    destinations: list[str] = []
    search_from = 0
    while True:
        match = INLINE_LINK_RE.search(line, search_from)
        if not match:
            return destinations
        content_start = match.end()
        depth = 1
        escaped = False
        index = content_start
        while index < len(line):
            character = line[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    destination = parse_link_destination(line[content_start:index])
                    if destination is not None:
                        destinations.append(destination)
                    index += 1
                    break
            index += 1
        search_from = max(match.end(), index)


def local_relative_path(destination: str) -> str | None:
    if destination.startswith(("#", "/", "//", "~")):
        return None
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return unquote(parsed.path)


def validate_links(path: Path, lines: list[str | None]) -> list[Issue]:
    issues: list[Issue] = []
    for line_number, original in enumerate(lines, start=1):
        if original is None:
            continue
        line = mask_inline_code(original)
        destinations = inline_link_destinations(line)
        definition = REFERENCE_DEFINITION_RE.match(line)
        if definition:
            destination = parse_link_destination(definition.group(1))
            if destination is not None:
                destinations.append(destination)

        for destination in destinations:
            relative = local_relative_path(destination)
            if relative is None:
                continue
            target = path.parent / relative
            if not target.exists():
                issues.append(
                    Issue(path, line_number, f"missing local link target: {destination}")
                )
    return issues


def validate_file(path: Path) -> list[Issue]:
    lines = path.read_text(encoding="utf-8").splitlines()
    visible_lines = mask_fenced_code(lines)
    return validate_tables(path, visible_lines) + validate_links(path, visible_lines)


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


def validate_root(root: Path) -> tuple[list[Path], list[Issue]]:
    files = markdown_files(root)
    issues = [issue for path in files for issue in validate_file(path)]
    return files, issues


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="validate-markdown-") as directory:
        root = Path(directory)
        (root / "target.md").write_text("# Target\n", encoding="utf-8")
        (root / "valid.md").write_text(
            """# Valid

| A | B |
|---|---|
| `literal | pipe` | [target](target.md) |

```markdown
| ignored |
|---|---|
| [ignored](missing.md) |
```
""",
            encoding="utf-8",
        )
        valid_issues = validate_file(root / "valid.md")
        if valid_issues:
            raise AssertionError(f"valid fixture produced issues: {valid_issues}")

        (root / "invalid.md").write_text(
            """# Invalid

| A | B |
|---|---|---|

| A | B |
|---|---|
| one | two | three |

[missing](does-not-exist.md)
[reference]: missing-reference.md
""",
            encoding="utf-8",
        )
        invalid_issues = validate_file(root / "invalid.md")
        messages = {issue.message for issue in invalid_issues}
        expected_fragments = {
            "table separator has 3 columns; header has 2",
            "table row has 3 columns; header has 2",
            "missing local link target: does-not-exist.md",
            "missing local link target: missing-reference.md",
        }
        if messages != expected_fragments:
            raise AssertionError(
                f"invalid fixture mismatch: expected {expected_fragments}, found {messages}"
            )
    print("validate_markdown self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    root = args.root.resolve()
    if not root.is_dir():
        print(f"error: Markdown root is not a directory: {root}", file=sys.stderr)
        return 2

    files, issues = validate_root(root)
    for issue in sorted(issues, key=lambda item: (str(item.path), item.line, item.message)):
        try:
            display_path = issue.path.relative_to(root)
        except ValueError:
            display_path = issue.path
        print(f"{display_path}:{issue.line}: {issue.message}", file=sys.stderr)

    if issues:
        print(
            f"Markdown validation failed: {len(issues)} issue(s) in {len(files)} file(s)",
            file=sys.stderr,
        )
        return 1
    print(f"Markdown validation passed: {len(files)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
