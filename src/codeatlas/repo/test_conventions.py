"""Part 2 of the repository layer: pair test files with the source files they test, by name.

Every language has a naming habit for tests (`test_user.py`, `user.test.ts`,
`UserTest.java`). Reading the habit backwards names the file under test: strip the
affix, then look for a source file with that name. When several match, the ranking
prefers the same package, then the folder layout the test mirrors, then the nearest
folder. Candidates that tie split the confidence, so an unsure pairing says so.

A file in a test folder without a test affix (`tests/helpers.py`) is a *support file*:
it counts as a test file but is not paired, because its name says nothing about what it
tests. JavaScript (`__tests__/user.js`, mocha's `test/user.js`) and Rust (`tests/*.rs`)
are the exceptions, since their conventions do not use an affix.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.models import Edge, EdgeKind, FileRecord, Node, Resolution
from codeatlas.repo.ecosystems import rust
from codeatlas.repo.ecosystems.base import Declared
from codeatlas.repo.manifests import find_packages
from codeatlas.repo.paths import basename, child, module_id, parent, repo_name

CONFIDENCE = 0.8
TEST_FOLDERS = frozenset({"test", "tests", "spec", "specs", "__tests__"})
# C# test projects: `Shop.Tests/` mirrors `Shop/`.
TEST_PROJECT_SUFFIXES = (".unittests", ".integrationtests", ".tests", ".test")
# Folder names that group code or tests without saying which code: skipped when
# comparing the folder layout of a test with that of a candidate.
_LAYOUT_NOISE = TEST_FOLDERS | {
    "unit", "integration", "functional", "feature", "features", "e2e",
    "src", "main", "lib", "app", "java", "kotlin",
}
# Declarations rank below the code they declare: a C header, a Python type stub.
_DECLARATIONS = (".h", ".hh", ".hpp", ".hxx", ".pyi")
_RUST_LIBRARY = "lib"  # subject of a Rust integration test: its crate's library

FAMILIES: dict[str, str] = {
    "python": "python",
    "typescript": "js", "tsx": "js", "javascript": "js",
    "go": "go",
    "java": "jvm", "kotlin": "jvm",
    "c_sharp": "csharp",
    "ruby": "ruby",
    "php": "php",
    "rust": "rust",
    "c": "c", "cpp": "c",
}


@dataclass(frozen=True, slots=True)
class TestFile:
    """A file recognised as a test; `subject` is the source name it points at, if any."""

    __test__ = False  # not a pytest test class, despite the name

    path: str
    family: str
    subject: str | None


def classify(path: str, language: str) -> TestFile | None:
    """The test file at `path`, or None when it is not one by its language's convention."""
    family = FAMILIES.get(language)
    if family is None:
        return None
    folders = path.split("/")[:-1]
    in_test_folder = any(f.lower() in TEST_FOLDERS for f in folders)
    verdict = _RULES[family](basename(path), folders, in_test_folder)
    if verdict is None:
        return None
    return TestFile(path, family, verdict or None)


# Each rule returns the subject name, "" for a support file, or None for "not a test".
Rule = Callable[[str, list[str], bool], str | None]


def _affix_rule(*patterns: str, support_in_test_folder: bool = True) -> Rule:
    """A rule from regexes over the file stem; group 1 of the first match is the subject."""
    compiled = [re.compile(p) for p in patterns]

    def rule(name: str, folders: list[str], in_test_folder: bool) -> str | None:
        stem = _stem(name)
        for pattern in compiled:
            match = pattern.fullmatch(stem)
            if match:
                return match.group(1)
        return "" if in_test_folder and support_in_test_folder else None

    return rule


def _js(name: str, folders: list[str], in_test_folder: bool) -> str | None:
    match = re.fullmatch(r"(.+)\.(?:test|spec)\.[^.]+", name)
    if match:
        return match.group(1)
    return _stem(name) if in_test_folder else None


def _go(name: str, folders: list[str], in_test_folder: bool) -> str | None:
    return name[: -len("_test.go")] if name.endswith("_test.go") else None


def _csharp(name: str, folders: list[str], in_test_folder: bool) -> str | None:
    match = re.fullmatch(r"(.+?)Tests?", _stem(name))
    if match:
        return match.group(1)
    in_test_project = any(f.lower().endswith(TEST_PROJECT_SUFFIXES) for f in folders)
    return "" if in_test_folder or in_test_project else None


def _rust(name: str, folders: list[str], in_test_folder: bool) -> str | None:
    return _RUST_LIBRARY if "tests" in folders else None


_RULES: dict[str, Rule] = {
    "python": _affix_rule(r"test_(.+)", r"(.+)_test"),
    "js": _js,
    "go": _go,
    # `UserServiceIT` is an integration test; `GIT` is not (IT must follow a lower case).
    "jvm": _affix_rule(r"(.+?)Tests?", r"(.+?[a-z0-9])IT"),
    "csharp": _csharp,
    "ruby": _affix_rule(r"(.+)_(?:spec|test)", r"test_(.+)"),
    "php": _affix_rule(r"(.+?)Test"),
    "rust": _rust,
    "c": _affix_rule(r"test_(.+)", r"(.+?)_(?:unit)?test"),
}


