"""Command line: `scan`, `index`, `view`, `export`, `search`, `ask`, `impact`, `tests`, `mcp`.

`scan` runs intake, discovery and every adapter, then prints a census of what it saw.
Each discovered file lands in exactly one (language, tier) row, files that could not be
parsed included, and each folder or link that was not entered is listed once with its
reason and file count, so the totals show that nothing was dropped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from codeatlas import __version__
from codeatlas.config import Config, load_config
from codeatlas.impact.diff import parse_diff
from codeatlas.impact.models import Change
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
from codeatlas.view.data import focus_matches


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
    not_entered = files.get("not_entered") or {}
    if not_entered.get("total"):
        lines.append(f"not entered: {not_entered['total']} folders or links "
                     f"({not_entered['files']} files): " + _pairs(not_entered["by_reason"]))
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
        if not focus_matches(store, snapshot_id, args.focus):
            print(f"--focus {args.focus!r} matches no file of {snapshot_id}", file=sys.stderr)
            return 2
        saved = load_report(config, snapshot_id)
        data = build_view_data(store, snapshot_id, saved.to_dict() if saved else None, args.focus)
        if args.impact:
            data["impact"] = _view_impact(store, snapshot_id, args.impact)
    out = Path(args.out) if args.out else Path(config.data_dir) / "view.html"
    write_view(data, out, open_browser=not args.no_open)
    omitted = data["omitted"]
    print(f"wrote {out} ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")
    if omitted["nodes"]:
        print(f"left out: {omitted['nodes']} nodes, {omitted['files']} files; use --focus <folder>")
    return 0


def _view_impact(store: GraphStore, snapshot_id: str, diff_file: Path) -> dict[str, Any]:
    """The `--impact` block of the page: what the diff changes and what it could break."""
    from codeatlas.impact import impact
    from codeatlas.view.data import impact_block

    changes = _parse_checked(read_diff_text(diff_file))
    return impact_block(impact(store, snapshot_id, changes))


def _run_export(args: argparse.Namespace, config: Config) -> int:
    store, snapshot_id = _open_store(args, config)
    with store:
        data = store.export_json(snapshot_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


# search, ask, impact, tests, mcp: thin front ends over the query-time modules


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def _run_search(args: argparse.Namespace, config: Config) -> int:
    from codeatlas.llm.config import load_llm_config
    from codeatlas.llm.embeddings import EmbeddingClient
    from codeatlas.search.embed import build_embeddings
    from codeatlas.search.hybrid import HybridSearch

    store, snapshot_id = _open_store(args, config)
    with store:
        embedder = EmbeddingClient.from_config(load_llm_config(args.config))
        notes: list[str] = []
        if args.embed:
            try:
                notes.append(f"embedded {build_embeddings(store, snapshot_id, embedder)} new nodes")
            except Exception as exc:  # no model here: search still works with BM25
                notes.append(f"could not embed ({exc}); searching with BM25 only")
        search = HybridSearch(store, snapshot_id, embedder)
        hits = search.search(args.query, k=args.k, expand=not args.no_expand)
        notes += search.notes
    rows = [_hit_row(rank, hit) for rank, hit in enumerate(hits, start=1)]
    if args.json:
        _print_json({"snapshot": snapshot_id, "query": args.query, "hits": rows, "notes": notes})
        return 0
    lines = [f"{r['rank']:>3}  {r['score']:.4f}  {r['kind']:<9} {r['key']}  "
             f"{r['path']}:{r['line']}  [{'+'.join(r['sources'])}]" for r in rows]
    print("\n".join(lines) if lines else "no hits")
    for note in notes:
        print(f"note: {note}")
    return 0


def _hit_row(rank: int, hit: Any) -> dict[str, Any]:
    node = hit.node
    return {"rank": rank, "score": round(hit.score, 6), "kind": str(node.kind), "key": node.key,
            "path": node.path, "line": node.span.start_line, "sources": list(hit.sources)}


LLM_KEYS = ("GROQ_API_KEY", "GEMINI_API_KEY")


def _run_ask(args: argparse.Namespace, config: Config) -> int:
    if not any(os.environ.get(name) for name in LLM_KEYS):
        print("codeatlas: ask needs a language model: set GROQ_API_KEY or GEMINI_API_KEY",
              file=sys.stderr)
        return 2
    from codeatlas.agent.loop import ask
    from codeatlas.llm import LLMClient, LLMError
    from codeatlas.llm.config import load_llm_config

    store, snapshot_id = _open_store(args, config)
    try:
        with store:
            client = LLMClient.from_config(load_llm_config(args.config))
            answer = ask(args.question, store, snapshot_id, client,
                         max_steps=args.max_steps, config=config)
    except LLMError as exc:  # the trajectory so far is already on disk
        print(f"codeatlas: the language model could not be reached: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json({
            "snapshot": snapshot_id, "answer": answer.text, "steps": answer.steps,
            "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens,
            "limit_hit": answer.limit_hit, "trajectory": _posix(answer.trajectory_path),
            "citations": [asdict(c) for c in answer.citations],
        })
        return 0
    print(answer.text)
    print("\nCitations:")
    for c in answer.citations:
        print(f"  {'ok     ' if c.valid else 'INVALID'} {c.text}"
              + ("" if c.valid else f"  ({c.reason})"))
    if not answer.citations:
        print("  none")
    print(f"\nSteps: {answer.steps}  tokens in/out: {answer.input_tokens}/{answer.output_tokens}")
    print(f"Trajectory: {_posix(answer.trajectory_path)}")
    return 0


def _posix(path: Path | None) -> str | None:
    return path.as_posix() if path is not None else None


def read_changes(args: argparse.Namespace, store: GraphStore, snapshot_id: str,
                 config: Config) -> list[Change]:
    """The change from `--diff FILE`, `--diff -`, `--git REV` or `--files`."""
    if args.files:
        return [Change(_repo_path(f)) for f in args.files]
    if args.git:
        return _parse_checked(_git_diff(args.git, store, snapshot_id, config))
    return _parse_checked(read_diff_text(args.diff))


def read_diff_text(source: str | Path) -> str:
    """A diff from a file, or from stdin for `-`, always decoded as UTF-8.

    stdin is read as bytes: `sys.stdin.read()` uses the console's code page on Windows
    (often cp1252), which cannot decode a UTF-8 diff.
    """
    if str(source) == "-":
        return sys.stdin.buffer.read().decode("utf-8", errors="replace")
    return Path(source).read_text(encoding="utf-8", errors="replace")


def _parse_checked(text: str) -> list[Change]:
    """`parse_diff`, but text that is not blank and holds no file header is an error."""
    changes = parse_diff(text)
    if text.strip() and not changes:
        raise ValueError("no file headers found in the diff")
    return changes


def _repo_path(path: str) -> str:
    """`.\\backend\\app.py` from PowerShell -> `backend/app.py`, as the store keeps it."""
    clean = path.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean


def _git_diff(rev: str, store: GraphStore, snapshot_id: str, config: Config) -> str:
    """`git diff REV` in the snapshot's checkout. This runs git only, never repository code."""
    from codeatlas.agent.tools import ToolContext

    root = ToolContext(store, snapshot_id, config).repo_root()
    if root is None:
        raise ValueError(f"cannot find the checkout of {snapshot_id}: use --diff or --files")
    _require_checkout_at_snapshot(root, store.get_snapshot(snapshot_id))
    # No external diff driver, no textconv filter and no fsmonitor hook: git only reads files.
    done = _git(root, "-c", "core.fsmonitor=false", "diff", "--relative", "--no-color",
                "--no-ext-diff", "--no-textconv", rev, "--")
    if done.returncode != 0:
        raise ValueError(f"git diff {rev} failed in {root.as_posix()}: {done.stderr.strip()}")
    return done.stdout


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
    except FileNotFoundError as exc:
        raise ValueError("git is not installed or not on PATH") from exc


