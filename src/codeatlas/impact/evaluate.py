"""Score test selection against mutation truth, and against three baselines.

Mutation truth (`eval/mutants/truth/*.json`) says, for each mutated function, which test
files really fail. The change handed to the engine is that function's span; what it
selects is compared with those files. This module needs a store and a truth dict, nothing
else, so it is testable on hand-made data; `scripts/evaluate_impact.py` does the cloning
and indexing.

Definitions (what each hides is in the explainer):
- precision = selected files that fail / selected files (0 when nothing is selected);
- recall = failing files that were selected / failing files;
- skipped share = test files not selected / all test files;
- all are macro averages over mutants that at least one test catches. Mutants no test
  catches have no truth to recall (Q4 in docs/decisions.md): they are counted apart, and
  the engine's selection for them is not scored.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from codeatlas.impact.engine import ImpactEngine
from codeatlas.impact.models import Change
from codeatlas.models import EdgeKind, NodeKind

KS = (5, 10)
Ranked = list[tuple[str, float]]  # (test file, score), best first
Selector = Callable[[ImpactEngine, Change], Ranked]


@dataclass(frozen=True, slots=True)
class Mutant:
    """One row of a truth file: the mutated function and the test files that fail."""

    function: str
    failing_files: frozenset[str]
    status: str = "mutated"


def mutants_from_truth(truth: Mapping[str, object]) -> list[Mutant]:
    """Mutants from a truth file; a failing test id `path::name` counts as its file."""
    rows = truth.get("mutants", [])
    return [
        Mutant(
            str(row["function"]),
            frozenset(str(t).split("::")[0] for t in row.get("failing_tests", [])),
            str(row.get("status", "mutated")),
        )
        for row in rows  # type: ignore[attr-defined]
    ]


def all_test_files(engine: ImpactEngine) -> set[str]:
    """Every test file in the snapshot: the pool selection skips from."""
    return {
        str(d.get("path")) for _, d in engine.g.nodes(data=True)
        if d.get("kind") is NodeKind.MODULE
        and engine._is_test_file(str(d.get("path")), str(d.get("language")))
    }


# The engine and the three baselines, all returning ranked test files.


def engine_selector(threshold: float | None = None) -> Selector:
    """Files the engine ranks at or above `threshold` (default: the config's cut-off)."""

    def select(engine: ImpactEngine, change: Change) -> Ranked:
        cut = engine.config.test_threshold if threshold is None else threshold
        return [(p.path, p.score) for p in engine.impact([change]).test_files(cut)]

    return select


def engine_ranking(engine: ImpactEngine, change: Change) -> Ranked:
    """Every file the engine scores, for precision and recall at k."""
    return [(p.path, p.score) for p in engine.impact([change]).test_files(0.0)]


def run_all_selector(engine: ImpactEngine, change: Change) -> Ranked:
    return [(p, 1.0) for p in sorted(all_test_files(engine))]


def importing_tests_selector(engine: ImpactEngine, change: Change) -> Ranked:
    """Baseline: test files with an IMPORTS edge into the changed file."""
    tests = all_test_files(engine)
    found: set[str] = set()
    for node in engine.store.nodes_in_file(engine.snapshot_id, change.path):
        if node.id not in engine.g:
            continue
        for src, _, data in engine.g.in_edges(node.id, data=True):
            path = str(engine.g.nodes[src].get("path"))
            if data["kind"] is EdgeKind.IMPORTS and path in tests:
                found.add(path)
    return [(p, 1.0) for p in sorted(found)]


def cochange_selector(engine: ImpactEngine, change: Change) -> Ranked:
    """Baseline: test files that history says change with the changed file."""
    tests = all_test_files(engine)
    neighbours = sorted(engine._cochange(change.path), key=lambda t: (-t[1], t[0]))
    return [(p, c) for p, c, _, _ in neighbours if p in tests]


# Metrics


@dataclass(slots=True)
class Prf:
    precision: float
    recall: float
    f1: float


def prf(selected: Sequence[str], truth: frozenset[str]) -> Prf:
    hits = len(set(selected) & truth)
    precision = hits / len(selected) if selected else 0.0
    recall = hits / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    return Prf(precision, recall, f1)


@dataclass(slots=True)
class Tally:
    """Running macro averages for one selector."""

    mutants: int = 0
    natural: list[Prf] = field(default_factory=list)
    at_k: dict[int, list[Prf]] = field(default_factory=lambda: {k: [] for k in KS})
    skipped: list[float] = field(default_factory=list)
    empty: int = 0

    def add(self, natural: Ranked, ranking: Ranked, truth: frozenset[str], universe: int) -> None:
        self.mutants += 1
        files = [p for p, _ in natural]
        self.natural.append(prf(files, truth))
        for k in KS:
            self.at_k[k].append(prf([p for p, _ in ranking[:k]], truth))
        self.skipped.append(1 - len(files) / universe if universe else 0.0)
        self.empty += not files

    def summary(self) -> dict[str, float | int | None]:
        def mean(rows: list[Prf], attr: str) -> float | None:
            return round(sum(getattr(r, attr) for r in rows) / len(rows), 4) if rows else None

        out: dict[str, float | int | None] = {"mutants": self.mutants}
        for attr in ("precision", "recall", "f1"):
            out[attr] = mean(self.natural, attr)
        for k in KS:
            out[f"precision@{k}"] = mean(self.at_k[k], "precision")
            out[f"recall@{k}"] = mean(self.at_k[k], "recall")
        out["skipped_share"] = (round(sum(self.skipped) / len(self.skipped), 4)
                                if self.skipped else None)
        out["empty_selections"] = self.empty
        return out


def evaluate_mutants(
    engine: ImpactEngine, mutants: Sequence[Mutant], selectors: Mapping[str, Selector]
) -> dict[str, object]:
    """Scores for every selector, plus the mutants that could not be scored and why."""
    universe = all_test_files(engine)
    tallies = {name: Tally() for name in selectors}
    uncaught: list[str] = []
    skipped: list[str] = []
    unmapped: list[str] = []
    for mutant in mutants:
        mutant = Mutant(mutant.function, _resolve_files(mutant.failing_files, universe),
                        mutant.status)
        if mutant.status != "mutated":
            skipped.append(mutant.function)
            continue
        if not mutant.failing_files:
            uncaught.append(mutant.function)  # Q4: no test noticed, so no truth to score
            continue
        change = change_for(engine, mutant.function)
        if change is None:
            unmapped.append(mutant.function)
            continue
        ranking = engine_ranking(engine, change)
        for name, select in selectors.items():
            natural = select(engine, change)
            tallies[name].add(natural, ranking if name == "engine" else natural,
                              mutant.failing_files, len(universe))
    return {
        "test_files": len(universe),
        "scores": {name: t.summary() for name, t in tallies.items()},
        "caught_by_no_test": uncaught,
        "skipped_mutants": skipped,
        "not_in_index": unmapped,
    }


def _resolve_files(files: frozenset[str], universe: set[str]) -> frozenset[str]:
    """Truth names a test file by path, but vitest reports it relative to its own folder.

    A name not in the index is matched to the one test file whose path ends with it;
    an ambiguous or unknown name stays as written (and so can never be recalled).
    """
    resolved = set()
    for name in files:
        if name in universe:
            resolved.add(name)
            continue
        ends = [p for p in universe if p.endswith("/" + name)]
        resolved.add(ends[0] if len(ends) == 1 else name)
    return frozenset(resolved)


def change_for(engine: ImpactEngine, function_key: str) -> Change | None:
    """The mutated function's span as a change, or None when the index lacks the function."""
    found = engine.store.nodes_by_key(function_key, engine.snapshot_id)
    if not found:
        return None
    node = found[0]
    return Change(node.path, ((node.span.start_line, node.span.end_line),))


def default_selectors() -> dict[str, Selector]:
    return {
        "engine": engine_selector(),
        "run-all": run_all_selector,
        "importing-tests": importing_tests_selector,
        "cochange-only": cochange_selector,
    }


def table(name: str, result: Mapping[str, object]) -> str:
    """One benchmark as a markdown table."""
    scores: Mapping[str, Mapping[str, object]] = result["scores"]  # type: ignore[assignment]
    head = ("| selector | mutants | P | R | F1 | P@5 | R@5 | P@10 | R@10 | skipped | empty |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    rows = []
    for selector, s in scores.items():
        cells = [s["mutants"], *(s[k] for k in ("precision", "recall", "f1", "precision@5",
                 "recall@5", "precision@10", "recall@10", "skipped_share", "empty_selections"))]
        rows.append(f"| {selector} | " + " | ".join("-" if c is None else str(c)
                                                     for c in cells) + " |")
    notes = (f"{result['test_files']} test files. Caught by no test: "
             f"{len(result['caught_by_no_test'])}; skipped: {len(result['skipped_mutants'])}; "
             f"not in the index: {len(result['not_in_index'])}.")  # type: ignore[arg-type]
    return f"### {name}\n\n{head}\n" + "\n".join(rows) + f"\n\n{notes}\n"
