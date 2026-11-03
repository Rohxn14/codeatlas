"""Predictors for the co-change benchmark, and the protocol the impact engine (T12) plugs into.

`rev` is the last commit a predictor may look at, normally `<held-out commit>^`, so it
never sees the answer. Both shipped predictors read the same history and apply the same
filters as the repository layer.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Protocol

from codeatlas.repo.cochange import CoChangeAnalyzer, History, read_history
from eval.cochange.gitread import files_at


class Predictor(Protocol):
    """Rank other files likely to change together with `changed_file`."""

    name: str

    def predict(self, repo_root: Path, rev: str, changed_file: str, k: int) -> list[str]: ...


class _Cached:
    """History and file list for the latest `rev`; every file of one commit shares them."""

    def __init__(self, max_commits: int) -> None:
        self.max_commits = max_commits
        self._key: tuple[Path, str] | None = None
        self.history = History()
        self.present: set[str] = set()

    def load(self, repo_root: Path, rev: str) -> bool:
        """True when a new revision was loaded, so subclasses rebuild their index."""
        if self._key == (repo_root, rev):
            return False
        self._key = (repo_root, rev)
        self.history = read_history(repo_root, self.max_commits, rev)
        self.present = files_at(repo_root, rev) if self.history.commits else set()
        return True


class CoChangePredictor:
    """Files ranked by the repository layer's rule: confidence, then support, then name."""

    name = "cochange"

    def __init__(self, max_commits: int = 2_000) -> None:
        self._cache = _Cached(max_commits)
        self._analyzer = CoChangeAnalyzer(max_commits=max_commits)
        self._ranked: dict[str, list[str]] = {}

    def predict(self, repo_root: Path, rev: str, changed_file: str, k: int) -> list[str]:
        if self._cache.load(repo_root, rev):
            self._ranked = self._index()
        return self._ranked.get(changed_file, [])[:k]

    def _index(self) -> dict[str, list[str]]:
        changed, together, _ = self._analyzer._count(
            self._cache.history.commits, self._cache.present
        )
        targets: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
        for (a, b), support in together.items():
            if support < self._analyzer.min_support:
                continue
            targets[a].append((support / changed[a], support, b))
            targets[b].append((support / changed[b], support, a))
        return {
            source: [t[2] for t in sorted(found, key=lambda t: (-t[0], -t[1], t[2]))]
            for source, found in targets.items()
        }


class SameFolderPredictor:
    """Baseline: other files in the same folder, most recently changed first."""

    name = "same-folder"

    def __init__(self, max_commits: int = 2_000) -> None:
        self._cache = _Cached(max_commits)
        self._analyzer = CoChangeAnalyzer(max_commits=max_commits)
        self._recency: list[str] = []

    def predict(self, repo_root: Path, rev: str, changed_file: str, k: int) -> list[str]:
        if self._cache.load(repo_root, rev):
            self._recency = self._by_recency()
        folder = changed_file.rpartition("/")[0]
        same = [p for p in self._recency if p != changed_file and p.rpartition("/")[0] == folder]
        return same[:k]

    def _by_recency(self) -> list[str]:
        """Distinct kept paths in order of their latest change (history is newest first)."""
        seen: Counter[str] = Counter()
        order: list[str] = []
        for paths in self._cache.history.commits:
            for path in paths:
                if path in seen or self._analyzer._filter_reason(path, self._cache.present):
                    continue
                seen[path] += 1
                order.append(path)
        return order