def _require_checkout_at_snapshot(root: Path, snapshot: Snapshot | None) -> None:
    """`git diff REV` compares with the working tree, so it only describes the snapshot
    while HEAD is still the indexed commit; otherwise the result would be about newer code."""
    if snapshot is None:
        return
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode == 0 and head.stdout.strip() != snapshot.commit_sha:
        raise ValueError(
            f"the checkout at {root.as_posix()} is at {head.stdout.strip()[:12]}, but the "
            f"snapshot is {snapshot.commit_sha[:12]}: run `codeatlas index --force` on it, "
            "or use --diff or --files")


def _impact_result(args: argparse.Namespace, config: Config) -> tuple[str, Any, Any, int]:
    """Run the engine on the requested change: snapshot, result, engine, changed file count."""
    from codeatlas.impact import ImpactConfig, ImpactEngine

    store, snapshot_id = _open_store(args, config)
    with store:
        changes = read_changes(args, store, snapshot_id, config)
        defaults = ImpactConfig()
        tuning = ImpactConfig(depth=args.depth if args.depth is not None else defaults.depth,
                              decay=args.decay if args.decay is not None else defaults.decay)
        engine = ImpactEngine(store, snapshot_id, tuning)
        result = engine.impact(changes)
    return snapshot_id, result, engine, len({c.path for c in changes})


