"""What a language must say for import-scoped resolution: two small questions.

A profile answers (1) which files an import statement reaches, and (2) which other files
a file can call into without importing them (its package scope). The resolver does the
rest identically for every language. See `.claude/skills/add-language/SKILL.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.models import Node, RawCall, RawImport


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

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        return Reach(imp, external=imp.target)

    def reaches(self, ctx: Context, file: FileInfo, imp: RawImport) -> list[Reach]:
        """Every `Reach` of one statement; Rust `use a::{B, c::D}` has one per name."""
        return [self.reach(ctx, file, imp)]

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        """Other files that `file` can use without importing them."""
        return []

    def qualify(self, ctx: Context, file: FileInfo, call: RawCall) -> Reach | None:
        """Where a written qualifier that is not an import binding points.

        Rust `crate::util::f()` or `Self::new()` name their target in the call itself.
        None: the resolver carries on with its scopes.
        """
        return None

    def narrow(self, ctx: Context, file: FileInfo, call: RawCall, nodes: list[Node]) -> list[Node]:
        """Drop candidates the language rules out, or swap them for better ones.

        C++ `ns::f()` cannot be `other::f`; a C prototype stands for its definition.
        """
        return nodes
