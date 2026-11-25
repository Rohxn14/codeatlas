"""`index_repository`: build a snapshot once, save a report of what happened, reuse it.

The report is the file the acceptance suite (T10) reads, so its field names are stable
(they are listed in `docs/explainers/pipeline.md`).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from codeatlas.config import Config
from codeatlas.indexer.pipeline.build import AlreadyIndexed, BuildResult, build_graph
from codeatlas.indexer.pipeline.parse import Progress, no_progress
from codeatlas.models import NodeKind, Snapshot
from codeatlas.repo import summarize
from codeatlas.search.embed import Embedder, build_embeddings
from codeatlas.store import GraphStore

SECONDS_STEPS = ("intake", "discover", "parse", "repo_layer", "write", "resolve", "link", "total")


@dataclass(slots=True)
class IndexReport:
    """What one index run did; `to_dict()` is the JSON saved next to the database."""

    snapshot: dict[str, Any]
    seconds: dict[str, float]
    files: dict[str, Any]
    nodes: dict[str, Any]
    edges: dict[str, Any]
    raw_calls: dict[str, Any]
    problems: dict[str, Any]
    repo_layer: dict[str, Any] = field(default_factory=dict)
    # {"model", "symbols", "seconds"}, or {"model", "error"}; {} when none were built.
    embeddings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexReport:
        """A saved report; a field added since it was saved takes its default.

        A missing field must not fail: `load_report` would return None, and
        `index_repository` would then rebuild the whole snapshot.
        """
        return cls(**{name: data[name] for name in cls.__dataclass_fields__ if name in data})


def reports_dir(config: Config) -> Path:
    return Path(config.data_dir) / "reports"


def report_path(config: Config, snapshot_id: str) -> Path:
    """`@` and `/` in a snapshot id are not safe in every file name, so both become `_`."""
    safe = snapshot_id.replace("@", "_").replace("/", "_")
    return reports_dir(config) / f"{safe}.json"


def load_report(config: Config, snapshot_id: str) -> IndexReport | None:
    path = report_path(config, snapshot_id)
    try:
        return IndexReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def index_repository(
    source: str,
    config: Config,
    db_path: Path,
    force: bool = False,
    progress: Progress = no_progress,
    embedder: Embedder | None = None,
) -> IndexReport:
    """Index `source` into the database at `db_path`, or return the saved report.

    An already-indexed commit returns its report unless `force`. The commit is only known
    after parsing, so a repeat still parses every file before the saved report is found.
    With an `embedder`, a new snapshot also gets the vectors vector search reads
    (`embed_snapshot`); tests and libraries pass none, so they never load a model.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with GraphStore(db_path) as store:
        try:
            built = build_graph(source, store, config, replace_existing=force,
                                progress=progress)
        except AlreadyIndexed as exc:
            saved = load_report(config, exc.snapshot_id)
            if saved is not None:
                return saved
            # The report file was deleted: the store is intact, so rebuild to recreate it.
            built = build_graph(source, store, config, replace_existing=True,
                                progress=progress)
        report = build_report(store, built)
        _save_report(config, report)
        if embedder is not None:
            # After the save: embedding can take minutes, and stopping it half way must
            # not lose the report, which would make the next run rebuild everything.
            report.embeddings = embed_snapshot(store, report.snapshot["id"], embedder,
                                               progress)
            _save_report(config, report)
    return report