def evidence_line(evidence: Any) -> str:
    """One line per evidence: signal, score, then the hop path or the detail."""
    steps = [evidence.path[0].key] if evidence.path else []
    for hop in evidence.path[1:]:
        conf = f" {hop.confidence:g}" if hop.confidence is not None else ""
        steps.append(f"<-{hop.kind}{conf}- {hop.key}")
    text = " ".join(steps) or evidence.detail
    if steps and evidence.detail:
        text += f" ({evidence.detail})"
    return f"{evidence.signal} {evidence.score:.3f}: {text}"


def _scored_rows(items: Sequence[Any], top: int) -> list[dict[str, Any]]:
    return [{"rank": rank, "key": t.key, "kind": str(t.kind), "path": t.path,
             "score": round(t.score, 4), "evidence": [evidence_line(e) for e in t.evidence]}
            for rank, t in enumerate(items[:top], start=1)]


def _scored_lines(rows: list[dict[str, Any]], total: int, noun: str) -> list[str]:
    lines = [f"{total} {noun}" + (f", top {len(rows)} shown" if len(rows) < total else "")]
    for r in rows:
        lines.append(f"{r['rank']:>3}  {r['score']:.3f}  {r['kind']:<9} {r['key']}")
        if r["evidence"]:
            lines.append(f"       {r['evidence'][0]}")
    return lines


def _head_lines(snapshot_id: str, files: int, result: Any) -> list[str]:
    changed = ", ".join(result.changed[:10]) or "none"
    if files == 0:
        return [f"snapshot {snapshot_id}: no changes", ""]
    more = f" and {len(result.changed) - 10} more" if len(result.changed) > 10 else ""
    return [f"snapshot {snapshot_id}: {files} changed files, "
            f"{len(result.changed)} changed symbols", f"changed: {changed}{more}", ""]


def _warning_lines(result: Any) -> list[str]:
    if not result.warnings:
        return []
    return ["", f"warnings ({len(result.warnings)}):", *(f"  {w}" for w in result.warnings)]


def _run_impact(args: argparse.Namespace, config: Config) -> int:
    snapshot_id, result, _engine, files = _impact_result(args, config)
    rows = _scored_rows(result.targets, args.top)
    if args.json:
        _print_json({"snapshot": snapshot_id, "changed": list(result.changed),
                     "total": len(result.targets), "targets": rows,
                     "warnings": list(result.warnings)})
        return 0
    lines = _head_lines(snapshot_id, files, result)
    lines += _scored_lines(rows, len(result.targets), "targets")
    print("\n".join(lines + _warning_lines(result)))
    return 0


def _run_tests(args: argparse.Namespace, config: Config) -> int:
    from codeatlas.impact.evaluate import all_test_files

    snapshot_id, result, engine, files = _impact_result(args, config)
    rows = _scored_rows(result.tests, args.top)
    threshold = engine.config.test_threshold
    picked = [p.path for p in result.test_files(threshold)]
    universe = all_test_files(engine)
    skipped = 1 - len(set(picked) & universe) / len(universe) if universe else 0.0
    summary = {"threshold": threshold, "selected_files": picked,
               "test_files": len(universe), "skipped_share": round(skipped, 4)}
    if args.json:
        _print_json({"snapshot": snapshot_id, "changed": list(result.changed),
                     "total": len(result.tests), "tests": rows, **summary,
                     "warnings": list(result.warnings)})
        return 0
    lines = _head_lines(snapshot_id, files, result)
    lines += _scored_lines(rows, len(result.tests), "tests")
    lines += ["", f"test files to run (score >= {threshold:g}): {len(picked)} of "
              f"{len(universe)}; skipped share {skipped:.0%}"]
    lines += [f"  {path}" for path in picked[:args.top]]
    if len(picked) > args.top:
        lines.append(f"  ... and {len(picked) - args.top} more (see --json)")
    print("\n".join(lines + _warning_lines(result)))
    return 0


def _run_mcp(args: argparse.Namespace, config: Config) -> int:
    import asyncio

    from codeatlas.agent.mcp_server import serve_stdio
    from codeatlas.agent.tools import ToolSet

    store, snapshot_id = _open_store(args, config)
    print(f"codeatlas MCP server on stdio, snapshot {snapshot_id}", file=sys.stderr)
    with store:
        asyncio.run(serve_stdio(ToolSet(store, snapshot_id, config)))
    return 0


_THIS_MACHINE = frozenset({"127.0.0.1", "localhost"})


