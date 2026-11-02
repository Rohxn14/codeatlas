"""Command line: `scan`, `index`, `view` and `export`.

`scan` runs intake, discovery and every adapter, then prints a census of what it saw.
Each discovered file lands in exactly one (language, tier) row, files that could not be
parsed included, and each folder or link that was not entered is listed once with its
reason and file count, so the totals show that nothing was dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from codeatlas import __version__
from codeatlas.config import Config, load_config
from codeatlas.indexer.discover import Discovery, SkippedPath
from codeatlas.indexer.intake import IntakeError
from codeatlas.indexer.pipeline.build import default_db_path
from codeatlas.indexer.pipeline.index import IndexReport, index_repository, load_report
from codeatlas.indexer.pipeline.parse import (  # noqa: F401  (re-exported for callers)
    UNKNOWN_TYPE_REASON,
    parse_source,
    skipped_result,
)
from codeatlas.indexer.registry import Registry
from codeatlas.models import (
    FileRecord,
    NodeKind,
    ParseResult,
    Snapshot,
)
from codeatlas.store import GraphStore
from codeatlas.view import build_view_data, latest_snapshot_id, write_view


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
    parsed = parse_source(source, config, registry)
    return ScanReport(
        snapshot=parsed.snapshot,
        root=parsed.intake.root,
        used_git=parsed.discovery.used_git,
        reused_clone=parsed.intake.reused_clone,
        rows=_rows(parsed.discovery.files, parsed.results),
        discovery=parsed.discovery,
        tier_reasons=registry.fallback_reasons(),
    )


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


# index, view, export


def render_index_text(report: IndexReport) -> str:
    """A short summary in the style of `scan`: census, edges, unresolved calls, problems."""
    snap, files, calls = report.snapshot, report.files, report.raw_calls
    lines = [
        f"CodeAtlas {snap['indexer_version']}: {snap['id']}",
        f"source: {snap['source']}",
        "",
        "Files by language and tier",
    ]
    tiers = ", ".join(f"{k}: {v}" for k, v in files["by_tier"].items())
    lines += _table(["language", "files"], [[k, v] for k, v in files["by_language"].items()])
    lines.append(f"total: {files['total']} files ({tiers}); skipped: {files['skipped']['total']}")
    lines += ["", "Nodes: " + _pairs(report.nodes["by_kind"])]
    lines.append(f"Edges: {report.edges['total']}")
    lines += ["  by kind: " + _pairs(report.edges["by_kind"])]
    lines += ["  by resolution: " + _pairs(report.edges["by_resolution"])]
    if report.edges["dropped"]:
        lines.append("  dropped: " + _pairs(report.edges["dropped"]))
    lines.append(
        f"Raw calls: {calls['total']}, resolved {calls['resolved']}, "
        f"unresolved {calls['unresolved']} ({_pairs(calls['unresolved_by_language']) or 'none'})"
    )
    lines += _problem_lines(report.problems)
    seconds = report.seconds
    lines.append("Seconds: " + ", ".join(f"{k} {v}" for k, v in seconds.items()))
    limits = ", ".join(snap["limits_hit"]) or "none"
    lines += [f"limits hit: {limits}", "", "Next: codeatlas view"]
    return "\n".join(lines)


def _pairs(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items())


def _problem_lines(problems: dict[str, Any]) -> list[str]:
    lines = ["Problems:"]
    errors = problems["files_with_errors"]
    lines.append(f"  files with parse errors: {len(errors)}")
    lines += [f"    {e['path']}: {e['errors'][0]}" for e in errors[:10]]
    lines += [f"  {text}" for text in problems["plugin_and_resolver_failures"]]
    if problems["languages_without_resolver"]:
        missing = ", ".join(problems["languages_without_resolver"])
        lines.append(f"  languages without a resolver: {missing}")
    return lines


def _open_store(args: argparse.Namespace, config: Config) -> tuple[GraphStore, str]:
    """The store and snapshot id for `view` and `export`; a clear error if there is none."""
    db_path = Path(args.db) if args.db else default_db_path(config)
    if not db_path.exists():
        raise ValueError(f"no database at {db_path}: run `codeatlas index <path-or-url>` first")
    snapshot_id = args.snapshot or latest_snapshot_id(db_path)
    if snapshot_id is None:
        raise ValueError(f"{db_path} holds no snapshot: run `codeatlas index <path-or-url>`")
    store = GraphStore(db_path)
    if store.get_snapshot(snapshot_id) is None:
        store.close()
        raise ValueError(f"no snapshot {snapshot_id!r} in {db_path}")
    return store, snapshot_id


def _run_index(args: argparse.Namespace, config: Config) -> int:
    db_path = Path(args.db) if args.db else default_db_path(config)
    report = index_repository(args.source, config, db_path, force=args.force)
    print(render_index_text(report))
    return 0


def _run_view(args: argparse.Namespace, config: Config) -> int:
    store, snapshot_id = _open_store(args, config)
    with store:
        saved = load_report(config, snapshot_id)
        data = build_view_data(store, snapshot_id, saved.to_dict() if saved else None, args.focus)
    out = Path(args.out) if args.out else Path(config.data_dir) / "view.html"
    write_view(data, out, open_browser=not args.no_open)
    omitted = data["omitted"]
    print(f"wrote {out} ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")
    if omitted["nodes"]:
        print(f"left out: {omitted['nodes']} nodes, {omitted['files']} files; use --focus <folder>")
    return 0


def _run_export(args: argparse.Namespace, config: Config) -> int:
    store, snapshot_id = _open_store(args, config)
    with store:
        data = store.export_json(snapshot_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


# Entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeatlas", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"codeatlas {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--config", type=Path, help="path to codeatlas.toml")
        return sub

    scan_cmd = add("scan", "discover and parse a repository, print a census")
    scan_cmd.add_argument("source", help="a local folder or https://github.com/owner/repo[@ref]")
    scan_cmd.add_argument("--json", action="store_true", help="print the census as JSON")

    index_cmd = add("index", "index a repository into the database and print a summary")
    index_cmd.add_argument("source", help="a local folder or https://github.com/owner/repo[@ref]")
    index_cmd.add_argument("--db", type=Path, help="database file")
    index_cmd.add_argument("--force", action="store_true", help="re-index an indexed commit")

    view_cmd = add("view", "write an HTML page of the graph and open it")
    view_cmd.add_argument("--db", type=Path, help="database file")
    view_cmd.add_argument("--snapshot", help="snapshot id (default: the latest)")
    view_cmd.add_argument("--focus", default="", help="show only files under this path prefix")
    view_cmd.add_argument("--out", type=Path, help="where to write the page")
    view_cmd.add_argument("--no-open", action="store_true", help="write the page, do not open it")

    export_cmd = add("export", "write the graph as JSON (contract section 8)")
    export_cmd.add_argument("--db", type=Path, help="database file")
    export_cmd.add_argument("--snapshot", help="snapshot id (default: the latest)")
    export_cmd.add_argument("--out", type=Path, required=True, help="JSON file to write")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "index":
            return _run_index(args, config)
        if args.command == "view":
            return _run_view(args, config)
        if args.command == "export":
            return _run_export(args, config)
        report = scan(args.source, config)
    except (IntakeError, OSError, ValueError, KeyError) as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
