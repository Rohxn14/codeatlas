"""Link HTTP client calls to the server routes they hit, across languages.

Why: no single-language resolver sees that `fetch("/api/users/" + id)` in TypeScript reaches
a Python handler. The linker joins the two worlds on method and normalised path, so a change
to the handler reaches its callers. It is static: a URL built at run time stays unmatched,
and is counted by reason in `unmatched`.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.indexer.linker.urls import (
    IMPORTED_AXIOS,
    PARAM,
    ClientUrl,
    join_client_url,
    normalise_client_url,
    route_segments,
    segment_pattern,
)
from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    ParseResult,
    RawHttpCall,
    RawImport,
    RawRoute,
    Resolution,
    Span,
    make_key,
    make_node_id,
)

EXACT_CONFIDENCE = 0.9
PATTERN_CONFIDENCE = 0.7


@dataclass(slots=True)
class _Route:
    """One distinct (method, path) endpoint and the handlers that serve it."""

    method: str
    path_pattern: str
    segments: tuple[str, ...]
    framework: str
    language: str
    key: str
    line: int
    handlers: list[str] = field(default_factory=list)


class HttpLinker:
    """Creates ROUTE nodes, HANDLES and CALLS_HTTP edges. See the module docstring."""

    name = "http"

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.unmatched: Counter[str] = Counter()
        self.matched_calls = 0

    def link(
        self, results: Sequence[ParseResult], index: SymbolIndex, snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        self.problems, self.unmatched, self.matched_calls = [], Counter(), 0
        routes = _collect_routes(results, self.problems)
        nodes = [_route_node(r, snapshot_id) for r in routes.values()]
        edges = _handles_edges(routes, snapshot_id)
        edges += self._calls_edges(results, routes, snapshot_id)
        self.problems += [
            f"unmatched http calls: {reason}={count}"
            for reason, count in sorted(self.unmatched.items())
        ]
        return nodes, edges

    def _calls_edges(
        self,
        results: Sequence[ParseResult],
        routes: dict[tuple[str, str], _Route],
        snapshot_id: str,
    ) -> list[Edge]:
        edges: dict[tuple[str, str], Edge] = {}
        instances = _axios_instances(results)
        for result in results:
            for raw_call in result.http_calls:
                call = _through_instance(raw_call, result, instances)
                if call is None:
                    self.unmatched["unknown_client"] += 1
                    continue
                found = _match(call, routes)
                if isinstance(found, str):
                    self.unmatched[found] += 1
                    continue
                self.matched_calls += 1
                for edge in _call_edges(call, found, snapshot_id):
                    old = edges.get((edge.src_id, edge.dst_id))
                    if old is None or edge.confidence > old.confidence:
                        edges[(edge.src_id, edge.dst_id)] = edge
        return list(edges.values())


# path -> exported name -> (base URL, url kind), from module nodes' `axios_instances`.
_Instances = dict[str, dict[str, tuple[str, str]]]
_SCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _axios_instances(results: Sequence[ParseResult]) -> _Instances:
    """Axios instances each module exports, as the TypeScript adapter recorded them."""
    found: _Instances = {}
    for result in results:
        for node in result.nodes:
            exported = node.attrs.get("axios_instances") if node.kind is NodeKind.MODULE else None
            if isinstance(exported, dict):
                found[result.path] = {
                    name: (str(v.get("base_url", "")), str(v.get("url_kind", "literal")))
                    for name, v in exported.items()
                    if isinstance(v, dict)
                }
    return found


def _through_instance(
    call: RawHttpCall, result: ParseResult, instances: _Instances
) -> RawHttpCall | None:
    """The call with its instance's base URL joined, or None when the instance is unknown.

    A call whose client is not `axios:<name>` is returned unchanged.
    """
    if not call.client.startswith(IMPORTED_AXIOS):
        return call
    local = call.client[len(IMPORTED_AXIOS):]
    for raw in result.imports:
        exported = _bound_name(raw, local)
        if exported is None:
            continue
        base = _instance_for(result.path, raw.target, exported, instances)
        if base is None:
            return None
        url_text, url_kind = join_client_url(*base, call.url_text, call.url_kind)
        return replace(call, client="axios", url_text=url_text, url_kind=url_kind)
    return None


def _bound_name(raw: RawImport, local: str) -> str | None:
    """The exported name an import binds to `local`, or None if it binds no such name."""
    if raw.is_reexport:
        return None
    for name, alias in raw.names:
        if (alias or name) == local:
            return name
    return None


def _instance_for(
    importer: str, target: str, exported: str, instances: _Instances
) -> tuple[str, str] | None:
    """Find `exported` in the module `target` names, relative to `importer`.

    A relative target is resolved like a bundler would (extensions, `index` files). A
    bare or aliased one (`@/api/http`) cannot be resolved without the build config, so it
    is accepted only when exactly one module exports an instance under that name.
    """
    if target.startswith("."):
        for path in _module_candidates(posixpath.dirname(importer), target):
            if path in instances:
                return instances[path].get(exported)
        return None
    matches = [names[exported] for names in instances.values() if exported in names]
    return matches[0] if len(matches) == 1 else None


@lru_cache(maxsize=1024)
def _module_candidates(directory: str, target: str) -> tuple[str, ...]:
    base = posixpath.normpath(posixpath.join(directory, target))
    stem = posixpath.splitext(base)[0] if base.endswith((".js", ".mjs", ".cjs")) else base
    return (
        base,
        *(stem + ext for ext in _SCRIPT_EXTENSIONS),
        *(f"{base}/index{ext}" for ext in _SCRIPT_EXTENSIONS),
    )


def _collect_routes(
    results: Sequence[ParseResult], problems: list[str]
) -> dict[tuple[str, str], _Route]:
    """One route per (METHOD, path); the first handler in path order owns the key."""
    routes: dict[tuple[str, str], _Route] = {}
    ordered = sorted(results, key=lambda r: r.path)
    for result in ordered:
        for raw in result.routes:
            method = raw.method.upper()
            segments = route_segments(raw.path_pattern)
            pattern = "/" + "/".join(_as_written(raw.path_pattern, segments))
            route = routes.get((method, pattern))
            if route is None:
                route = _new_route(raw, method, pattern, segments, result)
                routes[(method, pattern)] = route
            _add_handler(route, raw, problems)
    return routes


def _as_written(path_pattern: str, segments: tuple[str, ...]) -> list[str]:
    """The pattern's own segments (`{id}` stays `{id}`), without empty ones."""
    return [s for s in path_pattern.split("?")[0].split("/") if s] or list(segments)


