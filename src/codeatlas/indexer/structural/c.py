"""C and C++ resolution profiles: `#include` maps to files, a header and its source are one.

C has no modules: `#include "x.h"` pastes a header in, and the header usually only
*declares* what `x.c` defines. So an include reaches the header, and a prototype found
there is swapped (in `narrow`) for the definition in the header's same-named source file.
Two facts the parse results do not hold are read from the checkout as text: the include
folders named in `CMakeLists.txt`, and whether a function node has a body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import Node, RawCall, RawImport

LANGUAGES = ("c", "cpp")  # `.h` is C in the extension table, so C++ includes reach both
HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx"})
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx")
INCLUDE_FOLDERS = ("include", "src")
_CMAKE_INCLUDES = re.compile(
    r"\b(target_)?include_directories\s*\(([^)]*)\)", re.IGNORECASE
)
_CMAKE_KEYWORDS = frozenset({"PUBLIC", "PRIVATE", "INTERFACE", "SYSTEM", "BEFORE", "AFTER"})
_CMAKE_CURRENT_DIR = re.compile(r"^\$\{CMAKE_CURRENT_SOURCE_DIR\}/?")
_CMAKE_ROOT_DIR = re.compile(r"^\$\{(?:CMAKE_SOURCE_DIR|PROJECT_SOURCE_DIR)\}/?")
_CMAKE_BUILD_INTERFACE = re.compile(r"^\$<BUILD_INTERFACE:([^>]*)>$")
_CMAKE_COMMENT = re.compile(r"#\[(=*)\[.*?\]\1\]|#[^\n]*", re.DOTALL)
_QUALIFIER = re.compile(rb"((?:[A-Za-z_]\w*\s*::\s*)+)~?[A-Za-z_]\w*\s*$")


@dataclass(frozen=True, slots=True)
class _Shape:
    """What the source text says about one function node."""

    is_prototype: bool
    scope: tuple[str, ...]  # namespaces and classes around it: `ns.C.m` -> ("ns", "C")


class CProfile(Profile):
    """Includes reach files; own file, then the same-named header or source, is the scope."""

    languages = frozenset({"c"})
    unqualified_uses_package = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        target = imp.target
        system = target.startswith("<") and target.endswith(">")
        name = target[1:-1].strip() if system else target
        path = None if system else _relative(file.directory, name, ctx)
        path = path or _in_include_folders(ctx, file, name)
        if path is None and not system:
            path = _unique_suffix(ctx, name)
        if path is None:
            return Reach(imp, external=name)
        return Reach(imp, (path,), names=None)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        return _partners(ctx, file.path)

    def narrow(self, ctx: Context, file: FileInfo, call: RawCall, nodes: list[Node]) -> list[Node]:
        if call.receiver and call.callee_text.endswith("::" + call.name):
            wanted = tuple(p.strip() for p in call.receiver.split("::") if p.strip())
            nodes = [n for n in nodes if _scope_ends_with(_shape(ctx, n).scope, wanted)]
        return _definitions_first(ctx, nodes)


class CppProfile(CProfile):
    """C's rules, plus classes: `m()` in a method looks in its class first."""

    languages = frozenset({"cpp"})
    has_class_chain = True


# Includes


def _relative(directory: str, name: str, ctx: Context) -> str | None:
    """`#include "x.h"` beside the including file (`../` allowed)."""
    path = _normalise(f"{directory}/{name}" if directory else name)
    return path if path is not None and path in ctx.files else None


def _in_include_folders(ctx: Context, file: FileInfo, name: str) -> str | None:
    for folder in _include_folders(ctx, file):
        path = _normalise(f"{folder}/{name}" if folder else name)
        if path is not None and path in ctx.files:
            return path
    return None


def _include_folders(ctx: Context, file: FileInfo) -> list[str]:
    """`include/` and `src/` in the file's folder and every ancestor, nearest first;
    then the folders `CMakeLists.txt` files name; then the repository root."""
    folders: list[str] = []
    directory = file.directory
    while directory:
        folders += [f"{directory}/{f}" for f in INCLUDE_FOLDERS]
        directory = directory.rsplit("/", 1)[0] if "/" in directory else ""
    folders += list(INCLUDE_FOLDERS)
    folders += _cmake_folders(ctx)
    folders.append("")
    return folders


def _cmake_folders(ctx: Context) -> list[str]:
    cached = ctx.cache.get("c_cmake_folders")
    if cached is None:
        cached = ctx.cache["c_cmake_folders"] = _read_cmake_folders(ctx)
    return cached  # type: ignore[return-value]


def _read_cmake_folders(ctx: Context) -> list[str]:
    """Folders in `include_directories(...)` lines, relative to each CMakeLists.txt.

    Comments go first, so `# include_directories(old)` names nothing.
    """
    if ctx.index is None:
        return []
    folders: list[str] = []
    for record in ctx.index.files():
        if PurePosixPath(record.path).name != "CMakeLists.txt":
            continue
        raw = ctx.read(record.path)
        if raw is None:
            continue
        base = str(PurePosixPath(record.path).parent)
        base = "" if base == "." else base
        text = _CMAKE_COMMENT.sub("", raw.decode("utf-8", "replace"))
        for match in _CMAKE_INCLUDES.finditer(text):
            words = match.group(2).split()
            for word in words[1:] if match.group(1) else words:  # skip the target name
                folder = _cmake_folder(base, word)
                if folder is not None and folder not in folders:
                    folders.append(folder)
    return folders