def _save_report(config: Config, report: IndexReport) -> None:
    path = report_path(config, report.snapshot["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")


def embed_snapshot(store: GraphStore, snapshot_id: str, embedder: Embedder,
                   progress: Progress = no_progress) -> dict[str, Any]:
    """Build the vectors vector search reads; a failure is recorded, never raised.

    Vectors used to be built only by `codeatlas search --embed`, so on Nov 19 none of the
    owner's six snapshots had one, and the agent's semantic search was text search only.
    A model that cannot be loaded (offline on first use) leaves the index usable and the
    report says why. Bodies are left out, as `search --embed` does: with 15 body lines
    each, PitwallOS took 187 s instead of 50 s.
    """
    progress("embed", "")
    started = time.perf_counter()
    try:
        count = build_embeddings(
            store, snapshot_id, embedder,
            on_batch=lambda done, total: progress("embed", f"{done:,} of {total:,} symbols"))
    except Exception as exc:  # vector search is optional: text search still works
        return {"model": embedder.model, "error": f"{type(exc).__name__}: {exc}"}
    return {"model": embedder.model, "symbols": count,
            "seconds": round(time.perf_counter() - started, 1)}


def build_report(store: GraphStore, built: BuildResult) -> IndexReport:
    """Count what the store holds, so the report matches the database, not the plan."""
    snapshot = built.parsed.snapshot
    sid = snapshot.id
    nodes = store.nodes(sid)
    edges = store.edges(sid)
    files = store.files(sid)
    return IndexReport(
        snapshot=_snapshot_dict(snapshot),
        seconds={step: round(built.seconds.get(step, 0.0), 3) for step in SECONDS_STEPS},
        files=_files_section(built),
        nodes={"total": len(nodes), "by_kind": _counts(str(n.kind) for n in nodes)},
        edges={
            "total": len(edges),
            "by_kind": _counts(str(e.kind) for e in edges),
            "by_resolution": _counts(str(e.resolution) for e in edges),
            "dropped": dict(sorted(built.edges_dropped.items())),
        },
        raw_calls=_calls_section(store, sid),
        problems=_problems_section(built, nodes),
        repo_layer=summarize(files, nodes, edges, built.analyzers),  # type: ignore[arg-type]
    )


def _snapshot_dict(snapshot: Snapshot) -> dict[str, Any]:
    data = asdict(snapshot)
    data["limits_hit"] = list(snapshot.limits_hit)
    return data


def _counts(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _files_section(built: BuildResult) -> dict[str, Any]:
    """Tier is the tier that parsed the file: a skipped Python file counts as text."""
    results = built.parsed.results
    reasons = {
        n.path: str(n.attrs["skipped_reason"])
        for r in results.values()
        for n in r.nodes[:1]
        if n.attrs.get("skipped_reason")
    }
    skipped = Counter(reason.split(" (", 1)[0] for reason in reasons.values())
    return {
        "total": len(results),
        "by_tier": _counts(str(r.tier) for r in results.values()),
        "by_language": _counts(r.language for r in results.values()),
        "skipped": {"total": len(reasons), "by_reason": dict(sorted(skipped.items()))},
        "not_entered": _not_entered(built),
    }


def _not_entered(built: BuildResult) -> dict[str, Any]:
    """Folders, links and submodules discovery never went into (`node_modules/`, say).

    Their files have no nodes at all, so without this section they would vanish from the
    report silently; `scan` already lists them.
    """
    skipped = built.parsed.discovery.skipped
    return {
        "total": len(skipped),
        "files": sum(s.file_count for s in skipped),
        "by_reason": _counts(s.reason for s in skipped),
        "paths": [{"path": s.path, "reason": s.reason, "files": s.file_count}
                  for s in skipped[:200]],
    }


def _calls_section(store: GraphStore, snapshot_id: str) -> dict[str, Any]:
    language_of = {f.path: f.language for f in store.files(snapshot_id)}
    calls = store.raw_calls(snapshot_id)
    unresolved = Counter(
        language_of.get(call.caller_key.split("::", 1)[0], "unknown")
        for call, resolved in calls
        if not resolved
    )
    return {
        "total": len(calls),
        "resolved": sum(1 for _, resolved in calls if resolved),
        "unresolved": sum(unresolved.values()),
        "unresolved_by_language": dict(sorted(unresolved.items())),
    }


def _problems_section(built: BuildResult, nodes: list[Any]) -> dict[str, Any]:
    with_errors = [
        {"path": n.path, "errors": list(n.attrs["errors"])}  # type: ignore[call-overload]
        for n in nodes
        if n.kind is NodeKind.MODULE and n.attrs.get("errors")
    ]
    return {
        "files_with_errors": with_errors,
        "plugin_and_resolver_failures": list(built.problems),
        "languages_without_resolver": list(built.languages_without_resolver),
    }
