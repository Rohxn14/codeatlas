"""C# resolution profile: a `using` names a namespace, and a namespace is a set of files."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import RawImport

LANGUAGE = "c_sharp"


class CSharpProfile(Profile):
    """Files belong to the namespace they declare (`attrs["package"]`), not to a folder.

    `using A.B;` reaches every file declaring namespace `A.B`; `using static A.B.C;`
    reaches only the members of class `C`; `using X = A.B.C;` names the class `X`. Names
    that match no namespace of the repository (`System.IO`) are external.
    """

    languages = frozenset({LANGUAGE})
    has_class_chain = True
    type_receivers = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        namespace, _, class_name = imp.target.rpartition(".")
        class_files = _class_files(ctx, namespace, class_name)
        if imp.alias:  # `using X = A.B.C;` (a class) or `using X = A.B;` (a namespace)
            if class_files:
                return Reach(imp, tuple(class_files), None, imp.alias, class_name)
            files = _namespace_files(ctx, imp.target)
            if files:
                return Reach(imp, tuple(files), None, imp.alias, None, frozenset(), True)
            return Reach(imp, external=imp.target, binding=imp.alias)
        files = _namespace_files(ctx, imp.target)
        if files:  # `using A.B;`
            return Reach(imp, tuple(files), None, None, None, frozenset(), True)
        if class_files:  # `using static A.B.C;`: members of C, unqualified
            return Reach(imp, tuple(class_files), None, None, class_name, None)
        return Reach(imp, external=imp.target)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        """Other files of the same namespace; none for a file outside any namespace."""
        if file.package is None:
            return []
        return [p for p in ctx.by_package.get((LANGUAGE, file.package), []) if p != file.path]


def _namespace_files(ctx: Context, namespace: str) -> list[str]:
    return list(ctx.by_package.get((LANGUAGE, namespace), []))


def _class_files(ctx: Context, namespace: str, class_name: str) -> list[str]:
    """Files of `namespace` that define a type called `class_name`."""
    if not namespace:
        return []
    return [p for p in _namespace_files(ctx, namespace) if class_name in ctx.files[p].types]