class TestConventionsAnalyzer:
    """TESTS edges from test modules to the source modules their names point at."""

    __test__ = False

    name = "test_conventions"

    def __init__(self) -> None:
        self.report: dict[str, object] = {}

    def analyze(
        self, repo_root: Path, files: Sequence[FileRecord], snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        # The same package layout the manifest analyzer builds, read again so this
        # analyzer stands alone; manifests are small, so the second read is cheap.
        layout = find_packages(repo_root, files, repo_name(snapshot_id))
        owner = layout.owner
        tests, sources = _split(files)
        edges: list[Edge] = []
        unpaired: list[str] = []
        ambiguous = 0
        for test in tests:
            chosen = _best_candidates(test, sources, owner)
            if not chosen:
                unpaired.append(test.path)
                continue
            attrs: dict[str, object] = {}
            if len(chosen) > 1:
                ambiguous += 1
                attrs["candidates"] = len(chosen)
            for source in chosen:
                edges.append(
                    Edge(module_id(snapshot_id, test.path), module_id(snapshot_id, source),
                         EdgeKind.TESTS, CONFIDENCE / len(chosen), Resolution.CONVENTION,
                         attrs=dict(attrs))
                )
        self.report = {
            "test_files": len(tests),
            "paired": len(tests) - len(unpaired),
            "ambiguous": ambiguous,
            "unpaired": unpaired,
        }
        return [], edges


def _split(files: Sequence[FileRecord]) -> tuple[list[TestFile], dict[tuple[str, str], list[str]]]:
    """Test files, and the other files of each family indexed by (family, stem)."""
    tests: list[TestFile] = []
    sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in sorted(files, key=lambda r: r.path):
        test = classify(record.path, record.language)
        if test is not None:
            tests.append(test)
        elif record.language in FAMILIES:
            sources[(FAMILIES[record.language], _stem(basename(record.path)))].append(record.path)
    return tests, sources


def _best_candidates(
    test: TestFile, sources: dict[tuple[str, str], list[str]], owner: dict[str, Declared]
) -> list[str]:
    """The equally good source files for a test, best first by the ranking."""
    if not test.subject:
        return []
    if test.family == "rust":
        return _rust_targets(test.path, sources, owner.get(test.path))
    candidates = sources.get((test.family, test.subject), [])
    if test.family == "go":  # a Go test file belongs to the package in its own folder
        candidates = [c for c in candidates if parent(c) == parent(test.path)]
    if not candidates:
        return []
    ranks = {c: _rank(test.path, c, owner) for c in candidates}
    best = min(ranks.values())
    return [c for c in candidates if ranks[c] == best]


def _rank(test: str, candidate: str, owner: dict[str, Declared]) -> tuple[int, int, int, int]:
    """Lower is better: same package, then mirrored layout, then code over declarations
    (headers, stubs), then fewest folder steps between the two files."""
    test_package = owner.get(test)
    same_package = test_package is not None and test_package is owner.get(candidate)
    return (
        0 if same_package else 1,
        -_shared_layout(test, candidate),
        1 if candidate.endswith(_DECLARATIONS) else 0,
        _folder_distance(test, candidate),
    )


def _rust_targets(
    test: str, sources: dict[tuple[str, str], list[str]], crate: Declared | None
) -> list[str]:
    """What a Rust integration test exercises: its crate's library, or, for a crate with
    no library, its binaries (which then share the confidence)."""
    rust_files = {p for (family, _), paths in sources.items() if family == "rust" for p in paths}
    if crate is not None and crate.ecosystem == rust.ECOSYSTEM:
        library = crate.extra.get("library")
        targets = [library] if isinstance(library, str) else crate.entry_points
        return [t for t in targets if t in rust_files]
    # No Cargo.toml in the snapshot: assume the default layout around `tests/`.
    folders = test.split("/")[:-1]
    last_tests = len(folders) - 1 - folders[::-1].index("tests")
    crate_root = "/".join(folders[:last_tests])
    for name in ("src/lib.rs", "src/main.rs"):
        if child(crate_root, name) in rust_files:
            return [child(crate_root, name)]
    return []


def _layout(path: str) -> list[str]:
    """Folders that say which code a file is about, lower case, noise removed."""
    parts = []
    for folder in path.lower().split("/")[:-1]:
        for suffix in TEST_PROJECT_SUFFIXES:
            if folder.endswith(suffix):
                folder = folder[: -len(suffix)]
                break
        if folder and folder not in _LAYOUT_NOISE:
            parts.append(folder)
    return parts


def _shared_layout(test: str, candidate: str) -> int:
    """How many trailing folders the two layouts share: `tests/models/test_user.py` and
    `app/models/user.py` share `models`."""
    shared = 0
    for a, b in zip(reversed(_layout(test)), reversed(_layout(candidate)), strict=False):
        if a != b:
            break
        shared += 1
    return shared


def _folder_distance(a: str, b: str) -> int:
    left, right = a.split("/")[:-1], b.split("/")[:-1]
    common = 0
    for x, y in zip(left, right, strict=False):
        if x != y:
            break
        common += 1
    return len(left) + len(right) - 2 * common


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name
