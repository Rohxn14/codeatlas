"""Discovery: list every file worth indexing, with its language, tier and content hash.

Files come from `git ls-files` inside a git work tree (exactly what the repository
tracks, plus untracked files git does not ignore), otherwise from a directory walk that
honours `.gitignore`. Anything left out is recorded with a reason, never dropped silently.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pathspec

from codeatlas.config import Limits
from codeatlas.indexer.intake import run_git
from codeatlas.models import FileRecord, Tier

TEXT_LANGUAGE = "text"

# Grammar names for files the structural tier can parse.
GRAMMAR_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".cs": "c_sharp",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".rb": "ruby",
}

# Languages CodeAtlas recognises but has no grammar for yet: text tier, but named, so the
# census shows "kotlin: 40 files" instead of hiding them in "text".
TEXT_LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".dart": "dart",
    ".sh": "bash",
    ".bash": "bash",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
    ".md": "markdown",
    ".rst": "rst",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".proto": "proto",
}

TEXT_LANGUAGE_BY_FILENAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
}

SKIP_DIRS = frozenset({"node_modules", ".venv", "venv", "dist", "build", ".git"})
MINIFIED_SUFFIXES = (".min.js", ".min.mjs", ".min.css")
BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A path discovery left out, and why."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class Discovery:
    """What discovery found: files to index, paths left out, and limits reached."""

    files: tuple[FileRecord, ...]
    skipped: tuple[SkippedFile, ...] = ()
    limits_hit: tuple[str, ...] = ()


def detect_language(path: str) -> str:
    """Grammar name for a repo-relative path, a named text language, or `"text"`."""
    name = PurePosixPath(path).name
    if name in TEXT_LANGUAGE_BY_FILENAME:
        return TEXT_LANGUAGE_BY_FILENAME[name]
    suffix = PurePosixPath(path).suffix.lower()
    return (
        GRAMMAR_BY_EXTENSION.get(suffix) or TEXT_LANGUAGE_BY_EXTENSION.get(suffix) or TEXT_LANGUAGE
    )


def extensions_for(language: str) -> tuple[str, ...]:
    """Every extension that maps to `language`, for an adapter's `extensions`."""
    table = {**GRAMMAR_BY_EXTENSION, **TEXT_LANGUAGE_BY_EXTENSION}
    return tuple(sorted(ext for ext, lang in table.items() if lang == language))


def discover(
    root: Path,
    limits: Limits | None = None,
    tier_for: Callable[[str], Tier] | None = None,
    deadline: float | None = None,
) -> Discovery:
    """List the files under `root` in path order, stopping at `max_files` or `deadline`.

    `tier_for` maps a language to the tier its adapter will report; by default it asks the
    default registry, so a file's tier always matches what parsing will produce.
    `deadline` is a `time.monotonic()` value.
    """
    limits = limits or Limits()
    if tier_for is None:
        from codeatlas.indexer.registry import default_registry

        tier_for = default_registry().tier_for
    candidates, skipped = _list_paths(root)
    files: list[FileRecord] = []
    limits_hit: list[str] = []
    for rel in sorted(candidates):
        if deadline is not None and time.monotonic() > deadline:
            limits_hit.append("max_seconds")
            break
        record, reason = _inspect(root, rel, limits, tier_for)
        if record is None:
            skipped.append(SkippedFile(rel, reason))
            continue
        if len(files) >= limits.max_files:
            limits_hit.append("max_files")
            break
        files.append(record)
    return Discovery(files=tuple(files), skipped=tuple(skipped), limits_hit=tuple(limits_hit))


def _list_paths(root: Path) -> tuple[list[str], list[SkippedFile]]:
    """Candidate paths, minus those under always-skipped folders (each folder recorded once)."""
    paths = _git_paths(root)
    if paths is None:
        return _walk(root)
    kept: list[str] = []
    skipped_dirs: dict[str, None] = {}
    for rel in paths:
        parts = rel.split("/")
        hit = next((i for i, part in enumerate(parts[:-1]) if part in SKIP_DIRS), None)
        if hit is None:
            kept.append(rel)
        else:
            skipped_dirs.setdefault("/".join(parts[: hit + 1]), None)
    return kept, [SkippedFile(d, "excluded directory") for d in skipped_dirs]


def _git_paths(root: Path) -> list[str] | None:
    """Tracked plus untracked-but-not-ignored files, relative to `root`; None outside git."""
    try:
        out = run_git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root)
    except (RuntimeError, FileNotFoundError):
        return None
    return sorted({p for p in out.split("\0") if p})


def _walk(root: Path) -> tuple[list[str], list[SkippedFile]]:
    """Walk outside git, honouring every `.gitignore` on the way down."""
    files: list[str] = []
    skipped: list[SkippedFile] = []
    specs: list[tuple[str, pathspec.GitIgnoreSpec]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        specs = [(base, spec) for base, spec in specs if _is_within(rel_dir, base)]
        ignore_file = Path(dirpath) / ".gitignore"
        if ignore_file.is_file():
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
            specs.append((rel_dir, pathspec.GitIgnoreSpec.from_lines(lines)))
        kept_dirs = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS:
                skipped.append(SkippedFile(_join(rel_dir, d), "excluded directory"))
            elif not _ignored(_join(rel_dir, d) + "/", specs):
                kept_dirs.append(d)
        dirnames[:] = kept_dirs  # os.walk descends only into these
        files.extend(
            rel for rel in (_join(rel_dir, n) for n in filenames) if not _ignored(rel, specs)
        )
    return files, skipped


def _ignored(rel: str, specs: list[tuple[str, pathspec.GitIgnoreSpec]]) -> bool:
    for base, spec in specs:
        local = rel[len(base) + 1 :] if base else rel
        if spec.match_file(local):
            return True
    return False


def _is_within(rel_dir: str, base: str) -> bool:
    return base == "" or rel_dir == base or rel_dir.startswith(base + "/")


def _join(base: str, name: str) -> str:
    return f"{base}/{name}" if base else name


def _inspect(
    root: Path, rel: str, limits: Limits, tier_for: Callable[[str], Tier]
) -> tuple[FileRecord | None, str]:
    """A FileRecord for one path, or None and the reason it is left out."""
    full = root / rel
    if full.is_symlink():
        return None, "symlink"
    if not full.is_file():
        return None, "not a regular file"
    if rel.lower().endswith(MINIFIED_SUFFIXES):
        return None, "minified"
    size = full.stat().st_size
    if size > limits.max_file_bytes:
        return None, f"over max_file_bytes ({size} bytes)"
    data = full.read_bytes()
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return None, "binary"
    language = detect_language(rel)
    record = FileRecord(
        path=rel,
        language=language,
        tier=tier_for(language),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    return record, ""
