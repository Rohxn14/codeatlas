"""Command line: `codeatlas scan <path-or-url> [--json]`.

`scan` runs intake, discovery and every file's adapter, then prints a language census and
a per-language table. Every discovered file lands in exactly one row, so the totals show
that nothing was skipped without a recorded reason.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from codeatlas import __version__
from codeatlas.config import Config, load_config
from codeatlas.indexer.discover import Discovery, discover
from codeatlas.indexer.intake import Checkout, content_sha, intake
from codeatlas.indexer.registry import Registry, default_registry
from codeatlas.models import FileRecord, NodeKind, ParseResult, Snapshot, make_snapshot_id

_ERROR_SAMPLES = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codeatlas", description=__doc__)
    parser.add_argument("--version", action="version", version=f"codeatlas {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="census of a local folder or GitHub repository")
    scan_cmd.add_argument("source", help="a local path or https://github.com/owner/repo[@ref]")
    scan_cmd.add_argument("--json", action="store_true", help="print the report as JSON")
    scan_cmd.add_argument("--config", type=Path, help="path to codeatlas.toml")
    args = parser.parse_args(argv)

    try:
        report = scan(args.source, load_config(args.config))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"codeatlas: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    return 0


def scan(source: str, config: Config, registry: Registry | None = None) -> dict[str, object]:
    """Index `source` without storing anything, and return the census report."""
    registry = registry or default_registry()
    started = time.monotonic()
    deadline = started + config.limits.max_seconds
    checkout = intake(source, config.repos_dir)
    found = discover(checkout.root, config.limits, registry.tier_for, deadline)
    snapshot = _snapshot(checkout, found)
    results: list[ParseResult] = []
    limits_hit = list(found.limits_hit)
    for record in found.files:
        if time.monotonic() > deadline:
            if "max_seconds" not in limits_hit:
                limits_hit.append("max_seconds")
            break
        source_bytes = (checkout.root / record.path).read_bytes()
        adapter = registry.adapter_for(record.language)
        results.append(adapter.parse(record.path, source_bytes, snapshot.id))
    snapshot = Snapshot(**{**asdict(snapshot), "limits_hit": tuple(limits_hit)})
    return _report(snapshot, checkout, found, results, time.monotonic() - started)


def _snapshot(checkout: Checkout, found: Discovery) -> Snapshot:
    sha = checkout.commit_sha or content_sha([(f.path, f.sha256) for f in found.files])
    return Snapshot(
        id=make_snapshot_id(checkout.repo, sha),
        repo=checkout.repo,
        commit_sha=sha,
        indexed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        indexer_version=__version__,
        source=checkout.source,
        limits_hit=found.limits_hit,
    )


def _report(
    snapshot: Snapshot,
    checkout: Checkout,
    found: Discovery,
    results: list[ParseResult],
    seconds: float,
) -> dict[str, object]:
    by_path = {r.path: r for r in results}
    rows: dict[str, dict[str, object]] = {}
    for record in found.files:
        row = rows.setdefault(record.language, _empty_row(record))
        row["files"] += 1
        row["bytes"] += record.size_bytes
        result = by_path.get(record.path)
        if result is None:
            row["not_parsed"] += 1
            continue
        _add_result(row, result)
    languages = sorted(rows.values(), key=lambda r: (-r["bytes"], r["language"]))
    return {
        "snapshot": {**asdict(snapshot), "limits_hit": list(snapshot.limits_hit)},
        "root": checkout.root.as_posix(),
        "reused_clone": checkout.reused,
        "seconds": round(seconds, 2),
        "languages": languages,
        "skipped": [asdict(s) for s in found.skipped],
        "totals": {
            "files": len(found.files),
            "files_in_rows": sum(r["files"] for r in languages),
            "bytes": sum(f.size_bytes for f in found.files),
            "parsed": len(results),
            "skipped": len(found.skipped),
        },
    }


def _empty_row(record: FileRecord) -> dict[str, object]:
    return {
        "language": record.language,
        "tier": str(record.tier),
        "files": 0,
        "bytes": 0,
        "nodes": {},
        "calls": 0,
        "files_with_errors": 0,
        "not_parsed": 0,
        "error_samples": [],
    }


def _add_result(row: dict[str, object], result: ParseResult) -> None:
    kinds = Counter(str(n.kind) for n in result.nodes)
    nodes = row["nodes"]
    for kind, count in kinds.items():
        nodes[kind] = nodes.get(kind, 0) + count
    row["calls"] += len(result.calls)
    if result.errors:
        row["files_with_errors"] += 1
        if len(row["error_samples"]) < _ERROR_SAMPLES:
            row["error_samples"].append(f"{result.path}: {result.errors[0]}")


def render(report: dict[str, object]) -> str:
    """The report as plain-text tables."""
    snap = report["snapshot"]
    totals = report["totals"]
    languages = report["languages"]
    lines = [
        f"{snap['id']}  ({snap['source']}, {report['seconds']}s)",
        "",
        "Language census",
        f"  {'language':<14}{'files':>8}{'bytes':>14}",
    ]
    lines += [f"  {r['language']:<14}{r['files']:>8}{r['bytes']:>14,}" for r in languages]
    kinds = [str(k) for k in NodeKind if any(str(k) in r["nodes"] for r in languages)]
    header = "".join(f"{k:>11}" for k in kinds)
    lines += ["", "Per language", f"  {'language':<14}{'tier':<12}{'files':>7}{header}"
              f"{'calls':>8}{'errors':>8}"]
    for r in languages:
        counts = "".join(f"{r['nodes'].get(k, 0):>11}" for k in kinds)
        lines.append(
            f"  {r['language']:<14}{r['tier']:<12}{r['files']:>7}{counts}"
            f"{r['calls']:>8}{r['files_with_errors']:>8}"
        )
    lines += ["", f"Files: {totals['files']} discovered, {totals['files_in_rows']} in rows, "
              f"{totals['parsed']} parsed, {totals['skipped']} skipped"]
    reasons = Counter(_reason_group(s["reason"]) for s in report["skipped"])
    lines += [f"  skipped, {reason}: {count}" for reason, count in sorted(reasons.items())]
    samples = [s for r in languages for s in r["error_samples"]]
    if samples:
        lines += ["", "Parse errors (samples)"] + [f"  {s}" for s in samples]
    limits = snap["limits_hit"]
    lines += ["", f"Limits hit: {', '.join(limits)}" if limits else "Limits hit: none"]
    return "\n".join(lines)


def _reason_group(reason: str) -> str:
    return reason.split(" (", 1)[0]


if __name__ == "__main__":
    sys.exit(main())
