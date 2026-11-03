"""The pinned repository list (`repos.yaml`) and its validation.

A SHA is pinned on purpose: a moving branch would make two scoreboards incomparable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REPOS_FILE = Path(__file__).with_name("repos.yaml")
SIZES = ("small", "medium", "large", "very large")
_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_LANGUAGES = frozenset(
    {
        "python",
        "typescript",
        "javascript",
        "go",
        "java",
        "rust",
        "csharp",
        "php",
        "ruby",
        "c",
        "cpp",
        "kotlin",
        "scala",
        "swift",
        "lua",
        "elixir",
        "shell",
    }
)


@dataclass(frozen=True, slots=True)
class RepoSpec:
    """One pinned repository."""

    name: str
    url: str
    sha: str
    languages: tuple[str, ...]
    size: str
    why: str

    @property
    def is_large(self) -> bool:
        return self.size in ("large", "very large")


def load_repos(path: Path = REPOS_FILE) -> list[RepoSpec]:
    """Read and validate the list; raises `ValueError` naming every problem found."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("repos") or []
    specs: list[RepoSpec] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        label = f"entry {i} ({entry.get('name', '?')})"
        missing = [
            k for k in ("name", "url", "sha", "languages", "size", "why") if not entry.get(k)
        ]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue
        if entry["name"] in seen:
            problems.append(f"{label}: duplicate name")
        seen.add(entry["name"])
        if not _SHA.match(str(entry["sha"])):
            problems.append(f"{label}: sha must be 40 lowercase hex characters")
        if entry["size"] not in SIZES:
            problems.append(f"{label}: size must be one of {', '.join(SIZES)}")
        if not str(entry["url"]).startswith("https://github.com/"):
            problems.append(f"{label}: url must be a public https://github.com/ URL")
        specs.append(
            RepoSpec(
                name=str(entry["name"]),
                url=str(entry["url"]),
                sha=str(entry["sha"]),
                languages=tuple(entry["languages"]),
                size=str(entry["size"]),
                why=str(entry["why"]),
            )
        )
    if problems:
        raise ValueError("invalid repos.yaml:\n" + "\n".join(problems))
    return specs


def find_repo(name: str, path: Path = REPOS_FILE) -> RepoSpec:
    """The entry called `name`; `ValueError` lists the known names when it is absent."""
    specs = load_repos(path)
    for spec in specs:
        if spec.name == name:
            return spec
    raise ValueError(f"unknown repository {name!r}; known: {', '.join(s.name for s in specs)}")
