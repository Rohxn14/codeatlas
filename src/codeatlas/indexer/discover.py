"""Discovery: list every file of a repository with its language, tier and content hash.

Files come from `git ls-files` when the folder is the top level of a git repository
(so the repository's own ignore rules apply exactly as git applies them), otherwise
from a walk that honours `.gitignore` files through `pathspec`. Anything that cannot be
analysed (a binary, a minified bundle, a file over the size limit, a symlink) is listed
in `skipped` with its reason instead of disappearing.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable
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

# Files that usually hold keys or passwords. They stay on the map by name; nothing in
# CodeAtlas reads what is in them, because indexed text can reach a language model.
SECRET_REASON = "may hold secrets: its content is never read"
_SECRET_NAMES = frozenset({
    ".env", ".envrc", ".netrc", ".npmrc", ".pypirc", ".htpasswd", "credentials",
    "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".jks", ".keystore")
# `.env.example` and its like are made to be read: they show the names, not the values.
_SAMPLE_ENDINGS = (".example", ".sample", ".template", ".dist")

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
class SkippedPath:
    """A folder, symlink or submodule discovery did not enter, recorded once with its reason."""

    path: str
    reason: str
    file_count: int = 0


@dataclass(frozen=True, slots=True)
class Discovery:
    """What discovery found.

    `files` holds every file, including ones that cannot be analysed (binary, minified,
    too large): those are TEXT records, and `skip_reasons` says why for each path.
    `skipped` lists what was not entered at all, one entry per folder or link.
    """

    files: list[FileRecord]
    skip_reasons: dict[str, str]
    skipped: list[SkippedPath]
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
    if git_paths is not None:
        candidates, skipped = _drop_excluded(git_paths)
    else:
        candidates, skipped = _walk(root)
    files: list[FileRecord] = []
    skip_reasons: dict[str, str] = {}
    limits: set[str] = set()
    for rel in candidates:
        if deadline.expired():
            limits.add("max_seconds")
            break
        if len(files) >= config.max_files:
            limits.add("max_files")
            break
        outcome = _examine(root, rel, config, tier_for)
        if isinstance(outcome, SkippedPath):
            skipped.append(outcome)
        elif outcome is not None:
            record, reason = outcome
            files.append(record)
            if reason:
                skip_reasons[rel] = reason
                if reason.startswith("over max_file_bytes"):
                    limits.add("max_file_bytes")
    return Discovery(files, skip_reasons, skipped, tuple(sorted(limits)), git_paths is not None)


def _examine(
    root: Path, rel: str, config: Config, tier_for: Callable[[str], Tier]
) -> tuple[FileRecord, str | None] | SkippedPath | None:
    """A record (with a reason when it will not be parsed), a path not entered, or None.

    None means git listed a file that is no longer in the work tree, so it is not part
    of this snapshot.
    """
    full = root.joinpath(*rel.split("/"))
    if full.is_symlink():
        return SkippedPath(rel, "symlink")
    if full.is_dir():
        return SkippedPath(rel, "git submodule (not fetched)")
    if not full.is_file():
        return None
    language = language_for(rel)
    size = full.stat().st_size
    if is_secret_path(rel):
        # The hash stands for the name and size only: the bytes are not read.
        digest = hashlib.sha256(f"{rel}\0{size}".encode()).hexdigest()
        return FileRecord(rel, TEXT_LANGUAGE, Tier.TEXT, digest, size), SECRET_REASON
    reason = None
    if rel.lower().endswith(MINIFIED_SUFFIXES):
        reason = "minified"
    elif size > config.max_file_bytes:
        # A large image or archive is binary, not a text file too long to read.
        with full.open("rb") as handle:
            binary = b"\0" in handle.read(BINARY_SNIFF_BYTES)
        reason = "binary" if binary else f"over max_file_bytes ({config.max_file_bytes})"
    if reason:
        return FileRecord(rel, language, Tier.TEXT, _hash_file(full), size), reason
    data = full.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return FileRecord(rel, language, Tier.TEXT, digest, len(data)), "binary"
    tier = Tier.TEXT if language == TEXT_LANGUAGE else tier_for(language)
    return FileRecord(rel, language, tier, digest, len(data)), None


def is_secret_path(path: str) -> bool:
    """True for a file whose content must never be read (see SECRET_REASON)."""
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith(_SAMPLE_ENDINGS):
        return False
    return (name in _SECRET_NAMES or name.startswith(".env.")
            or name.endswith(_SECRET_SUFFIXES))


def _hash_file(path: Path) -> str:
    """SHA-256 without reading a large file into memory at once."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _drop_excluded(paths: list[str]) -> tuple[list[str], list[SkippedPath]]:
    """Remove paths under excluded folders, recording each folder once with its file count."""
    kept: list[str] = []
    counts: dict[str, int] = {}
    for rel in paths:
        parts = rel.split("/")
        hit = next((i for i, part in enumerate(parts[:-1]) if part in EXCLUDED_DIRS), None)
        if hit is None:
            kept.append(rel)
        else:
            folder = "/".join(parts[: hit + 1])
            counts[folder] = counts.get(folder, 0) + 1
    skipped = [SkippedPath(f, "excluded directory", n) for f, n in sorted(counts.items())]
    return kept, skipped


