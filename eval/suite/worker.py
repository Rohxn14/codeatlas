"""Index one folder into a database and write its metrics as JSON; runs in a child process.

A child process, so the runner can enforce a wall-clock limit by killing it and can read
the peak memory of exactly one build. Invoked as
`python -m eval.suite.worker ROOT DB OUT MAX_SECONDS`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from codeatlas.config import Config
from codeatlas.indexer.pipeline import BuildResult, build_graph
from codeatlas.store import GraphStore

_REASON_LIMIT = 100
_ERROR_SAMPLES = 5


def peak_memory_mb() -> float | None:
    """Peak resident memory of this process, or None where the platform does not report it."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024  # bytes on macOS, KB on Linux
    return round(peak / divisor, 1)


def collect_metrics(db_path: Path, result: BuildResult) -> dict[str, object]:
    """Everything the scoreboard shows for one finished build, read back from the database."""
    snapshot_id = result.snapshot_id
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        tiers = _counter(
            conn,
            "SELECT tier, COUNT(*) FROM files WHERE snapshot_id = ? GROUP BY tier",
            snapshot_id,
        )
        languages = _counter(
            conn,
            "SELECT language, COUNT(*) FROM files WHERE snapshot_id = ? GROUP BY language",
            snapshot_id,
        )
        nodes = _counter(
            conn,
            "SELECT kind, COUNT(*) FROM nodes WHERE snapshot_id = ? GROUP BY kind",
            snapshot_id,
        )
        edges = _counter(
            conn,
            "SELECT kind, COUNT(*) FROM edges WHERE snapshot_id = ? GROUP BY kind",
            snapshot_id,
        )
        raw, resolved = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(resolved), 0) FROM raw_calls WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        module_attrs = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT attrs_json FROM nodes WHERE snapshot_id = ? AND kind = 'module'",
                (snapshot_id,),
            )
        ]
    finally:
        conn.close()
    errors = [a["errors"] for a in module_attrs if a.get("errors")]
    skipped = Counter(
        _short(str(a["skipped_reason"])) for a in module_attrs if a.get("skipped_reason")
    )
    snapshot = result.parsed.snapshot
    return {
        "snapshot_id": snapshot_id,
        "files": sum(tiers.values()),
        "files_by_tier": dict(tiers),
        "files_by_language": dict(languages.most_common()),
        "files_with_parse_errors": len(errors),
        "parse_errors": sum(len(e) for e in errors),
        "parse_error_samples": [str(e[0])[: _REASON_LIMIT * 2] for e in errors[:_ERROR_SAMPLES]],
        "skipped_by_reason": dict(skipped.most_common()),
        "nodes_by_kind": dict(nodes),
        "edges_by_kind": dict(edges),
        "raw_calls": raw,
        "resolved_calls": int(resolved),
        "unresolved_share": round(1 - resolved / raw, 4) if raw else None,
        "limits_hit": list(snapshot.limits_hit),
        "problems": list(result.problems),
        "languages_without_resolver": list(result.languages_without_resolver),
        "edges_dropped": dict(result.edges_dropped),
    }


def _counter(conn: sqlite3.Connection, sql: str, snapshot_id: str) -> Counter[str]:
    return Counter({key: count for key, count in conn.execute(sql, (snapshot_id,))})


def _short(reason: str) -> str:
    """A skip reason without the per-file detail, so equal reasons group together."""
    return (
        reason.split(":")[0][:_REASON_LIMIT]
        if reason.startswith("unreadable")
        else reason[:_REASON_LIMIT]
    )


def main(argv: list[str]) -> int:
    root, db, out, max_seconds = Path(argv[0]), Path(argv[1]), Path(argv[2]), float(argv[3])
    started = time.monotonic()
    if db.exists():
        db.unlink()
    config = Config(max_seconds=max_seconds)
    with GraphStore(db) as store:
        result = build_graph(str(root), store, config)
    metrics = collect_metrics(db, result)
    metrics["seconds"] = round(time.monotonic() - started, 2)
    metrics["peak_memory_mb"] = peak_memory_mb()
    out.write_text(json.dumps(metrics), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
