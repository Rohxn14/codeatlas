"""The graph tools the agent and the MCP server share.

Each tool is a plain function over a `ToolContext` (a store plus one snapshot) and a
`ToolSpec` with a JSON schema. Both front ends (the agent loop and the MCP server) take
their tool list from `ToolSet`, so they always see the same names, descriptions and
schemas.

Every result is a JSON-serialisable dict that:
- stays under `MAX_RESULT_CHARS` (a long list is cut and `truncated` says so),
- carries a `citation` (`repo@sha:path:line`) for every symbol it names,
- reports a problem as `{"error": ...}` instead of raising, so the model can recover.

`run_tests` is deliberately absent: CodeAtlas never runs code from an indexed repository.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from codeatlas.config import Config
from codeatlas.llm import ToolSpec
from codeatlas.models import Edge, EdgeKind, Node, NodeKind, Snapshot
from codeatlas.store import GraphStore
from codeatlas.store import graph as graph_algos

MAX_RESULT_CHARS = 4000
MAX_SOURCE_LINES = 60
DEFAULT_LIMIT = 10
MAX_DEPTH = 3
_NOT_SYMBOLS = frozenset({NodeKind.MODULE, NodeKind.PACKAGE, NodeKind.EXTERNAL})


@dataclass(slots=True)
class ToolContext:
    """What every tool needs: the store, one snapshot, and where cloned sources live."""

    store: GraphStore
    snapshot_id: str
    config: Config = field(default_factory=Config)
    _graphs: dict[tuple[str, ...], nx.MultiDiGraph] = field(default_factory=dict)

    @property
    def snapshot(self) -> Snapshot:
        snapshot = self.store.get_snapshot(self.snapshot_id)
        if snapshot is None:
            raise KeyError(f"no snapshot {self.snapshot_id!r} in the store")
        return snapshot

    def graph(self, kinds: Iterable[EdgeKind]) -> nx.MultiDiGraph:
        """The NetworkX view for some edge kinds, built once per context."""
        wanted = sorted(str(k) for k in kinds)
        cache_key = tuple(wanted)
        if cache_key not in self._graphs:
            self._graphs[cache_key] = self.store.graph(
                self.snapshot_id, [EdgeKind(k) for k in wanted]
            )
        return self._graphs[cache_key]

    def citation(self, path: str, line: int) -> str:
        return f"{self.snapshot_id}:{path}:{line}"

    def repo_root(self) -> Path | None:
        """Folder of the indexed checkout: the local source, or the clone of a URL."""
        source = self.snapshot.source
        local = Path(source)
        if local.is_dir():
            return local
        from codeatlas.indexer.intake import IntakeError, looks_like_url, parse_github_url

        if looks_like_url(source):
            try:
                clone = self.config.repos_dir / parse_github_url(source).dirname
            except IntakeError:
                return None
            return clone if clone.is_dir() else None
        return None


# Result helpers


def _symbol(ctx: ToolContext, node: Node, **extra: object) -> dict[str, Any]:
    """The short description of a node every tool uses, with its citation."""
    out: dict[str, Any] = {
        "key": node.key,
        "kind": str(node.kind),
        "name": node.name,
        "path": node.path,
        "line": node.span.start_line,
        "citation": ctx.citation(node.path, node.span.start_line),
    }
    if node.signature:
        out["signature"] = node.signature
    out.update(extra)
    return out


def _fit(result: dict[str, Any], list_key: str) -> dict[str, Any]:
    """Drop items from the end of `result[list_key]` until the JSON fits the budget.

    Says so with `truncated` and `omitted`, because a silently short list would let the
    model claim "these are all the callers".
    """
    items: list[Any] = list(result.get(list_key, []))
    result["truncated"] = result.get("truncated", False)
    omitted = 0
    while items and len(json.dumps({**result, list_key: items})) > MAX_RESULT_CHARS:
        items.pop()
        omitted += 1
    result[list_key] = items
    if omitted:
        result["truncated"] = True
        result["omitted"] = result.get("omitted", 0) + omitted
    return result


def _error(message: str, **extra: object) -> dict[str, Any]:
    return {"error": message, **extra}


def _resolve(ctx: ToolContext, key: str) -> Node | dict[str, Any]:
    """Find a node by key; accept a bare qualname (`UserRepo.save`) when it is unique."""
    found = ctx.store.nodes_by_key(key, ctx.snapshot_id)
    if found:
        return found[0]
    if "::" not in key and key:
        matches = [
            n
            for n in ctx.store.nodes_by_name(ctx.snapshot_id, key.rsplit(".", 1)[-1])
            if n.qualname == key and n.kind not in _NOT_SYMBOLS
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return _error(
                f"{key!r} is ambiguous; use one of these keys",
                candidates=[n.key for n in matches[:10]],
            )
    return _error(f"no symbol with key {key!r}; use search_symbols to find the key")


def _clamp_depth(depth: object, default: int = 1) -> int:
    value = depth if isinstance(depth, int) and not isinstance(depth, bool) else default
    return max(1, min(value, MAX_DEPTH))


def _clamp_limit(limit: object, default: int = DEFAULT_LIMIT) -> int:
    value = limit if isinstance(limit, int) and not isinstance(limit, bool) else default
    return max(1, min(value, 50))


# The tools


def search_symbols(
    ctx: ToolContext, name: str, kind: str | None = None, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """Symbols whose name matches `name`: exact first, then prefix, then substring."""
    wanted = name.strip().lower()
    if not wanted:
        return _error("name must not be empty")
    kinds = None
    if kind:
        try:
            kinds = {NodeKind(kind)}
        except ValueError:
            return _error(f"unknown kind {kind!r}", valid_kinds=[str(k) for k in NodeKind])
    ranked: list[tuple[int, Node]] = []
    for node in ctx.store.nodes(ctx.snapshot_id):
        if (kinds and node.kind not in kinds) or (not kinds and node.kind in _NOT_SYMBOLS):
            continue
        lowered = node.name.lower()
        if lowered == wanted or node.qualname.lower() == wanted:
            ranked.append((0, node))
        elif lowered.startswith(wanted):
            ranked.append((1, node))
        elif wanted in lowered:
            ranked.append((2, node))
    ranked.sort(key=lambda item: (item[0], item[1].path, item[1].span.start_line))
    limit = _clamp_limit(limit)
    result = {
        "query": name,
        "total": len(ranked),
        "truncated": len(ranked) > limit,
        "symbols": [_symbol(ctx, n, match="exact" if r == 0 else "partial")
                    for r, n in ranked[:limit]],
    }
    return _fit(result, "symbols")


def semantic_search(ctx: ToolContext, query: str, k: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Hybrid search when `codeatlas.search.HybridSearch` exists, else BM25 text search."""
    k = _clamp_limit(k)
    note = ""
    try:
        from codeatlas.search import HybridSearch  # type: ignore[attr-defined]
    except ImportError:
        note = "codeatlas.search is not available; used text search only"
    else:
        try:
            from codeatlas.llm import EmbeddingClient

            # from_config: the configured model and cache, so embeddings built under
            # CODEATLAS_EMBEDDING_MODEL are found again.
            engine = HybridSearch(ctx.store, ctx.snapshot_id, EmbeddingClient.from_config())
            found = [h for h in engine.search(query, k=k)
                     if h.node.path and h.node.kind is not NodeKind.EXTERNAL]
            hits = [_hit(ctx, h.node, h.score, list(getattr(h, "sources", ())))
                    for h in found[:k]]
            notes = "; ".join(getattr(engine, "notes", []) or [])
            result = {"query": query, "engine": "hybrid", "hits": hits}
            if notes:
                result["note"] = notes
            return _fit(result, "hits")
        except Exception as exc:  # search is best effort: text search still answers
            note = f"hybrid search failed ({type(exc).__name__}: {exc}); used text search only"
    hits = [_hit(ctx, n, s, ["bm25"]) for n, s in ctx.store.search_text(ctx.snapshot_id, query, k)]
    return _fit({"query": query, "engine": "text", "note": note, "hits": hits}, "hits")