def _git_ls_files(root: Path) -> list[str] | None:
    """Tracked plus untracked-but-not-ignored files, or None to walk the folder instead.

    Git mode is used only when `root` is the top level of its own repository. A folder
    inside someone else's repository (an untracked project in a home folder that is a
    git repository, say) would otherwise lose every file the outer repository ignores
    (`--others` lists untracked files, but the outer repository's ignore rules would
    still hide files), so it is walked with its own `.gitignore` rules instead.
    """
    if not is_repo_top_level(root):
        return None
    done = _run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if done is None:
        return None
    paths = {p for p in done.decode("utf-8", "surrogateescape").split("\0") if p}
    return sorted(paths)


def is_repo_top_level(root: Path) -> bool:
    """True when `root` is the top folder of its own git repository.

    Discovery and intake share this rule, so they always agree on what "the repository"
    is: files are listed by git, and the snapshot gets a commit SHA, only at the top.
    """
    done = _run_git(root, "rev-parse", "--show-toplevel")
    if done is None:
        return False
    top = done.decode("utf-8", "surrogateescape").strip()
    return bool(top) and _same_path(Path(top), root)


def _same_path(a: Path, b: Path) -> bool:
    """Equal after resolving links, ignoring case where the OS does (Windows)."""
    return os.path.normcase(a.resolve()) == os.path.normcase(b.resolve())


def _run_git(root: Path, *args: str) -> bytes | None:
    """Stdout of a read-only git command in `root`, or None if git fails or is missing."""
    command = ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args]
    try:
        done = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _walk(root: Path) -> tuple[list[str], list[SkippedPath]]:
    """Walk `root` in sorted order, honouring `.gitignore`, and record excluded folders.

    An excluded folder (`node_modules`, `dist`, ...) is recorded even when `.gitignore`
    also lists it: it is on disk, so the census should say it was left out.
    """
    files: list[str] = []
    skipped: list[SkippedPath] = []
    specs: list[tuple[str, pathspec.PathSpec]] = []
    for current, dirnames, filenames in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        ignore_file = Path(current) / ".gitignore"
        if ignore_file.is_file():
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
            specs.append((rel_dir, pathspec.GitIgnoreSpec.from_lines(lines)))
        entered = []
        for name in sorted(dirnames):
            rel = _join(rel_dir, name)
            if name in EXCLUDED_DIRS:
                skipped.append(SkippedPath(rel, "excluded directory", _count_files(root / rel)))
            elif _ignored(rel + "/", specs):
                continue
            elif (Path(current) / name).is_symlink():
                skipped.append(SkippedPath(rel, "symlink"))
            else:
                entered.append(name)
        dirnames[:] = entered  # os.walk descends only into these
        for name in sorted(filenames):
            rel = _join(rel_dir, name)
            if not _ignored(rel, specs):
                files.append(rel)
    return files, skipped


def _count_files(folder: Path) -> int:
    """Files under a skipped folder, counted without reading them or following links."""
    return sum(len(names) for _, _, names in os.walk(folder))


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
