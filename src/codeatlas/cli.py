"""Command line: `codeatlas scan <path-or-url> [--json]`.

`scan` runs intake, discovery and every adapter, then prints a census of what it saw.
Each discovered file lands in exactly one (language, tier) row, files that could not be
parsed included, and each folder or link that was not entered is listed once with its
reason and file count, so the totals show that nothing was dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codeatlas import __version__
from codeatlas.config import Config, Deadline, load_config
from codeatlas.indexer.discover import TEXT_LANGUAGE, Discovery, SkippedPath, discover
from codeatlas.indexer.generic.adapter import TextAdapter, module_node
from codeatlas.indexer.intake import IntakeError, IntakeResult, open_source
from codeatlas.indexer.registry import Registry
from codeatlas.models import (
    FileRecord,
    NodeKind,
    ParseResult,
    Snapshot,
    Tier,
    make_snapshot_id,
)


@dataclass(slots=True)
class LanguageRow:
    """One language's line in the census."""

    language: str
    tier: str
    files: int = 0
    bytes: int = 0
    nodes: dict[str, int] = field(default_factory=dict)
    raw_calls: int = 0
    files_with_errors: int = 0
    unparsed: int = 0


@dataclass(frozen=True, slots=True)
class ScanReport:
    snapshot: Snapshot
    root: Path
    used_git: bool
    reused_clone: bool
    rows: list[LanguageRow]
    discovery: Discovery
    tier_reasons: dict[str, str]

    def to_json(self) -> dict[str, object]:
        reasons = self.discovery.skip_reasons
        by_reason = Counter(_reason_group(r) for r in reasons.values())
        return {
            "snapshot": asdict(self.snapshot),
            "root": self.root.as_posix(),
            "used_git": self.used_git,
            "reused_clone": self.reused_clone,
            "languages": [asdict(row) for row in self.rows],
            "totals": {
                "files": sum(r.files for r in self.rows),
                "bytes": sum(r.bytes for r in self.rows),
                "nodes": sum(sum(r.nodes.values()) for r in self.rows),
                "raw_calls": sum(r.raw_calls for r in self.rows),
                "unparsed": sum(r.unparsed for r in self.rows),
            },
            "skipped_files": {
                "count": len(reasons),
                "by_reason": dict(sorted(by_reason.items())),
                "files": [{"path": p, "reason": r} for p, r in sorted(reasons.items())],
            },
            "skipped_paths": [asdict(s) for s in self.discovery.skipped],
            "tier_reasons": self.tier_reasons,
        }


def scan(source: str, config: Config, registry: Registry | None = None) -> ScanReport:
    """Intake, discovery and parsing of one source, stopping at the configured limits."""
    registry = registry or Registry()
    intake = open_source(source, config)
    # The limit covers indexing only: a slow clone must not use up the parse budget.
    deadline = Deadline(config.max_seconds)
    discovery = discover(intake.root, config, registry.tier_for, deadline)
    sha = intake.commit_sha or _content_sha(discovery.files)
    snapshot_id = make_snapshot_id(intake.repo, sha)
    results: dict[str, ParseResult] = {}
    limits = set(discovery.limits_hit)
    for record in discovery.files:
        if deadline.expired():
            limits.add("max_seconds")
            break
        reason = discovery.skip_reasons.get(record.path)
        results[record.path] = (
            skipped_result(record, reason, snapshot_id)
            if reason
            else _parse(intake, record, registry, snapshot_id)
        )
    snapshot = Snapshot(
        id=snapshot_id,
        repo=intake.repo,
        commit_sha=sha,
        indexed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        indexer_version=__version__,
        source=intake.source,
        limits_hit=tuple(sorted(limits)),
    )
    return ScanReport(
        snapshot=snapshot,
        root=intake.root,
        used_git=discovery.used_git,
        reused_clone=intake.reused_clone,
        rows=_rows(discovery.files, results),
        discovery=discovery,
        tier_reasons=registry.fallback_reasons(),
    )


UNKNOWN_TYPE_REASON = "unknown file type: no language matches this file name or extension"


def _parse(
    intake: IntakeResult, record: FileRecord, registry: Registry, snapshot_id: str
) -> ParseResult:
    adapter = (
        TextAdapter(TEXT_LANGUAGE, UNKNOWN_TYPE_REASON)
        if record.language == TEXT_LANGUAGE
        else registry.adapter_for(record.language)
    )
    try:
        source = intake.root.joinpath(*record.path.split("/")).read_bytes()
    except OSError as exc:
        return skipped_result(record, f"unreadable: {exc}", snapshot_id)
    return adapter.parse(record.path, source, snapshot_id)


def skipped_result(record: FileRecord, reason: str, snapshot_id: str) -> ParseResult:
    """A TEXT-tier module node for a file that is not parsed, carrying the reason."""
    module = module_node(record.path, record.language, b"", snapshot_id, {"skipped_reason": reason})
    return ParseResult(record.path, record.language, Tier.TEXT, (module,))


