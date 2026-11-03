"""Types the impact engine takes and returns: changes, configuration, ranked results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class Change:
    """One changed file: its repo-relative path and, if known, which lines changed.

    `ranges` are 1-based inclusive `(first, last)` line pairs in the snapshot's version of
    the file. No ranges means "the whole file" (new, deleted or unknown lines). `symbol_keys`
    names changed symbols directly, which is what the agent's tools pass.
    """

    path: str
    ranges: tuple[tuple[int, int], ...] = ()
    symbol_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImpactConfig:
    """Every tunable number in one place, so an evaluation run can state exactly what it used."""

    depth: int = 4  # hops of CALLS/IMPORTS walked from a changed symbol
    decay: float = 0.8  # multiplied in per hop, on top of the edge confidence
    import_file_factor: float = 0.5  # importers of a changed file that import nothing changed
    cochange_weight: float = 0.7  # history is correlation, not dependency
    tests_decay: float = 0.9  # TESTS edges are intended coverage: nearly full weight
    combine: Literal["max", "noisy_or"] = "max"
    min_score: float = 0.05  # targets below this are dropped
    test_threshold: float = 0.3  # the "natural cut-off": best F1 on both mutation benchmarks


@dataclass(frozen=True, slots=True)
class Hop:
    """One node on an evidence path, listed from the changed symbol outwards.

    `kind` and `confidence` describe the edge between this node and the previous one,
    which in the code points the other way: a caller has a `calls` edge into the changed
    function, and appears after it in the path.
    """

    key: str
    kind: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """Why one signal flagged a target: the path, the import or the history behind it."""

    signal: str  # "graph", "import", "cochange" or "tests"
    score: float
    path: tuple[Hop, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Target:
    """A node the change could break, with the combined score and all evidence."""

    key: str
    kind: str
    path: str
    score: float
    evidence: tuple[Evidence, ...] = field(default=())  # best first


@dataclass(frozen=True, slots=True)
class TestPick:
    """A test function or test file to run."""

    __test__ = False  # not a pytest class, despite the name

    key: str
    path: str
    kind: str  # "test" or "module"
    score: float
    evidence: tuple[Evidence, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ImpactResult:
    """Ranked targets and tests, and what could not be mapped."""

    changed: tuple[str, ...]  # keys of the symbols the changes mapped to
    targets: tuple[Target, ...]
    tests: tuple[TestPick, ...]
    warnings: tuple[str, ...] = ()

    def test_files(self, threshold: float = 0.0) -> list[TestPick]:
        """The best pick per test file, ranked: what a test runner can actually be told."""
        best: dict[str, TestPick] = {}
        for pick in self.tests:  # already ranked, so the first pick of a file is its best
            if pick.score >= threshold and pick.path not in best:
                best[pick.path] = pick
        return list(best.values())