def _cmake_folder(base: str, word: str) -> str | None:
    """One argument of `include_directories`: keywords and other variables are skipped.

    `${CMAKE_CURRENT_SOURCE_DIR}` is the CMakeLists folder; `${CMAKE_SOURCE_DIR}` and
    `${PROJECT_SOURCE_DIR}` are taken as the repository root (a nested `project()` would
    move the second, which text reading cannot see). `$<BUILD_INTERFACE:dir>` is `dir`.
    """
    word = word.strip("\"'")
    wrapped = _CMAKE_BUILD_INTERFACE.match(word)
    if wrapped:
        word = wrapped.group(1).strip("\"'")
    if _CMAKE_ROOT_DIR.match(word):
        base, word = "", _CMAKE_ROOT_DIR.sub("", word)
        if not word:
            return ""
    elif _CMAKE_CURRENT_DIR.match(word):
        word = _CMAKE_CURRENT_DIR.sub("", word)
        if not word:
            return base
    if not word or word.upper() in _CMAKE_KEYWORDS or "$" in word or word.startswith("/"):
        return None
    return _normalise(f"{base}/{word}" if base else word)


def _unique_suffix(ctx: Context, name: str) -> str | None:
    """Last resort for `"x.h"`: the only file anywhere whose path ends with it.

    Projects built with a Makefile pass `-I` folders CodeAtlas cannot read; a unique
    match is still very likely the header meant.
    """
    base = PurePosixPath(name).name
    found = [
        path
        for language in LANGUAGES
        for path in ctx.by_basename.get((language, base), [])
        if path == name or path.endswith("/" + name)
    ]
    return found[0] if len(found) == 1 else None


def _normalise(path: str) -> str | None:
    """Collapse `.` and `..`; None when the path climbs out of the repository."""
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


# Header and source


def _partners(ctx: Context, path: str) -> list[str]:
    """`x.h` <-> `x.c`/`x.cpp`: beside it, else the only such file in the repository."""
    pure = PurePosixPath(path)
    wanted = SOURCE_SUFFIXES if pure.suffix in HEADER_SUFFIXES else tuple(HEADER_SUFFIXES)
    names = [pure.stem + suffix for suffix in wanted]
    beside = [str(pure.with_name(n)) for n in names if str(pure.with_name(n)) in ctx.files]
    if beside:
        return beside
    anywhere = [
        p for language in LANGUAGES for n in names for p in ctx.by_basename.get((language, n), [])
    ]
    return anywhere if len(anywhere) == 1 else []


def _definitions_first(ctx: Context, nodes: list[Node]) -> list[Node]:
    """A prototype stands for its definition: swap it for the one in the partner file.

    A prototype whose definition is not found stays: it is still the declaration the
    caller compiled against. When definitions are among the candidates, prototypes go.
    """
    result: list[Node] = []
    for node in nodes:
        if not _shape(ctx, node).is_prototype:
            result.append(node)
            continue
        found = _definition_of(ctx, node)
        result += found or [node]
    unique = list({n.key: n for n in result}.values())
    defined = [n for n in unique if not _shape(ctx, n).is_prototype]
    return defined or unique


def _definition_of(ctx: Context, prototype: Node) -> list[Node]:
    scope = _shape(ctx, prototype).scope
    paths = [prototype.path, *_partners(ctx, prototype.path)]
    found = []
    for path in paths:
        info = ctx.files.get(path)
        for node in info.functions.get(prototype.name, []) if info else []:
            shape = _shape(ctx, node)
            if not shape.is_prototype and _scope_ends_with(shape.scope, scope[-1:]):
                found.append(node)
    return found


def _scope_ends_with(scope: tuple[str, ...], wanted: tuple[str, ...]) -> bool:
    return not wanted or scope[-len(wanted) :] == wanted


# Reading a function's shape from the source


def _shape(ctx: Context, node: Node) -> _Shape:
    shapes = ctx.cache.setdefault("c_shapes", {})
    assert isinstance(shapes, dict)
    if node.key not in shapes:
        shapes[node.key] = _read_shape(ctx, node)
    return shapes[node.key]


def _read_shape(ctx: Context, node: Node) -> _Shape:
    """Prototype or definition, and the full scope (`void C::z()` adds C to `z`)."""
    scope = tuple(p.split("#", 1)[0] for p in node.qualname.split(".")[:-1])
    lines = _lines(ctx, node.path)
    if not lines:
        return _Shape(False, scope)
    start = _offset(lines, node.span.start_line, node.span.start_col)
    end = _offset(lines, node.span.end_line, node.span.end_col)
    source = b"".join(lines)
    head = source[start:end].split(b"(", 1)[0]
    written = _QUALIFIER.search(head)
    if written:
        extra = tuple(p.strip() for p in written.group(1).decode("utf-8", "replace").split("::"))
        scope = scope + tuple(p for p in extra if p)
    return _Shape(_is_prototype(source, start, end), scope)


def _lines(ctx: Context, path: str) -> list[bytes]:
    texts = ctx.cache.setdefault("c_sources", {})
    assert isinstance(texts, dict)
    if path not in texts:
        raw = ctx.read(path)
        texts[path] = raw.splitlines(keepends=True) if raw else []
    return texts[path]


def _offset(lines: list[bytes], line: int, column: int) -> int:
    return sum(len(text) for text in lines[: line - 1]) + column


def _is_prototype(source: bytes, start: int, end: int) -> bool:
    """A definition's node spans its body, so its text ends with `}`; a prototype's node
    is only the declarator, and what follows it decides.

    Reading past a definition's `}` would find the next `int x;` and call it a prototype.
    """
    if source[start:end].rstrip().endswith(b"}"):
        return False
    return _ends_with_semicolon(source, end)


def _ends_with_semicolon(source: bytes, position: int) -> bool:
    """After the declarator, a `;` before any `{` means there is no body."""
    semicolon = source.find(b";", position)
    brace = source.find(b"{", position)
    if semicolon == -1:
        return False
    return brace == -1 or semicolon < brace
