"""What a language must say for import-scoped resolution: two small questions.

A profile answers (1) which files an import statement reaches, and (2) which other files
a file can call into without importing them (its package scope). The resolver does the
rest identically for every language. See `.claude/skills/add-language/SKILL.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.models import RawImport


@dataclass(frozen=True, slots=True)
class Reach:
    """What one import brings into a file."""

    imp: RawImport
    paths: tuple[str, ...] = ()  # repository files it reaches
    external: str | None = None  # set instead of `paths` when the target is outside the repo
    binding: str | None = None  # the qualifier that names it in code: `fmt` in `fmt.Println`
    class_name: str | None = None  # only members of this class are reached (Java)
    names: frozenset[str] | None = frozenset()  # names usable unqualified; None = all
    wildcard: bool = False  # the import reaches every file of a package (a `*`)


class Profile:
    """Base class; a language overrides `reach` and `package_scope`."""

    languages: ClassVar[frozenset[str]] = frozenset()
    # Go: `F()` with no qualifier can only be a package-level function, never a method.
    unqualified_is_toplevel: ClassVar[bool] = False
    # Go: an unqualified call may reach any file of the package; Java: only its class chain.
    unqualified_uses_package: ClassVar[bool] = False
    # Java: `m()` and `this.m()` look in the enclosing classes first.
    has_class_chain: ClassVar[bool] = False
    # C#, PHP, Ruby: `Foo.bar()` where `Foo` is a class in scope (own file, package scope or
    # an imported file) looks only at the methods of `Foo`, with no import binding needed.
    type_receivers: ClassVar[bool] = False
    # Receivers that mean "the current object or class": Java `this`, PHP `$this`/`self`.
    self_receivers: ClassVar[frozenset[str]] = frozenset({"this", "self", "super"})

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        return Reach(imp, external=imp.target)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        """Other files that `file` can use without importing them."""
        return []


def join_relative(directory: str, relative: str) -> str | None:
    """`directory/relative` with `.` and `..` folded away; None if it climbs out of the repo.

    Shared by the profiles whose imports are file paths (PHP `require`, Ruby
    `require_relative`). Pure string work on forward slashes, so it behaves the same on
    Windows and Linux.
    """
    parts = [p for p in directory.split("/") if p]
    for piece in relative.split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(piece)
    return "/".join(parts)
