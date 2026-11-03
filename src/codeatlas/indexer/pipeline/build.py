"""`build_graph`: parse a source, then resolve, link and store everything in one snapshot.

The steps, in order (each is one small function below):

1. parse (intake, discovery, adapters);
2. record parse problems on each file's module node (decision D-13), keeping the first
   of two nodes with the same id;
3. run the repository layer and note each module's package;
4. add CONTAINS edges inside files (decision D-14);
5. write the snapshot, files, nodes and raw calls;
6. run the registered resolvers, then the linkers, against the stored symbols;
7. create EXTERNAL nodes for edges that point outside the repository (decision D-19);
8. drop and count invalid edges, deduplicate, write the rest, mark resolved raw calls.

Nothing is dropped silently: every skipped plugin, failed resolver and dropped edge is
named in the `BuildResult`.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from codeatlas.config import Config
from codeatlas.indexer.pipeline import plugins
from codeatlas.indexer.pipeline.contains import contains_edges
from codeatlas.indexer.pipeline.parse import Parsed, parse_source
from codeatlas.indexer.registry import Registry
from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    ParseResult,
    Span,
    make_node_id,
)
from codeatlas.repo import default_analyzers
from codeatlas.store import GraphStore

EXTERNAL_PREFIX = "::external:"


class AlreadyIndexed(ValueError):
    """The snapshot of this commit is stored; `index_repository` returns its saved report."""

    def __init__(self, snapshot_id: str) -> None:
        super().__init__(f"{snapshot_id} is already indexed; pass replace_existing=True")
        self.snapshot_id = snapshot_id


@dataclass(slots=True)
class BuildResult:
    """What one build did, for the CLI, the report and the tests."""

    parsed: Parsed
    nodes_written: int = 0
    edges_written: int = 0
    raw_calls: int = 0
    resolved_calls: int = 0
    edges_dropped: Counter[str] = field(default_factory=Counter)
    problems: list[str] = field(default_factory=list)
    languages_without_resolver: list[str] = field(default_factory=list)
    analyzers: list[object] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)  # one entry per step, plus total

    @property
    def snapshot_id(self) -> str:
        return self.parsed.snapshot.id


def build_graph(
    source: str,
    store: GraphStore,
    config: Config | None = None,
    registry: Registry | None = None,
    replace_existing: bool = False,
) -> BuildResult:
    """Index `source` (a folder or a GitHub URL) into `store`; returns what happened.

    An existing snapshot of the same commit raises `ValueError` unless
    `replace_existing`, which deletes it first.
    """
    config = config or Config()
    started = time.perf_counter()
    parsed = parse_source(source, config, registry)
    result = BuildResult(parsed)
    result.seconds.update(parsed.seconds)
    snapshot_id = parsed.snapshot.id
    if store.get_snapshot(snapshot_id) is not None:
        if not replace_existing:
            raise AlreadyIndexed(snapshot_id)
        store.delete_snapshot(snapshot_id)

    results = [_record_problems(r) for r in parsed.results.values()]
    mark = time.perf_counter()
    repo_nodes, repo_edges = _repository_layer(parsed, config, result)
    results = _with_package_keys(results, repo_edges)
    file_nodes = [n for r in results for n in r.nodes]
    result.seconds["repo_layer"] = time.perf_counter() - mark
    mark = time.perf_counter()

    store.create_snapshot(parsed.snapshot)
    store.write_files(snapshot_id, parsed.discovery.files)
    result.nodes_written = store.write_nodes([*file_nodes, *repo_nodes])
    result.raw_calls = store.write_raw_calls(snapshot_id, [c for r in results for c in r.calls])

    result.seconds["write"] = time.perf_counter() - mark
    mark = time.perf_counter()
    index = store.symbol_index(snapshot_id)
    resolved = _run_resolvers(results, index, result, parsed.intake.root)
    result.seconds["resolve"] = time.perf_counter() - mark
    mark = time.perf_counter()
    link_nodes, linked = _run_linkers(results, index, snapshot_id, result)
    result.seconds["link"] = time.perf_counter() - mark
    mark = time.perf_counter()
    if link_nodes:
        result.nodes_written += store.write_nodes(link_nodes)

    edges = [*contains_edges(results), *repo_edges, *resolved, *linked]
    known = {n.id for n in (*file_nodes, *repo_nodes, *link_nodes)}
    externals = _external_nodes(edges, known, file_nodes, snapshot_id)
    if externals:
        result.nodes_written += store.write_nodes(externals)
        known.update(n.id for n in externals)
    result.edges_written = store.write_edges(snapshot_id, _valid(edges, known, result))
    result.resolved_calls = store.mark_resolved_calls(snapshot_id)
    result.seconds["write"] += time.perf_counter() - mark
    # Total covers every step, parsing included (the clone is in `intake`).
    result.seconds["total"] = time.perf_counter() - started
    return result


def _record_problems(result: ParseResult) -> ParseResult:
    """Parse errors onto the module node (D-13); the first of two equal ids wins."""
    errors = list(result.errors)
    seen: set[str] = set()
    nodes: list[Node] = []
    for node in result.nodes:
        if node.id in seen:
            errors.append(f"duplicate node id {node.key!r}: kept the first, dropped this one")
            continue
        seen.add(node.id)
        nodes.append(node)
    if errors and nodes:
        module = nodes[0]
        nodes[0] = replace(module, attrs={**module.attrs, "errors": errors})
    return replace(result, nodes=tuple(nodes))


def _repository_layer(
    parsed: Parsed, config: Config, result: BuildResult
) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = []
    edges: list[Edge] = []
    for analyzer in default_analyzers(config):
        try:
            found_nodes, found_edges = analyzer.analyze(
                parsed.intake.root, parsed.discovery.files, parsed.snapshot.id
            )
        except Exception as exc:  # one analyzer's bug must not lose the index
            result.problems.append(f"repository analyzer {analyzer.name} failed: {exc}")
            continue
        nodes += found_nodes
        edges += found_edges
        result.analyzers.append(analyzer)
    return nodes, edges


def _with_package_keys(results: list[ParseResult], repo_edges: list[Edge]) -> list[ParseResult]:
    """Set `attrs["package_key"]` on each module node from Package -> Module CONTAINS."""
    package_of = {
        e.dst_id: e.src_id.split("/", 1)[1]
        for e in repo_edges
        if e.kind is EdgeKind.CONTAINS and "::package:" in e.src_id
    }
    updated = []
    for result in results:
        module = result.nodes[0] if result.nodes else None
        if module is None or module.id not in package_of:
            updated.append(result)
            continue
        attrs = {**module.attrs, "package_key": package_of[module.id]}
        updated.append(replace(result, nodes=(replace(module, attrs=attrs), *result.nodes[1:])))
    return updated


def _run_resolvers(
    results: list[ParseResult], index: object, result: BuildResult, repo_root: Path
) -> list[Edge]:
    """Run each resolver on its languages; collect its edges and its own problems.

    A resolver that needs repository files (tsconfig.json, package.json) offers
    `set_repo_root(path)`: the pipeline passes the checkout, which for a GitHub URL is
    the clone, so it never has to guess the root from the store. A resolver's
    `problems` list (unreadable configs, say) is copied into the build's problems, so
    nothing it skipped is silent.
    """
    loaded, failures = plugins.load_plugins(plugins.RESOLVERS)
    result.problems += [f"resolver {f.name} not loaded: {f.error}" for f in failures]
    covered: set[str] = set()
    edges: list[Edge] = []
    for name, resolver in loaded:
        languages = frozenset(getattr(resolver, "languages", frozenset()))
        mine = [r for r in results if r.language in languages]
        covered |= languages
        try:
            if hasattr(resolver, "set_repo_root"):
                resolver.set_repo_root(repo_root)
            edges += resolver.resolve(mine, index)  # type: ignore[attr-defined]
        except Exception as exc:
            result.problems.append(f"resolver {name} failed: {type(exc).__name__}: {exc}")
        result.problems += [f"resolver {name}: {p}" for p in getattr(resolver, "problems", [])]
    parsed_languages = {r.language for r in results if r.nodes and len(r.nodes) > 1}
    result.languages_without_resolver = sorted(parsed_languages - covered)
    return edges


def _run_linkers(
    results: list[ParseResult], index: object, snapshot_id: str, result: BuildResult
) -> tuple[list[Node], list[Edge]]:
    loaded, failures = plugins.load_plugins(plugins.LINKERS)
    result.problems += [f"linker {f.name} not loaded: {f.error}" for f in failures]
    nodes: list[Node] = []
    edges: list[Edge] = []
    for name, linker in loaded:
        try:
            found_nodes, found_edges = linker.link(results, index, snapshot_id)  # type: ignore[attr-defined]
        except Exception as exc:
            result.problems.append(f"linker {name} failed: {type(exc).__name__}: {exc}")
            continue
        nodes += found_nodes
        edges += found_edges
        result.problems += [f"linker {name}: {p}" for p in getattr(linker, "problems", [])]
    return nodes, edges


def _external_nodes(
    edges: Sequence[Edge], known: set[str], file_nodes: Sequence[Node], snapshot_id: str
) -> list[Node]:
    """One EXTERNAL node per `::external:<name>` target (D-19).

    Resolvers return edges only, so they point at a reserved key and the pipeline makes
    the node; its language is the language of the first edge's source.
    """
    prefix = snapshot_id + "/"
    language_of = {n.id: n.language for n in file_nodes}
    created: dict[str, Node] = {}
    for edge in edges:
        key = edge.dst_id.removeprefix(prefix)
        if edge.dst_id in known or edge.dst_id in created or not key.startswith(EXTERNAL_PREFIX):
            continue
        name = key.removeprefix(EXTERNAL_PREFIX)
        created[edge.dst_id] = Node(
            id=make_node_id(snapshot_id, key),
            key=key,
            snapshot_id=snapshot_id,
            kind=NodeKind.EXTERNAL,
            language=language_of.get(edge.src_id, "text"),
            name=name.rsplit(".", 1)[-1] or name,
            qualname=name,
            path="",
            span=Span(1, 1),
        )
    return list(created.values())


def _valid(edges: Sequence[Edge], known: set[str], result: BuildResult) -> list[Edge]:
    """Edges whose ends exist and whose confidence is in (0, 1], one per (src, dst, kind).

    A repeated edge keeps its highest confidence and its first line.
    """
    best: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        if edge.src_id not in known:
            result.edges_dropped["unknown source"] += 1
            continue
        if edge.dst_id not in known:
            result.edges_dropped["unknown target"] += 1
            continue
        if not 0.0 < edge.confidence <= 1.0:
            result.edges_dropped["confidence outside (0, 1]"] += 1
            continue
        key = (edge.src_id, edge.dst_id, str(edge.kind))
        current = best.get(key)
        if current is None:
            best[key] = edge
            continue
        result.edges_dropped["duplicate (merged into one)"] += 1
        line = _first_line(current.line, edge.line)
        if edge.confidence > current.confidence:
            best[key] = replace(edge, line=line)
        else:
            best[key] = replace(current, line=line)
    return list(best.values())


def _first_line(a: int | None, b: int | None) -> int | None:
    lines = [n for n in (a, b) if n is not None]
    return min(lines) if lines else None


def default_db_path(config: Config) -> Path:
    """Where `codeatlas index` keeps its database unless told otherwise."""
    return Path(config.data_dir) / "codeatlas.db"
