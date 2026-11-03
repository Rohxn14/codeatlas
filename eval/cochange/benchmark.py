"""Score predictors on held-out commits.

For each held-out commit C and each file f it changed, a predictor ranks other files
from history before C only; the truth is the other files C changed.

Definitions (what each hides is in the explainer):
- precision@k = hits among the top k / number predicted, over queries that got a prediction;
- recall@k = hits among the top k / size of the truth, over all queries (no prediction = 0);
- no-prediction share = queries where the predictor returned nothing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from codeatlas.indexer.discover import language_for
from eval.cochange.gitread import recent_commits
from eval.cochange.predictors import Predictor

KS = (5, 10)


@dataclass(slots=True)
class Query:
    commit: str
    file: str
    language: str
    truth: frozenset[str]


@dataclass(slots=True)
class Tally:
    """Running sums for one group of queries."""

    queries: int = 0
    with_prediction: int = 0
    precision_sum: dict[int, float] = field(default_factory=lambda: dict.fromkeys(KS, 0.0))
    recall_sum: dict[int, float] = field(default_factory=lambda: dict.fromkeys(KS, 0.0))

    def add(self, ranked: list[str], truth: frozenset[str]) -> None:
        self.queries += 1
        if ranked:
            self.with_prediction += 1
        for k in KS:
            top = ranked[:k]
            hits = sum(1 for p in top if p in truth)
            if top:
                self.precision_sum[k] += hits / len(top)
            self.recall_sum[k] += hits / len(truth)

    def summary(self) -> dict[str, float | int | None]:
        out: dict[str, float | int | None] = {"queries": self.queries}
        for k in KS:
            out[f"precision@{k}"] = _ratio(self.precision_sum[k], self.with_prediction)
            out[f"recall@{k}"] = _ratio(self.recall_sum[k], self.queries)
        out["no_prediction_share"] = _ratio(self.queries - self.with_prediction, self.queries)
        return out


def _ratio(a: float, b: int) -> float | None:
    return round(a / b, 4) if b else None


def build_queries(repo_root: Path, commits: int = 100) -> list[Query]:
    """One query per (held-out commit, changed file)."""
    queries = []
    for sha, files in recent_commits(repo_root, commits):
        for path in files:
            truth = frozenset(files) - {path}
            queries.append(Query(sha, path, language_for(path), truth))
    return queries


def evaluate(
    repo_root: Path, queries: list[Query], predictor: Predictor, k: int = max(KS)
) -> dict[str, object]:
    """Overall and per-language scores of one predictor on the queries."""
    overall = Tally()
    by_language: dict[str, Tally] = defaultdict(Tally)
    for q in queries:
        ranked = predictor.predict(repo_root, f"{q.commit}^", q.file, k)
        overall.add(ranked, q.truth)
        by_language[q.language].add(ranked, q.truth)
    return {
        "predictor": predictor.name,
        "overall": overall.summary(),
        "by_language": {lang: t.summary() for lang, t in sorted(by_language.items())},
    }
