"""Discovery: list every file of a repository with its language, tier and content hash.

Files come from `git ls-files` inside a git work tree (so the repository's own ignore
rules apply exactly as git applies them), otherwise from a walk that honours
`.gitignore` files through `pathspec`. Anything that cannot be analysed (a binary, a
minified bundle, a file over the size limit, a symlink) is listed in `skipped` with its
reason instead of disappearing.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pathspec

from codeatlas.config import Config, Deadline
from codeatlas.models import FileRecord, Tier

TEXT_LANGUAGE = "text"
BINARY_SNIFF_BYTES = 8192

EXCLUDED_DIRS = frozenset(
    {"node_modules", ".venv", "venv", "dist", "build", ".git", ".codeatlas"}
)
MINIFIED_SUFFIXES = (".min.js", ".min.css", ".min.mjs")

# Extension -> language. Grammar names for languages CodeAtlas can parse; other names
# label text-tier files so the census still says what they are.
LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".cs": "c_sharp",
    ".php": "php",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".scala": "scala", ".sc": "scala",
    ".lua": "lua",
    ".swift": "swift",
    ".ex": "elixir", ".exs": "elixir",
    # Text tier: recognised, not parsed.
    ".kt": "kotlin", ".kts": "kotlin",
    ".dart": "dart", ".hs": "haskell", ".ml": "ocaml", ".mli": "ocaml",
    ".zig": "zig", ".r": "r", ".jl": "julia", ".pl": "perl", ".pm": "perl",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell",
    ".vue": "vue", ".svelte": "svelte",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".sql": "sql", ".proto": "proto", ".graphql": "graphql", ".gql": "graphql",
    ".md": "markdown", ".rst": "rst",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".xml": "xml",
    ".ini": "ini", ".cfg": "ini",
}
LANGUAGE_BY_FILENAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
    "GNUmakefile": "make",
    "CMakeLists.txt": "cmake",
}


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A path discovery saw but will not analyse, and why."""

    path: str
    reason: str
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class Discovery:
    """What discovery found: files to analyse, files it skipped, limits it reached."""

    files: list[FileRecord]
    skipped: list[SkippedFile]
    limits_hit: tuple[str, ...]
    used_git: bool


def language_for(path: str) -> str:
    """Language of a repo-relative path, from its file name or extension."""
    name = PurePosixPath(path).name
    if name in LANGUAGE_BY_FILENAME:
        return LANGUAGE_BY_FILENAME[name]
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(name).suffix.lower(), TEXT_LANGUAGE)


def extensions_for(language: str) -> tuple[str, ...]:
    return tuple(ext for ext, lang in LANGUAGE_BY_EXTENSION.items() if lang == language)


def discover(
    root: Path,
    config: Config,
    tier_for: Callable[[str], Tier],
    deadline: Deadline | None = None,
) -> Discovery:
    """List and hash the files under `root`, stopping at the file and time limits.

    `tier_for` comes from the registry, so a file's tier says what will really happen
    to it: a language whose grammar failed to load is reported as text, not structural.
    """
    deadline = deadline or Deadline(config.max_seconds)
    git_paths = _git_ls_files(root)
    candidates = git_paths if git_paths is not None else _walk(root)
    files: list[FileRecord] = []
    skipped: list[SkippedFile] = []
    limits: set[str] = set()
    for rel in candidates:
        if deadline.expired():
            limits.add("max_seconds")
            break
        if len(files) >= config.max_files:
            limits.add("max_files")
            break
        outcome = _examine(root, rel, config, tier_for)
        if isinstance(outcome, FileRecord):
            files.append(outcome)
            continue
        if outcome is not None:
            skipped.append(outcome)
            if outcome.reason.startswith("over max_file_bytes"):
                limits.add("max_file_bytes")
    return Discovery(files, skipped, tuple(sorted(limits)), git_paths is not None)


def _examine(
    root: Path, rel: str, config: Config, tier_for: Callable[[str], Tier]
) -> FileRecord | SkippedFile | None:
    """Turn one candidate path into a record, a skip with a reason, or None if it vanished."""
    parts = rel.split("/")
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return SkippedFile(rel, "excluded directory")
    full = root.joinpath(*parts)
    if full.is_symlink():
        return SkippedFile(rel, "symlink")
    if full.is_dir():
        return SkippedFile(rel, "git submodule (not fetched)")
    if not full.is_file():
        return None  # listed by git but deleted from the work tree: not part of this snapshot
    size = full.stat().st_size
    if rel.lower().endswith(MINIFIED_SUFFIXES):
        return SkippedFile(rel, "minified", size)
    if size > config.max_file_bytes:
        return SkippedFile(rel, f"over max_file_bytes ({config.max_file_bytes})", size)
    data = full.read_bytes()
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return SkippedFile(rel, "binary", size)
    language = language_for(rel)
    tier = Tier.TEXT if language == TEXT_LANGUAGE else tier_for(language)
    return FileRecord(rel, language, tier, hashlib.sha256(data).hexdigest(), len(data))


def _git_ls_files(root: Path) -> list[str] | None:
    """Tracked plus untracked-but-not-ignored files, or None when `root` is not in git."""
    command = [
        "git", "-c", "core.fsmonitor=false", "-C", str(root),
        "ls-files", "-z", "--cached", "--others", "--exclude-standard",
    ]
    try:
        done = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    paths = {p for p in done.stdout.decode("utf-8", "surrogateescape").split("\0") if p}
    return sorted(paths)


def _walk(root: Path) -> Iterator[str]:
    """Walk `root` in sorted order, pruning excluded folders and `.gitignore`d paths."""
    specs: list[tuple[str, pathspec.PathSpec]] = []
    for current, dirnames, filenames in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        ignore_file = Path(current) / ".gitignore"
        if ignore_file.is_file():
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
            specs.append((rel_dir, pathspec.GitIgnoreSpec.from_lines(lines)))
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not _ignored(_join(rel_dir, d) + "/", specs)
        )
        for name in sorted(filenames):
            rel = _join(rel_dir, name)
            if not _ignored(rel, specs):
                yield rel


def _join(rel_dir: str, name: str) -> str:
    return f"{rel_dir}/{name}" if rel_dir else name


def _ignored(rel: str, specs: list[tuple[str, pathspec.PathSpec]]) -> bool:
    """True when any `.gitignore` at or above the path's folder matches it."""
    for base, spec in specs:
        if base and not rel.startswith(base + "/"):
            continue
        if spec.match_file(rel[len(base) + 1 :] if base else rel):
            return True
    return False