def _new_route(
    raw: RawRoute, method: str, pattern: str, segments: tuple[str, ...], result: ParseResult
) -> _Route:
    key = make_key(result.path, f"route:{method} {pattern}")
    return _Route(method, pattern, segments, raw.framework, result.language, key, raw.line)


def _add_handler(route: _Route, raw: RawRoute, problems: list[str]) -> None:
    if raw.handler_key.endswith("::"):  # an inline arrow function: the module is the owner
        problems.append(
            f"route {route.method} {route.path_pattern}: inline handler, no HANDLES edge"
        )
    elif raw.handler_key not in route.handlers:
        route.handlers.append(raw.handler_key)


def _route_node(route: _Route, snapshot_id: str) -> Node:
    path = route.key.partition("::")[0]
    return Node(
        id=make_node_id(snapshot_id, route.key),
        key=route.key,
        snapshot_id=snapshot_id,
        kind=NodeKind.ROUTE,
        language=route.language,
        name=f"{route.method} {route.path_pattern}",
        qualname=route.key.partition("::")[2],
        path=path,
        span=Span(route.line, route.line),
        attrs={
            "http_method": route.method,
            "path_pattern": route.path_pattern,
            "framework": route.framework,
        },
    )


def _handles_edges(routes: dict[tuple[str, str], _Route], snapshot_id: str) -> list[Edge]:
    return [
        Edge(
            make_node_id(snapshot_id, route.key),
            make_node_id(snapshot_id, handler),
            EdgeKind.HANDLES,
            1.0,
            Resolution.STRUCTURAL,
            route.line,
        )
        for route in routes.values()
        for handler in route.handlers
    ]


# A match is the routes hit plus whether the match is exact.
_Hit = tuple[list[_Route], bool]


def _match(call: RawHttpCall, routes: dict[tuple[str, str], _Route]) -> _Hit | str:
    """Routes a call hits, or the reason it hits none."""
    url = normalise_client_url(call.url_text, call.url_kind)
    if url.reason:
        return url.reason
    method = call.method.upper() if call.method else None
    hits = [r for r in routes.values() if _method_ok(method, r) and _segments_ok(url, r)]
    if not hits:
        return "no_route"
    if any(r.method == method for r in hits):  # a route for this very method beats ANY
        hits = [r for r in hits if r.method == method]
    best = max(_literal_count(r) for r in hits)
    hits = [r for r in hits if _literal_count(r) == best]
    exact = (
        len(hits) == 1
        and method is not None
        and hits[0].method == method
        and not url.has_params
        and hits[0].segments == url.segments
    )
    return hits, exact


def _method_ok(method: str | None, route: _Route) -> bool:
    return method is None or route.method in (method, "ANY")


def _segments_ok(url: ClientUrl, route: _Route) -> bool:
    if len(url.segments) != len(route.segments):
        return False
    return all(_segment_ok(c, s) for c, s in zip(url.segments, route.segments, strict=True))


def _segment_ok(client: str, server: str) -> bool:
    """A route `{}` takes any segment; `{}.json` takes a literal `report.json`.

    A client parameter matches only a whole route parameter or the same text: what it
    holds at run time is unknown, so it cannot be said to fit a partly literal segment.
    """
    if server == PARAM or client == server:
        return True
    if PARAM not in server or PARAM in client:
        return False
    return segment_pattern(server).match(client) is not None


def _literal_count(route: _Route) -> int:
    return sum(1 for s in route.segments if s != PARAM)


def _call_edges(call: RawHttpCall, hit: _Hit, snapshot_id: str) -> list[Edge]:
    routes, exact = hit
    resolution = Resolution.ROUTE_EXACT if exact else Resolution.ROUTE_PATTERN
    confidence = EXACT_CONFIDENCE if exact else PATTERN_CONFIDENCE / len(routes)
    return [
        Edge(
            make_node_id(snapshot_id, call.caller_key),
            make_node_id(snapshot_id, route.key),
            EdgeKind.CALLS_HTTP,
            confidence,
            resolution,
            call.line,
            {"url": call.url_text, "client": call.client},
        )
        for route in routes
    ]