def _content_sha(files: Sequence[FileRecord]) -> str:
    """A stand-in commit SHA for a folder outside git: a hash of every file's hash."""
    digest = hashlib.sha1(usedforsecurity=False)
    for record in files:
        digest.update(f"{record.path}\0{record.sha256}\n".encode())
    return digest.hexdigest()


def _rows(files: Sequence[FileRecord], results: dict[str, ParseResult]) -> list[LanguageRow]:
    """One row per (language, tier): a Python file too large to parse counts as text."""
    rows: dict[tuple[str, str], LanguageRow] = {}
    for record in files:
        result = results.get(record.path)
        tier = str(result.tier if result else record.tier)
        row = rows.setdefault((record.language, tier), LanguageRow(record.language, tier))
        row.files += 1
        row.bytes += record.size_bytes
        if result is None:
            row.unparsed += 1
            continue
        for node in result.nodes:
            row.nodes[str(node.kind)] = row.nodes.get(str(node.kind), 0) + 1
        row.raw_calls += len(result.calls)
        row.files_with_errors += 1 if result.errors else 0
    return sorted(rows.values(), key=lambda r: (-r.bytes, r.language, r.tier))


def _reason_group(reason: str) -> str:
    return reason.split(" (", 1)[0]


# Text output

_KIND_COLUMNS = [NodeKind.MODULE, NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION]


def render_text(report: ScanReport) -> str:
    data = report.to_json()
    snap = report.snapshot
    lines = [
        f"CodeAtlas {snap.indexer_version}: {snap.id}",
        f"source: {snap.source}  (files listed by {'git' if report.used_git else 'walk'})",
        "",
        "Language census",
    ]
    lines += _table(
        ["language", "tier", "files", "bytes"],
        [[r.language, r.tier, r.files, r.bytes] for r in report.rows],
    )
    lines += ["", "Per language"]
    header = ["language", "tier", *(str(k) for k in _KIND_COLUMNS), "raw calls", "errors"]
    body = [
        [
            r.language,
            r.tier,
            *(r.nodes.get(str(k), 0) for k in _KIND_COLUMNS),
            r.raw_calls,
            r.files_with_errors,
        ]
        for r in report.rows
    ]
    lines += _table(header, body)
    totals = data["totals"]
    assert isinstance(totals, dict)
    lines += [
        "",
        f"total: {totals['files']} files, {totals['bytes']} bytes, {totals['nodes']} nodes, "
        f"{totals['raw_calls']} raw calls, {len(report.rows)} languages",
    ]
    if totals["unparsed"]:
        lines.append(f"not parsed (time limit): {totals['unparsed']} files")
    skipped = data["skipped_files"]
    assert isinstance(skipped, dict)
    if skipped["count"]:
        reasons = ", ".join(f"{k}: {v}" for k, v in skipped["by_reason"].items())
        lines.append(f"not parsed, kept as text: {skipped['count']} files ({reasons})")
    lines += _skipped_path_lines(report.discovery.skipped)
    for language, reason in sorted(report.tier_reasons.items()):
        lines.append(f"tier note for {language}: {reason}")
    limits = ", ".join(snap.limits_hit) if snap.limits_hit else "none"
    lines.append(f"limits hit: {limits}")
    return "\n".join(lines)


_MAX_SKIPPED_LINES = 20


def _skipped_path_lines(skipped: Sequence[SkippedPath]) -> list[str]:
    if not skipped:
        return []
    lines = [f"not entered: {len(skipped)} paths"]
    for entry in skipped[:_MAX_SKIPPED_LINES]:
        count = f", {entry.file_count} files" if entry.reason == "excluded directory" else ""
        lines.append(f"  {entry.path} ({entry.reason}{count})")
    if len(skipped) > _MAX_SKIPPED_LINES:
        lines.append(f"  ... and {len(skipped) - _MAX_SKIPPED_LINES} more (see --json)")
    return lines


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    cells = [header, *[[str(c) for c in row] for row in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(header))]

    def fmt(row: list[str]) -> str:
        first = row[0].ljust(widths[0])
        rest = (c.rjust(w) for c, w in zip(row[1:], widths[1:], strict=True))
        return "  ".join([first, *rest]).rstrip()

    return [fmt(cells[0]), fmt(["-" * w for w in widths]), *(fmt(r) for r in cells[1:])]


# Entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeatlas", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"codeatlas {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="discover and parse a repository, print a census")
    scan_cmd.add_argument("source", help="a local folder or https://github.com/owner/repo[@ref]")
    scan_cmd.add_argument("--json", action="store_true", help="print the census as JSON")
    scan_cmd.add_argument("--config", type=Path, help="path to codeatlas.toml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        report = scan(args.source, config)
    except (IntakeError, OSError, ValueError) as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