def _hit(ctx: ToolContext, node: Node, score: float, sources: list[str]) -> dict[str, Any]:
    out = _symbol(ctx, node, score=round(float(score), 4), found_by=sources)
    out["end_line"] = node.span.end_line
    return out


def get_symbol_source(ctx: ToolContext, key: str) -> dict[str, Any]:
    """Signature, docstring, span and source lines, read from the indexed checkout."""
    node = _resolve(ctx, key)
    if isinstance(node, dict):
        return node
    out = _symbol(ctx, node)
    out.update({"end_line": node.span.end_line, "docstring": node.docstring})
    root = ctx.repo_root()
    if root is None:
        out["source"] = None
        out["note"] = "the indexed checkout is not on disk, so no source lines are available"
        return out
    target = (root / node.path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        out["source"] = None
        out["note"] = f"{node.path} is not readable in the checkout"
        return out
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = node.span.start_line, node.span.end_line
    shown_end = min(end, start + MAX_SOURCE_LINES - 1)
    body = [f"{n}: {lines[n - 1]}" for n in range(start, shown_end + 1) if n <= len(lines)]
    out["source"] = "\n".join(body)
    out["truncated"] = shown_end < end
    # Long source can still exceed the character budget: cut whole lines from the end.
    while len(json.dumps(out)) > MAX_RESULT_CHARS and body:
        body.pop()
        out["source"] = "\n".join(body)
        out["truncated"] = True
    return out


def get_file_symbols(ctx: ToolContext, path: str) -> dict[str, Any]:
    """Everything defined in a file, in source order."""
    path = path.replace("\\", "/").removeprefix("./")
    nodes = [n for n in ctx.store.nodes_in_file(ctx.snapshot_id, path)
             if n.kind is not NodeKind.MODULE]
    module = ctx.store.module_for_path(ctx.snapshot_id, path)
    if module is None:
        return _error(f"{path!r} is not a file of this snapshot")
    result = {
        "path": path,
        "language": module.language,
        "lines": module.span.end_line,
        "citation": ctx.citation(path, module.span.start_line),
        "truncated": False,
        "symbols": [_symbol(ctx, n, end_line=n.span.end_line) for n in nodes],
    }
    return _fit(result, "symbols")


def _related(
    ctx: ToolContext, key: str, depth: int, min_confidence: float, forwards: bool
) -> dict[str, Any]:
    node = _resolve(ctx, key)
    if isinstance(node, dict):
        return node
    depth = _clamp_depth(depth)
    g = ctx.graph([EdgeKind.CALLS])
    walk = graph_algos.callees if forwards else graph_algos.callers
    reached = walk(g, node.id, depth, float(min_confidence or 0.0))
    ranked = sorted(reached.items(), key=lambda item: (-item[1], item[0]))
    items = []
    for node_id, confidence in ranked:
        other = ctx.store.node(node_id)
        if other is not None:
            items.append(_symbol(ctx, other, confidence=round(confidence, 3)))
    result = {
        "symbol": _symbol(ctx, node),
        "direction": "callees" if forwards else "callers",
        "depth": depth,
        "total": len(items),
        "truncated": False,
        "results": items,
    }
    return _fit(result, "results")


def find_callers(
    ctx: ToolContext, key: str, depth: int = 1, min_confidence: float = 0.0
) -> dict[str, Any]:
    """Callers within `depth` hops, with each one's best path confidence."""
    return _related(ctx, key, depth, min_confidence, forwards=False)


def find_callees(
    ctx: ToolContext, key: str, depth: int = 1, min_confidence: float = 0.0
) -> dict[str, Any]:
    """Callees within `depth` hops, with each one's best path confidence."""
    return _related(ctx, key, depth, min_confidence, forwards=True)


def get_imports(ctx: ToolContext, path: str) -> dict[str, Any]:
    """A module's IMPORTS edges, both directions."""
    module = ctx.store.module_for_path(ctx.snapshot_id, path.replace("\\", "/"))
    if module is None:
        return _error(f"{path!r} is not a file of this snapshot")
    imports = [_edge_row(ctx, e, e.dst_id) for e in ctx.store.edges_from(module.id,
                                                                         [EdgeKind.IMPORTS])]
    # Resolvers point imports at the symbol imported (`from repo import Repo` gives
    # user_repo.py -> repo.py::Repo), so a file's importers are the importers of the file
    # and of everything defined in it, each importing module listed once.
    imported_by, seen = [], set()
    for node in ctx.store.nodes_in_file(ctx.snapshot_id, module.path):
        for e in ctx.store.edges_to(node.id, [EdgeKind.IMPORTS]):
            if (e.src_id, e.dst_id) not in seen:
                seen.add((e.src_id, e.dst_id))
                imported_by.append(_edge_row(ctx, e, e.src_id))
    result = {
        "path": module.path,
        "citation": ctx.citation(module.path, module.span.start_line),
        "truncated": False,
        "imports": imports,
        "imported_by": imported_by,
    }
    # Shrink the longer list first so neither direction is lost completely.
    while len(json.dumps(result)) > MAX_RESULT_CHARS and (imports or imported_by):
        longer = imports if len(imports) >= len(imported_by) else imported_by
        longer.pop()
        result["truncated"] = True
    return result


def _edge_row(ctx: ToolContext, edge: Edge, other_id: str) -> dict[str, Any]:
    """An edge seen from one end: the node at the other end, plus how it was found."""
    other = ctx.store.node(other_id)
    row: dict[str, Any] = {
        "kind": str(edge.kind),
        "confidence": round(edge.confidence, 3),
        "resolution": str(edge.resolution),
        "line": edge.line,
    }
    if other is not None:
        row.update(_symbol(ctx, other))
    else:
        row["key"] = other_id.removeprefix(ctx.snapshot_id + "/")
    return row


def compare_symbol_across_snapshots(
    ctx: ToolContext, key: str, snapshot_a: str, snapshot_b: str
) -> dict[str, Any]:
    """Whether a symbol exists in two snapshots, with its signature and span in each."""
    sides: dict[str, Any] = {}
    for label, snapshot_id in (("a", snapshot_a), ("b", snapshot_b)):
        if ctx.store.get_snapshot(snapshot_id) is None:
            return _error(f"no snapshot {snapshot_id!r}")
        found = ctx.store.nodes_by_key(key, snapshot_id)
        if not found:
            sides[label] = {"snapshot": snapshot_id, "exists": False}
            continue
        node = found[0]
        sides[label] = {
            "snapshot": snapshot_id,
            "exists": True,
            "signature": node.signature,
            "span": [node.span.start_line, node.span.end_line],
            "citation": f"{snapshot_id}:{node.path}:{node.span.start_line}",
        }
    changed = (
        sides["a"]["exists"] != sides["b"]["exists"]
        or (sides["a"]["exists"] and sides["a"]["signature"] != sides["b"]["signature"])
    )
    return {"key": key, "a": sides["a"], "b": sides["b"], "signature_changed": changed}


def traverse(
    ctx: ToolContext,
    key: str,
    edge_kinds: list[str],
    direction: str = "out",
    depth: int = 1,
) -> dict[str, Any]:
    """A bounded breadth-first walk over the chosen edge kinds."""
    node = _resolve(ctx, key)
    if isinstance(node, dict):
        return node
    try:
        kinds = [EdgeKind(k) for k in edge_kinds]
    except ValueError as exc:
        return _error(str(exc), valid_kinds=[str(k) for k in EdgeKind])
    if not kinds:
        return _error("edge_kinds must name at least one edge kind")
    if direction not in ("out", "in", "both"):
        return _error("direction must be 'out', 'in' or 'both'")
    depth = _clamp_depth(depth)
    seen = {node.id}
    frontier = [node.id]
    rows: list[dict[str, Any]] = []
    for level in range(1, depth + 1):
        following: list[str] = []
        for current in frontier:
            steps: list[tuple[Edge, str]] = []
            if direction in ("out", "both"):
                steps += [(e, e.dst_id) for e in ctx.store.edges_from(current, kinds)]
            if direction in ("in", "both"):
                steps += [(e, e.src_id) for e in ctx.store.edges_to(current, kinds)]
            for edge, other_id in sorted(steps, key=lambda s: (-s[0].confidence, s[1])):
                if other_id in seen:
                    continue
                seen.add(other_id)
                following.append(other_id)
                row = _edge_row(ctx, edge, other_id)
                row.update({"from": current.removeprefix(ctx.snapshot_id + "/"), "depth": level})
                rows.append(row)
        frontier = following
    result = {"start": _symbol(ctx, node), "depth": depth, "total": len(rows),
              "truncated": False, "results": rows}
    return _fit(result, "results")


_IMPACT_KINDS = (EdgeKind.CALLS, EdgeKind.IMPORTS)


def _impact_scores(ctx: ToolContext, nodes: list[Node]) -> dict[str, float]:
    """Node id -> best path confidence of reaching any changed symbol over CALLS/IMPORTS.

    The changed symbols' own files count as starting points too, because an IMPORTS edge
    usually points at a module, not at one function inside it.
    """
    starts = {n.id for n in nodes}
    for n in nodes:
        module = ctx.store.module_for_path(ctx.snapshot_id, n.path)
        if module is not None:
            starts.add(module.id)
        # Imports point at symbols: `from repo import Repo` reaches Repo.save's class, so
        # the classes that own a changed method are starting points too.
        owner_key = n.owner_key
        while owner_key:
            owners = ctx.store.nodes_by_key(owner_key, ctx.snapshot_id)
            if not owners:
                break
            starts.add(owners[0].id)
            owner_key = owners[0].owner_key
    g = ctx.graph(_IMPACT_KINDS)
    return graph_algos.reverse_reach(g, starts, _IMPACT_KINDS)


def _resolve_all(ctx: ToolContext, keys: list[str]) -> tuple[list[Node], list[dict[str, Any]]]:
    found: list[Node] = []
    problems: list[dict[str, Any]] = []
    for key in keys:
        node = _resolve(ctx, key)
        if isinstance(node, dict):
            problems.append({"key": key, **node})
        else:
            found.append(node)
    return found, problems


def _run_engine(ctx: ToolContext, nodes: list[Node]) -> Any:
    """The impact engine on these symbols, reusing the context's cached graph."""
    from codeatlas.impact import Change, ImpactEngine
    from codeatlas.impact.engine import LOAD_KINDS

    engine = ImpactEngine(ctx.store, ctx.snapshot_id, graph=ctx.graph(LOAD_KINDS))
    return engine.impact([Change(n.path, symbol_keys=(n.key,)) for n in nodes])


def _evidence_rows(evidence: Any) -> list[dict[str, Any]]:
    """Evidence as JSON: signal, score, the path as 'key -kind(confidence)-> key', detail."""
    rows = []
    for e in evidence:
        steps = [e.path[0].key] if e.path else []
        for hop in e.path[1:]:
            steps.append(f"<-{hop.kind}({hop.confidence:g})- {hop.key}")
        rows.append({"signal": e.signal, "score": round(e.score, 3),
                     "path": " ".join(steps), "detail": e.detail})
    return rows


def impact(ctx: ToolContext, keys: list[str]) -> dict[str, Any]:
    """What a change to these symbols could break, ranked, each with its evidence (T12)."""
    nodes, problems = _resolve_all(ctx, list(keys))
    if not nodes:
        return _error("none of the keys matched a symbol", problems=problems)
    result = _run_engine(ctx, nodes)
    affected, co_changed = [], []
    for target in result.targets:
        other = ctx.store.nodes_by_key(target.key, ctx.snapshot_id)
        if not other:
            continue
        row = _symbol(ctx, other[0], confidence=round(target.score, 3),
                      evidence=_evidence_rows(target.evidence))
        history = [e for e in target.evidence if e.signal == "cochange"]
        if len(history) < len(target.evidence):
            affected.append(row)
        if history:
            co_changed.append({**row, "confidence": round(history[0].score, 3),
                               "changed_with": history[0].path[0].key.split("::")[0]})
    out: dict[str, Any] = {
        "changed": [_symbol(ctx, n) for n in nodes],
        "problems": problems,
        "warnings": list(result.warnings),
        "version": "v1: graph, imports, co-change and test links; highest signal wins",
        "truncated": False,
        "affected": affected,
        "co_changed_files": co_changed,
        "total_affected": len(affected),
    }
    # Cut the longer of the two lists first so neither disappears completely.
    while len(json.dumps(out)) > MAX_RESULT_CHARS and (affected or co_changed):
        (affected if len(affected) >= len(co_changed) else co_changed).pop()
        out["truncated"] = True
    return out


def select_tests(ctx: ToolContext, keys: list[str]) -> dict[str, Any]:
    """Tests to run for a change to these symbols, ranked, each with its evidence (T12)."""
    nodes, problems = _resolve_all(ctx, list(keys))
    if not nodes:
        return _error("none of the keys matched a symbol", problems=problems)
    result = _run_engine(ctx, nodes)
    ranked = []
    for pick in result.tests:
        found = ctx.store.nodes_by_key(pick.key, ctx.snapshot_id)
        if not found:
            continue
        best = pick.evidence[0]
        covers = best.path[-2].key if len(best.path) > 1 else best.path[0].key
        ranked.append(_symbol(ctx, found[0], confidence=round(pick.score, 3), covers=covers,
                              evidence=_evidence_rows(pick.evidence)))
    out = {
        "changed": [n.key for n in nodes],
        "problems": problems,
        "warnings": list(result.warnings),
        "version": "v1: graph, imports, co-change and test links; highest signal wins",
        "total": len(ranked),
        "truncated": False,
        "tests": ranked,
    }
    return _fit(out, "tests")


# Specs and registry

_KEY_HELP = (
    "A node key such as 'backend/users.py::UserService.save' (path::qualname); a bare "
    "qualname such as 'UserService.save' also works when it is unique."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


_KEY = {"type": "string", "description": _KEY_HELP}
_DEPTH = {"type": "integer", "minimum": 1, "maximum": MAX_DEPTH, "default": 1,
          "description": f"Hops to follow, at most {MAX_DEPTH}."}
_CONFIDENCE = {"type": "number", "minimum": 0, "maximum": 1, "default": 0,
               "description": "Ignore edges below this confidence."}
_KEYS = {"type": "array", "items": {"type": "string"}, "minItems": 1,
         "description": "Node keys of the changed symbols."}


@dataclass(frozen=True, slots=True)
class Tool:
    """A tool's spec and the function behind it."""

    spec: ToolSpec
    run: Callable[..., dict[str, Any]]


def _tool(
    name: str, description: str, schema: dict[str, Any], run: Callable[..., dict[str, Any]]
) -> Tool:
    return Tool(ToolSpec(name, description, schema), run)


_TOOLS: tuple[Tool, ...] = (
    _tool(
        "search_symbols",
        "Find symbols (functions, classes, tests, routes) whose name matches; exact "
        "matches come first. Use it to get the key of a symbol.",
        _schema({"name": {"type": "string", "description": "Name or part of a name."},
                 "kind": {"type": "string", "enum": [str(k) for k in NodeKind],
                          "description": "Only this kind of node."},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
                ["name"]),
        search_symbols,
    ),
    _tool(
        "semantic_search",
        "Search by meaning and words (hybrid search when available, otherwise BM25 text "
        "search). Use it when you do not know a name.",
        _schema({"query": {"type": "string"},
                 "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
                ["query"]),
        semantic_search,
    ),
    _tool(
        "get_symbol_source",
        "Signature, docstring, span and numbered source lines of one symbol.",
        _schema({"key": _KEY}, ["key"]),
        get_symbol_source,
    ),
    _tool(
        "get_file_symbols",
        "Everything defined in one file, in order.",
        _schema({"path": {"type": "string", "description": "Repo-relative path."}}, ["path"]),
        get_file_symbols,
    ),
    _tool(
        "find_callers",
        "Who calls a symbol, with the best path confidence of each caller.",
        _schema({"key": _KEY, "depth": _DEPTH, "min_confidence": _CONFIDENCE}, ["key"]),
        find_callers,
    ),
    _tool(
        "find_callees",
        "What a symbol calls, with the best path confidence of each callee.",
        _schema({"key": _KEY, "depth": _DEPTH, "min_confidence": _CONFIDENCE}, ["key"]),
        find_callees,
    ),
    _tool(
        "get_imports",
        "A file's imports and the files that import it.",
        _schema({"path": {"type": "string", "description": "Repo-relative path."}}, ["path"]),
        get_imports,
    ),
    _tool(
        "compare_symbol_across_snapshots",
        "Whether a symbol exists in two indexed snapshots, and its signature and span in each.",
        _schema({"key": _KEY, "snapshot_a": {"type": "string"}, "snapshot_b": {"type": "string"}},
                ["key", "snapshot_a", "snapshot_b"]),
        compare_symbol_across_snapshots,
    ),
    _tool(
        "traverse",
        "Walk the graph from a symbol along chosen edge kinds, at most 3 hops.",
        _schema({"key": _KEY,
                 "edge_kinds": {"type": "array", "minItems": 1,
                                "items": {"type": "string", "enum": [str(k) for k in EdgeKind]}},
                 "direction": {"type": "string", "enum": ["out", "in", "both"], "default": "out"},
                 "depth": _DEPTH},
                ["key", "edge_kinds"]),
        traverse,
    ),
    _tool(
        "impact",
        "What a change to these symbols may break: nodes that reach them over calls and "
        "imports ranked by confidence, plus files that change with them in history.",
        _schema({"keys": _KEYS}, ["keys"]),
        impact,
    ),
    _tool(
        "select_tests",
        "Tests worth running after a change to these symbols, ranked. It only lists "
        "tests; CodeAtlas never runs code from an indexed repository.",
        _schema({"keys": _KEYS}, ["keys"]),
        select_tests,
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(t.spec.name for t in _TOOLS)


class ToolSet:
    """The eleven tools bound to one store and snapshot."""

    def __init__(self, store: GraphStore, snapshot_id: str, config: Config | None = None) -> None:
        self.context = ToolContext(store, snapshot_id, config or Config())
        self._by_name = {t.spec.name: t for t in _TOOLS}

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in _TOOLS]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one tool; unknown tools and bad arguments come back as `{"error": ...}`."""
        tool = self._by_name.get(name)
        if tool is None:
            return _error(f"unknown tool {name!r}", tools=list(TOOL_NAMES))
        try:
            return tool.run(self.context, **(arguments or {}))
        except TypeError as exc:
            return _error(f"bad arguments for {name}: {exc}")

    def call_json(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        return json.dumps(self.call(name, arguments), ensure_ascii=False)
