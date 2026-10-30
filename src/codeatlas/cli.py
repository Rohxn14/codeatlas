"""Command line: `codeatlas scan <path-or-url> [--json]`.

`scan` runs intake, discovery and every adapter, then prints a census of what it saw.
Each discovered file lands in exactly one language row, and each skipped file in the
skipped list with its reason, so the totals show that nothing was dropped.
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
from codeatlas.indexer.discover import TEXT_LANGUAGE, Discovery, discover
from codeatlas.indexer.generic.adapter import TextAdapter
from codeatlas.indexer.intake import IntakeError, IntakeResult, open_source
from codeatlas.indexer.registry import Registry
from codeatlas.models import FileRecord, NodeKind, ParseResult, Snapshot, make_snapshot_id


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
        by_reason = Counter(_reason_group(s.reason) for s in self.discovery.skipped)
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
            "skipped": {
                "count": len(self.discovery.skipped),
                "by_reason": dict(sorted(by_reason.items())),
                "files": [asdict(s) for s in self.discovery.skipped],
            },
            "tier_reasons": self.tier_reasons,
        }


def scan(source: str, config: Config, registry: Registry | None = None) -> ScanReport:
    """Intake, discovery and parsing of one source, stopping at the configured limits."""
    registry = registry or Registry()
    deadline = Deadline(config.max_seconds)
    intake = open_source(source, config)
    discovery = discover(intake.root, config, registry.tier_for, deadline)
    sha = intake.commit_sha or _content_sha(discovery.files)
    snapshot_id = make_snapshot_id(intake.repo, sha)
    results: dict[str, ParseResult] = {}
    limits = set(discovery.limits_hit)
    for record in discovery.files:
        if deadline.expired():
            limits.add("max_seconds")
            break
        results[record.path] = _parse(intake, record, registry, snapshot_id)
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


def _parse(
    intake: IntakeResult, record: FileRecord, registry: Registry, snapshot_id: str
) -> ParseResult:
    adapter = (
        TextAdapter(TEXT_LANGUAGE)
        if record.language == TEXT_LANGUAGE
        else registry.adapter_for(record.language)
    )
    try:
        source = intake.root.joinpath(*record.path.split("/")).read_bytes()
    except OSError as exc:
        text = TextAdapter(record.language, f"unreadable: {exc}")
        return text.parse(record.path, b"", snapshot_id)
    return adapter.parse(record.path, source, snapshot_id)


def _content_sha(files: Sequence[FileRecord]) -> str:
    """A stand-in commit SHA for a folder outside git: a hash of every file's hash."""
    digest = hashlib.sha1(usedforsecurity=False)
    for record in files:
        digest.update(f"{record.path}\0{record.sha256}\n".encode())
    return digest.hexdigest()


def _rows(files: Sequence[FileRecord], results: dict[str, ParseResult]) -> list[LanguageRow]:
    rows: dict[str, LanguageRow] = {}
    for record in files:
        row = rows.setdefault(record.language, LanguageRow(record.language, str(record.tier)))
        row.files += 1
        row.bytes += record.size_bytes
        result = results.get(record.path)
        if result is None:
            row.unparsed += 1
            continue
        for node in result.nodes:
            row.nodes[str(node.kind)] = row.nodes.get(str(node.kind), 0) + 1
        row.raw_calls += len(result.calls)
        row.files_with_errors += 1 if result.errors else 0
    return sorted(rows.values(), key=lambda r: (-r.bytes, r.language))


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
        ["language", "files", "bytes"],
        [[r.language, r.files, r.bytes] for r in report.rows],
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
    skipped = data["skipped"]
    assert isinstance(skipped, dict)
    if skipped["count"]:
        reasons = ", ".join(f"{k}: {v}" for k, v in skipped["by_reason"].items())
        lines.append(f"skipped: {skipped['count']} files ({reasons})")
    for language, reason in sorted(report.tier_reasons.items()):
        lines.append(f"tier note for {language}: {reason}")
    limits = ", ".join(snap.limits_hit) if snap.limits_hit else "none"
    lines.append(f"limits hit: {limits}")
    return "\n".join(lines)


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
