"""Ruby resolution profile: `require` names map to files, reopened classes share a scope."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach, join_relative
from codeatlas.models import NodeKind, RawImport

LANGUAGE = "ruby"
# Libraries whose constant is spelled in capitals; others are guessed by capitalising.
_ACRONYMS = frozenset({"json", "yaml", "csv", "erb", "uri", "cgi", "pstore", "tsort", "openssl"})


class RubyProfile(Profile):
    """Ruby has no import bindings: once a file is required, its constants are global.

    So an import reaches files and brings nothing in by name (`names=None`: every
    top-level method of the file). `Foo.bar` is resolved by the shared "receiver names a
    class in scope" rule. A class or module reopened in several files is one scope,
    which `package_scope` expresses as "files that share a container with this one".
    """

    languages = frozenset({LANGUAGE})
    has_class_chain = True
    type_receivers = True
    unqualified_uses_package = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        method = imp.names[0][0] if imp.names else "require"
        target = imp.target if imp.target.endswith(".rb") else imp.target + ".rb"
        if method == "require_relative":
            path = join_relative(file.directory, target)
            found = [path] if path in ctx.files and path != file.path else []
        elif method == "load":
            path = join_relative(file.directory, target)
            found = [p for p in (path, join_relative("", target)) if p in ctx.files][:1]
        else:
            found = _load_path_files(ctx, file, target)
        if found:
            return Reach(imp, tuple(found), None, None, None, None)
        constant = _constant(imp.target)
        if _defined_in_repo(ctx, constant):
            # `require 'util'` that no `lib/util.rb` answers, with `module Util` in the
            # repository: the guessed constant must not turn `Util.slug` external.
            return Reach(imp, external=imp.target)
        return Reach(imp, external=imp.target, binding=constant)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        """Other files that open a class or module this file also opens."""
        table = _container_table(ctx)
        mine = {c for c, paths in table.items() if file.path in paths}
        return sorted({p for c in mine for p in table[c] if p != file.path})


def _container_table(ctx: Context) -> dict[str, set[str]]:
    table = ctx.cache.get("ruby_containers")
    if table is None:
        table = ctx.cache["ruby_containers"] = _containers(ctx)
    return table  # type: ignore[return-value]


def _defined_in_repo(ctx: Context, constant: str) -> bool:
    """Whether any Ruby file defines a class, or opens a module, called `constant`."""
    if any(constant == name.rsplit(".", 1)[-1] for name in _container_table(ctx)):
        return True
    return any(
        info.language == LANGUAGE and constant in info.types for info in ctx.files.values()
    )


def _load_path_files(ctx: Context, file: FileInfo, target: str) -> list[str]:
    """`require "a/b"` is `lib/a/b.rb`; with several gems, the one nearest to `file`."""
    wanted = "lib/" + target
    matches = [p for p in ctx.files if ctx.files[p].language == LANGUAGE
               and (p == wanted or p.endswith("/" + wanted))]
    if not matches:
        return []
    best = max(_shared_prefix(file.path, p) for p in matches)
    return sorted(p for p in matches if _shared_prefix(file.path, p) == best)


def _shared_prefix(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1], strict=False):
        if x != y:
            break
        count += 1
    return count


def _containers(ctx: Context) -> dict[str, set[str]]:
    """Container name (`Util`, `Util.Inner`) -> files that open it.

    Modules have no node of their own, so a container is read from the qualnames of the
    classes and functions defined inside it, with duplicate-name hashes removed.
    """
    table: dict[str, set[str]] = {}
    for info in ctx.files.values():
        if info.language != LANGUAGE:
            continue
        for node in info.nodes.values():
            if node.kind is NodeKind.CLASS:
                name = node.qualname
            elif node.kind is NodeKind.FUNCTION and "." in node.qualname:
                name = node.qualname.rsplit(".", 1)[0]
            else:
                continue
            table.setdefault(_plain(name), set()).add(info.path)
    return table


def _plain(qualname: str) -> str:
    return ".".join(part.split("#", 1)[0] for part in qualname.split("."))


def _constant(library: str) -> str:
    """`json` -> `JSON`, `set` -> `Set`, `net/http` -> `Http`: a guess at the module name."""
    last = library.rsplit("/", 1)[-1].removesuffix(".rb")
    if last in _ACRONYMS:
        return last.upper()
    return "".join(piece.capitalize() for piece in last.split("_"))
