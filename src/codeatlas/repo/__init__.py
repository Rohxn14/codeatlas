"""Repository layer: manifests, packages, test conventions and co-change (T15).

These analyzers need no parser, so they work on every repository whatever its
languages. Each is a `RepoAnalyzer` (contract section 7): it may read files and run
read-only git commands, and never runs build tools, package managers or repository code.
"""

from __future__ import annotations

from codeatlas.config import Config
from codeatlas.indexer.adapter import RepoAnalyzer
from codeatlas.repo.cochange import CoChangeAnalyzer
from codeatlas.repo.manifests import ManifestAnalyzer
from codeatlas.repo.summary import summarize
from codeatlas.repo.test_conventions import TestConventionsAnalyzer

__all__ = [
    "CoChangeAnalyzer",
    "ManifestAnalyzer",
    "TestConventionsAnalyzer",
    "default_analyzers",
    "summarize",
]


def default_analyzers(config: Config | None = None) -> list[RepoAnalyzer]:
    """The three analyzers every index runs, with history depth from `codeatlas.toml`."""
    config = config or Config()
    return [
        ManifestAnalyzer(),
        TestConventionsAnalyzer(),
        CoChangeAnalyzer(max_commits=config.max_history_commits),
    ]
