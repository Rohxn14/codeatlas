"""The TypeScript/JavaScript resolver: raw imports, calls and bases become edges."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.indexer.languages.typescript.resolver.bindings import (
    FileContext,
    build_context,
)
from codeatlas.indexer.languages.typescript.resolver.calls import CallResolver, Hit
from codeatlas.indexer.languages.typescript.resolver.modules import ModuleResolver
from codeatlas.indexer.languages.typescript.resolver.names import NameResolver, external_key
from codeatlas.indexer.languages.typescript.resolver.tables import Exports, Tables
from codeatlas.indexer.languages.typescript.resolver.tsconfig import ReadFile, load_rules
from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    ParseResult,
    Resolution,
    make_node_id,
)

log = logging.getLogger(__name__)
_TEST_PATH = re.compile(r"(\.|_)(test|spec)\.[cm]?[jt]sx?$|(^|/)(__tests__|tests?)/")


class TypeScriptResolver:
    """Resolves IMPORTS, CALLS, INHERITS and TESTS for TypeScript, TSX and JavaScript.

    `read_file(repo_path)` returns a file's bytes or None. The pipeline constructs
    resolvers with no arguments and passes no repository root, so by default the root is
    found from the snapshot's source when that is a local folder; for a cloned URL the
    tsconfig and package.json files cannot be read and only relative imports, barrels and
    calls are resolved. `problems` lists what could not be read.
    """

    languages = frozenset({"typescript", "tsx", "javascript"})

    def __init__(self, read_file: ReadFile | None = None) -> None:
        self._read = read_file
        self.problems: list[str] = []

    def resolve(self, results: Sequence[ParseResult], index: SymbolIndex) -> list[Edge]:
        self.problems = []
        if not results:
            return []
        read = self._read or self._reader_from_index(index)
        paths = {f.path for f in index.files()} | {r.path for r in results}
        rules, problems = load_rules(sorted(paths), read)
        self.problems += problems
        tables = Tables(list(results))
        modules = ModuleResolver(paths, rules, index, read)
        exports = Exports(tables, modules)
        run = _Run(tables, modules, exports, _snapshot_id(results))
        return run.edges(self.problems)

    def _reader_from_index(self, index: SymbolIndex) -> ReadFile:
        root = _root_of(index)
        if root is None:
            self.problems.append("repository root unknown: tsconfig and package.json skipped")
            return lambda _path: None

        def read(path: str) -> bytes | None:
            try:
                return root.joinpath(*path.split("/")).read_bytes()
            except OSError:
                return None

        return read


class _Run:
    """One resolution pass: builds every edge list and de-duplicates the result."""

    def __init__(
        self, tables: Tables, modules: ModuleResolver, exports: Exports, snapshot_id: str
    ) -> None:
        self._t = tables
        self._modules = modules
        self._exports = exports
        self._snapshot = snapshot_id
        self._edges: dict[tuple[str, str, EdgeKind], Edge] = {}

    def edges(self, problems: list[str]) -> list[Edge]:
        contexts = self._imports()
        names = NameResolver(self._t, self._exports, contexts)
        calls = CallResolver(self._t, self._exports, names, contexts)
        self._calls(calls)
        self._inherits(calls, names)
        return list(self._edges.values())

    # --- IMPORTS ----------------------------------------------------------------------

    def _imports(self) -> dict[str, FileContext]:
        contexts: dict[str, FileContext] = {}
        for path, info in self._t.files.items():
            def add(src: str, dst: str, line: int) -> None:
                self._add(src, dst, EdgeKind.IMPORTS, Resolution.STRUCTURAL, 1.0, line)

            contexts[path] = build_context(info, self._modules, self._exports, add)
        return contexts

    # --- CALLS and TESTS --------------------------------------------------------------

    def _calls(self, calls: CallResolver) -> None:
        for info in self._t.files.values():
            for raw in info.calls:
                caller = self._t.nodes.get(raw.caller_key)
                if caller is None or caller.kind is NodeKind.MODULE:
                    continue  # contract: CALLS start at a function or a test
                for hit in calls.resolve(raw, caller):
                    self._add_call(caller, hit, raw.line)

    def _add_call(self, caller: Node, hit: Hit, line: int) -> None:
        self._add(caller.key, hit.dst_key, EdgeKind.CALLS, hit.resolution, hit.confidence, line,
                  hit.attrs)
        target = self._t.nodes.get(hit.dst_key)
        if caller.kind is NodeKind.TEST and target is not None and _is_source_function(target):
            self._add(caller.key, hit.dst_key, EdgeKind.TESTS, hit.resolution, hit.confidence,
                      line, hit.attrs)

    # --- INHERITS ---------------------------------------------------------------------

    def _inherits(self, calls: CallResolver, names: NameResolver) -> None:
        for node in list(self._t.nodes.values()):
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            for base in calls.bases(node):
                dst = base.node.key if base.node is not None else external_key(base.external or "")
                if base.node is not None and base.node.kind not in (
                    NodeKind.CLASS, NodeKind.INTERFACE
                ):
                    continue
                self._add(node.key, dst, EdgeKind.INHERITS, Resolution.STRUCTURAL, 1.0,
                          node.span.start_line)

    # --- shared -----------------------------------------------------------------------

    def _add(
        self,
        src_key: str,
        dst_key: str,
        kind: EdgeKind,
        resolution: Resolution,
        confidence: float,
        line: int | None,
        attrs: dict[str, object] | None = None,
    ) -> None:
        """One edge per (source, target, kind): the best confidence, the first line."""
        key = (src_key, dst_key, kind)
        old = self._edges.get(key)
        lines = [n for n in (line, old.line if old else None) if n]
        first = min(lines) if lines else None
        if old is not None and old.confidence >= confidence:
            if first != old.line:
                self._edges[key] = Edge(**{**_fields(old), "line": first})
            return
        self._edges[key] = Edge(
            make_node_id(self._snapshot, src_key),
            make_node_id(self._snapshot, dst_key),
            kind,
            confidence,
            resolution,
            first,
            attrs or {},
        )


def _fields(edge: Edge) -> dict[str, object]:
    return {
        "src_id": edge.src_id, "dst_id": edge.dst_id, "kind": edge.kind,
        "confidence": edge.confidence, "resolution": edge.resolution, "line": edge.line,
        "attrs": edge.attrs,
    }


def _is_source_function(node: Node) -> bool:
    return node.kind is NodeKind.FUNCTION and not _TEST_PATH.search(node.path)


def _snapshot_id(results: Sequence[ParseResult]) -> str:
    for result in results:
        if result.nodes:
            return result.nodes[0].snapshot_id
    return ""


def _root_of(index: SymbolIndex) -> Path | None:
    """The folder the snapshot was indexed from, if the store is the real one and the
    source is a local directory. Uses the store's own attributes; None when unavailable."""
    store = getattr(index, "_store", None)
    snapshot_id = getattr(index, "snapshot_id", None)
    if store is None or snapshot_id is None:
        return None
    try:
        snapshot = store.get_snapshot(snapshot_id)
    except Exception:  # an unfamiliar store: tsconfig simply stays unread
        return None
    source = Path(snapshot.source) if snapshot is not None else None
    return source if source is not None and source.is_dir() else None
