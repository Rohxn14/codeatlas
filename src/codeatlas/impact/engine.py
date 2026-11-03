"""The impact engine: from a change to ranked targets and tests, each with its evidence.

Four signals look at the change independently (graph reach, file imports, co-change,
test links); `_combine` turns each target's per-signal best into one score. Keeping
the signals separate is what makes the evidence honest and lets an evaluation turn the
combination rule on and off.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import networkx as nx

from codeatlas.impact.models import (
    Change,
    Evidence,
    Hop,
    ImpactConfig,
    ImpactResult,
    Target,
    TestPick,
)
from codeatlas.impact.symbols import changed_nodes
from codeatlas.models import EdgeKind, Node, NodeKind
from codeatlas.repo.test_conventions import classify
from codeatlas.store import GraphStore
from codeatlas.store import graph as graph_algos

WALK_KINDS = (EdgeKind.CALLS, EdgeKind.IMPORTS)
LOAD_KINDS = (EdgeKind.CALLS, EdgeKind.IMPORTS, EdgeKind.TESTS, EdgeKind.CO_CHANGES)
_SUPPORT_FILES = frozenset({"__init__.py", "conftest.py"})
_NOT_TARGETS = frozenset({NodeKind.PACKAGE, NodeKind.EXTERNAL})

Signals = dict[str, dict[str, Evidence]]  # node id -> signal name -> its best evidence
# A source of co-change history: path -> [(other path, confidence, support, commits of path)].
CoChangeSource = Callable[[str], list[tuple[str, float, int, int]]]


class ImpactEngine:
    """One snapshot's graph, ready to answer many changes (an evaluation asks hundreds)."""

    def __init__(
        self,
        store: GraphStore,
        snapshot_id: str,
        config: ImpactConfig | None = None,
        graph: nx.MultiDiGraph | None = None,
        cochange: CoChangeSource | None = None,
    ) -> None:
        """`cochange` replaces the stored CO_CHANGES edges, so a benchmark can supply history
        cut off at a held-out commit instead of the history the index was built with."""
        self.store = store
        self._cochange = cochange or self._stored_cochange
        self.snapshot_id = snapshot_id
        self.config = config or ImpactConfig()
        self.g = graph if graph is not None else store.graph(snapshot_id, LOAD_KINDS)
        self._walk = self._decayed(self.g, self.config.decay)
        self._test_paths = {
            d.get("path") for _, d in self.g.nodes(data=True) if d.get("kind") is NodeKind.TEST
        }
        self._prefix = snapshot_id + "/"

    @staticmethod
    def _decayed(g: nx.MultiDiGraph, decay: float) -> nx.MultiDiGraph:
        """CALLS and IMPORTS edges with the per-hop decay folded into the confidence.

        `graph.reverse_reach` multiplies confidences along a path, so a decay of 0.8
        per hop is just 0.8 times each edge: a path then scores
        `product(confidence) * decay ** hops` with no change to the store's search.
        """
        walk = nx.MultiDiGraph()
        for src, dst, data in g.edges(data=True):
            if data["kind"] in WALK_KINDS:
                walk.add_edge(src, dst, kind=data["kind"], raw=data["confidence"],
                              confidence=data["confidence"] * decay)
        return walk

    # Entry point

    def impact(self, changes: Sequence[Change]) -> ImpactResult:
        changed, warnings = changed_nodes(self.store, self.snapshot_id, changes)
        changed_ids = {n.id for n in changed}
        owners = self._owners(changed, changed_ids)
        paths = {n.path for n in changed}
        signals: Signals = {}
        graph_reach = self._graph_signal(changed, changed_ids, owners, signals)
        self._import_signal(paths, changed_ids | set(owners), signals)
        self._cochange_signal(paths, signals)
        self._tests_signal(changed, graph_reach, signals)
        targets, tests = self._rank(signals, changed)
        return ImpactResult(tuple(n.key for n in changed), tuple(targets), tuple(tests),
                            tuple(warnings))

    # Signal 1: graph reach over CALLS and IMPORTS

    def _owners(self, changed: list[Node], changed_ids: set[str]) -> dict[str, Node]:
        """Classes that own a changed method -> the changed node they were found from.

        Imports point at the class (`from repo import Repo`), not at the method inside it,
        so a changed method also reaches whoever imports its class.
        """
        owners: dict[str, Node] = {}
        for node in changed:
            key = node.owner_key
            while key:
                found = self.store.nodes_by_key(key, self.snapshot_id)
                if not found:
                    break
                if found[0].id not in changed_ids:
                    owners.setdefault(found[0].id, node)
                key = found[0].owner_key
        return owners

    def _graph_signal(
        self, changed: list[Node], changed_ids: set[str], owners: dict[str, Node], out: Signals
    ) -> dict[str, float]:
        """Fills `out` with graph evidence; returns node id -> score for the tests signal."""
        cfg = self.config
        scores: dict[str, float] = {}
        reach = graph_algos.reverse_reach(self._walk, changed_ids, WALK_KINDS, cfg.depth)
        for node_id, score in reach.items():
            hops = self._trace(node_id, changed_ids, reach)
            self._add(out, node_id, Evidence("graph", score, tuple(hops)), scores)
        owner_reach = graph_algos.reverse_reach(self._walk, set(owners), WALK_KINDS, cfg.depth)
        origin_of = {self._key(oid): origin for oid, origin in owners.items()}
        for owner_id, origin in owners.items():
            owner = self.store.node(owner_id)
            if owner is not None and owner_id not in reach:
                hops = [Hop(origin.key), Hop(owner.key, "contains", 1.0)]
                self._add(out, owner_id, Evidence("graph", cfg.decay, tuple(hops)), scores)
        for node_id, score in owner_reach.items():
            if node_id in changed_ids or node_id in owners:
                continue
            tail = self._trace(node_id, set(owners), owner_reach)
            hops = [Hop(origin_of[tail[0].key].key), Hop(tail[0].key, "contains", 1.0), *tail[1:]]
            self._add(out, node_id, Evidence("graph", score * cfg.decay, tuple(hops)), scores)
        return scores

    def _trace(self, node_id: str, starts: set[str], reach: dict[str, float]) -> list[Hop]:
        """The best path from a start to `node_id`, rebuilt from the score map.

        The walk keeps only scores, so go back one edge at a time: the previous node is
        the neighbour whose score times the edge confidence is this node's score.
        """
        backwards: list[Hop] = []
        current = node_id
        while current not in starts:
            step = self._previous(current, starts, reach)
            if step is None:
                break
            previous, kind, raw = step
            backwards.append(Hop(self._key(current), kind, raw))
            current = previous
        backwards.append(Hop(self._key(current)))
        return backwards[::-1]

    def _previous(
        self, node_id: str, starts: set[str], reach: dict[str, float]
    ) -> tuple[str, str, float] | None:
        if node_id not in self._walk:
            return None
        options = sorted(
            (dst, str(d["kind"]), d["raw"], d["confidence"])
            for _, dst, d in self._walk.out_edges(node_id, data=True)
        )
        for dst, kind, raw, confidence in options:
            base = 1.0 if dst in starts else reach.get(dst)
            if base is not None and math.isclose(base * confidence, reach[node_id],
                                                 rel_tol=1e-9):
                return dst, kind, raw
        return None

    # Signal 2: importers of a changed file

    def _import_signal(self, paths: set[str], graph_starts: set[str], out: Signals) -> None:
        """Modules that import anything in a changed file, at file granularity.

        Imports of the changed symbols themselves are already the graph signal's first
        hop, so this one adds only what the symbol-level walk skips: imports of the module
        or of its other symbols. They count less because the file changed, not
        necessarily the thing imported.
        """
        cfg = self.config
        for path in sorted(paths):
            for node in self.store.nodes_in_file(self.snapshot_id, path):
                if node.id in graph_starts or node.id not in self.g:
                    continue
                for src, _, data in self.g.in_edges(node.id, data=True):
                    if data["kind"] is not EdgeKind.IMPORTS:
                        continue
                    if self.g.nodes[src].get("path") in paths:
                        continue
                    score = data["confidence"] * cfg.decay * cfg.import_file_factor
                    hops = (Hop(node.key), Hop(self._key(src), "imports", data["confidence"]))
                    detail = f"imports {node.key}, in a changed file"
                    self._add(out, src, Evidence("import", score, hops, detail))

    # Signal 3: co-change

    def _stored_cochange(self, path: str) -> list[tuple[str, float, int, int]]:
        module = self.store.module_for_path(self.snapshot_id, path)
        if module is None:
            return []
        found = []
        for edge in self.store.edges_from(module.id, [EdgeKind.CO_CHANGES]):
            if edge.dst_id in self.g:
                other = str(self.g.nodes[edge.dst_id].get("path", ""))
                found.append((other, edge.confidence, int(edge.attrs.get("support", 0)),
                              int(edge.attrs.get("source_commits", 0))))
        return found

    def _cochange_signal(self, paths: set[str], out: Signals) -> None:
        cfg = self.config
        for path in sorted(paths):
            module = self.store.module_for_path(self.snapshot_id, path)
            if module is None:
                continue
            for other, confidence, support, total in self._cochange(path):
                target = self.store.module_for_path(self.snapshot_id, other)
                if target is None or other in paths:
                    continue
                detail = f"changed together in {support} of {total} commits touching {path}"
                hops = (Hop(module.key), Hop(target.key, "co_changes", confidence))
                self._add(out, target.id,
                          Evidence("cochange", confidence * cfg.cochange_weight, hops, detail))

    # Signal 4: tests linked by TESTS edges

    def _tests_signal(
        self, changed: list[Node], graph_reach: dict[str, float], out: Signals
    ) -> None:
        """Tests that TESTS edges tie to a changed or reached node.

        `reach` is 1.0 for a changed node and for the module that holds it (a naming-
        convention edge points at the module), else the graph score of the node.
        """
        cfg = self.config
        reach: dict[str, tuple[float, tuple[Hop, ...]]] = {}
        for node in changed:
            reach[node.id] = (1.0, (Hop(node.key),))
            module = self.store.module_for_path(self.snapshot_id, node.path)
            if module is not None:
                reach.setdefault(module.id, (1.0, (Hop(module.key),)))
        for node_id, score in graph_reach.items():
            if node_id not in reach:
                best = out[node_id]["graph"]
                reach[node_id] = (score, best.path)
        for node_id, (base, hops) in sorted(reach.items()):
            if node_id not in self.g:
                continue
            for src, _, data in self.g.in_edges(node_id, data=True):
                if data["kind"] is not EdgeKind.TESTS or src in reach:
                    continue
                score = base * data["confidence"] * cfg.tests_decay
                path = (*hops, Hop(self._key(src), "tests", data["confidence"]))
                self._add(out, src, Evidence("tests", score, path, str(data.get("resolution"))))

    # Combine and rank

    def _combine(self, per_signal: dict[str, Evidence]) -> float:
        scores = [e.score for e in per_signal.values()]
        if self.config.combine == "max":
            return max(scores)
        miss = 1.0
        for s in scores:
            miss *= 1.0 - s
        return 1.0 - miss

    def _rank(
        self, signals: Signals, changed: list[Node]
    ) -> tuple[list[Target], list[TestPick]]:
        cfg = self.config
        changed_ids = {n.id for n in changed}
        targets: list[Target] = []
        tests: list[TestPick] = []
        for node_id, per_signal in signals.items():
            data = self.g.nodes[node_id] if node_id in self.g else {}
            kind = data.get("kind")
            if node_id in changed_ids or kind is None or kind in _NOT_TARGETS:
                continue
            score = self._combine(per_signal)
            if score < cfg.min_score:
                continue
            evidence = tuple(sorted(per_signal.values(), key=lambda e: (-e.score, e.signal)))
            key, path = data.get("key", self._key(node_id)), data.get("path", "")
            targets.append(Target(key, str(kind), path, score, evidence))
            pick = self._as_test(node_id, kind, data)
            if pick is not None:
                tests.append(TestPick(key, path, pick, score, evidence))
        tests.extend(self._changed_tests(changed))
        targets.sort(key=lambda t: (-t.score, t.key))
        tests.sort(key=lambda t: (-t.score, t.key))
        return targets, tests

    def _changed_tests(self, changed: list[Node]) -> list[TestPick]:
        """A test the change edits must run: certain, so score 1.0."""
        picks: dict[str, TestPick] = {}
        for node in changed:
            evidence = (Evidence("changed", 1.0, (Hop(node.key),), "the change edits this test"),)
            if node.kind is NodeKind.TEST:
                picks[node.key] = TestPick(node.key, node.path, "test", 1.0, evidence)
            if self._is_test_file(node.path, node.language):
                module = self.store.module_for_path(self.snapshot_id, node.path)
                if module is not None:
                    picks[module.key] = TestPick(module.key, node.path, "module", 1.0, evidence)
        return list(picks.values())

    def _as_test(self, node_id: str, kind: NodeKind, data: dict[str, object]) -> str | None:
        if kind is NodeKind.TEST:
            return "test"
        if kind is NodeKind.MODULE and self._is_test_file(
            str(data.get("path", "")), str(data.get("language", ""))
        ):
            return "module"
        return None

    def _is_test_file(self, path: str, language: str) -> bool:
        if path in self._test_paths:
            return True
        # `__init__.py` and `conftest.py` sit in test folders but hold no tests to run.
        name = path.rsplit("/", 1)[-1]
        return name not in _SUPPORT_FILES and classify(path, language) is not None

    # Helpers

    def _key(self, node_id: str) -> str:
        data = self.g.nodes[node_id] if node_id in self.g else {}
        return str(data.get("key") or node_id.removeprefix(self._prefix))

    @staticmethod
    def _add(
        out: Signals, node_id: str, evidence: Evidence, scores: dict[str, float] | None = None
    ) -> None:
        """Keep the best evidence per signal for a node."""
        slot = out.setdefault(node_id, {})
        old = slot.get(evidence.signal)
        if old is None or evidence.score > old.score:
            slot[evidence.signal] = evidence
            if scores is not None:
                scores[node_id] = evidence.score


def impact(
    store: GraphStore,
    snapshot_id: str,
    changes: Sequence[Change],
    config: ImpactConfig | None = None,
    graph: nx.MultiDiGraph | None = None,
    cochange: CoChangeSource | None = None,
) -> ImpactResult:
    """Rank what `changes` could break and which tests to run, in one snapshot."""
    return ImpactEngine(store, snapshot_id, config, graph, cochange).impact(changes)