def _run_serve(args: argparse.Namespace, config: Config) -> int:
    """Start the local web app. The web packages are optional, so they are imported here."""
    try:
        import uvicorn

        from codeatlas.web import create_app
    except ImportError as exc:
        raise ValueError(
            f'the web app needs extra packages ({exc.name}): run `pip install -e ".[web]"`'
        ) from exc
    db_path = Path(args.db) if args.db else default_db_path(config)
    local = args.host in _THIS_MACHINE
    # Indexing reads any folder its user names. That is fine for the person at this
    # machine and not for anyone else who can reach the port.
    read_only = args.read_only or not local
    url = f"http://{args.host}:{args.port}/"
    mode = " read-only" if read_only else ""
    print(f"codeatlas: serving {db_path}{mode} at {url} (Ctrl+C to stop)")
    if not db_path.exists():
        print("codeatlas: no database yet; index a repository from the page"
              if not read_only else "codeatlas: no database yet; run `codeatlas index` first")
    if not args.no_open:
        webbrowser.open(url)
    app = create_app(db_path, config, read_only=read_only,
                     hosts=sorted(_THIS_MACHINE) if local else None)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
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
    view_cmd.add_argument("--impact", type=Path, metavar="DIFF",
                          help="highlight what this diff changes and could break")

    export_cmd = add("export", "write the graph as JSON (contract section 8)")
    export_cmd.add_argument("--db", type=Path, help="database file")
    export_cmd.add_argument("--snapshot", help="snapshot id (default: the latest)")
    export_cmd.add_argument("--out", type=Path, required=True, help="JSON file to write")

    search_cmd = _query_command(add, "search", "hybrid search: BM25, vectors, one graph hop")
    search_cmd.add_argument("query")
    search_cmd.add_argument("-k", "--k", type=int, default=10, help="hits to return")
    search_cmd.add_argument("--no-expand", action="store_true", help="skip the graph hop")
    search_cmd.add_argument("--embed", action="store_true", help="build missing embeddings first")

    ask_cmd = _query_command(add, "ask", "answer a question with the agent (needs an LLM key)")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--max-steps", type=int, default=20)

    for name, help_text in (("impact", "rank what a change could break"),
                            ("tests", "rank the tests a change should run")):
        _change_inputs(_query_command(add, name, help_text))

    serve_cmd = add("serve", "open the local web app")
    serve_cmd.add_argument("--db", type=Path, help="database file")
    # 127.0.0.1 is this machine only. Another host would let other machines read the index.
    serve_cmd.add_argument("--host", default="127.0.0.1", help="address to listen on")
    serve_cmd.add_argument("--port", type=int, default=8765, help="port to listen on")
    serve_cmd.add_argument("--no-open", action="store_true", help="do not open a browser")
    serve_cmd.add_argument("--read-only", action="store_true",
                           help="no indexing or removing from the page (always on when "
                                "--host is not this machine)")

    mcp_cmd = add("mcp", "serve the agent's tools over MCP on stdio")
    mcp_cmd.add_argument("--db", type=Path, help="database file")
    mcp_cmd.add_argument("--snapshot", help="snapshot id (default: the latest)")
    return parser


def _query_command(add: Any, name: str, help_text: str) -> argparse.ArgumentParser:
    sub: argparse.ArgumentParser = add(name, help_text)
    sub.add_argument("--db", type=Path, help="database file")
    sub.add_argument("--snapshot", help="snapshot id (default: the latest)")
    sub.add_argument("--json", action="store_true", help="print JSON")
    return sub


def _change_inputs(sub: argparse.ArgumentParser) -> None:
    """The change, given one way, and the engine's tunable numbers."""
    source = sub.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", metavar="FILE", help="a unified diff file, or - for stdin")
    source.add_argument("--git", metavar="REV", help="run `git diff REV` in the checkout")
    source.add_argument("--files", nargs="+", metavar="PATH", help="whole files changed")
    sub.add_argument("--depth", type=int, help="hops walked from a changed symbol (default 4)")
    sub.add_argument("--decay", type=float, help="score kept per hop, 0 to 1 (default 0.8)")
    sub.add_argument("--top", type=int, default=20, help="rows to print (default 20)")


_RUNNERS = {
    "index": _run_index, "view": _run_view, "export": _run_export, "search": _run_search,
    "ask": _run_ask, "impact": _run_impact, "tests": _run_tests, "mcp": _run_mcp,
    "serve": _run_serve,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        runner = _RUNNERS.get(args.command)
        if runner is not None:
            return runner(args, config)
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
