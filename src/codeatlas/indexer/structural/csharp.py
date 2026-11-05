"""C# resolution profile: a `using` names a namespace, and a namespace is a set of files."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import Node, RawCall, RawImport

LANGUAGE = "c_sharp"


class CSharpProfile(Profile):
    """Files belong to the namespaces they declare (`attrs["packages"]`), not to a folder.

    `using A.B;` reaches every file declaring namespace `A.B`; `using static A.B.C;`
    reaches only the members of class `C`; `using X = A.B.C;` names the class `X`. Names
    that match no namespace of the repository (`System.IO`) are external. A file with two
    namespaces (`namespace A {}` then `namespace B {}`) is reached by either.
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

    def narrow(self, ctx: Context, file: FileInfo, call: RawCall, nodes: list[Node]) -> list[Node]:
        """One candidate per node: `using A;` and `using B;` can both reach a file that
        declares `A` and `B`, and the shared resolver lists that file once per import."""
        return list({n.key: n for n in nodes}.values())

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        """Other files sharing any of its namespaces; none for a file outside any."""
        found: list[str] = []
        for namespace in _declared(file):
            found += [p for p in _namespace_files(ctx, namespace) if p != file.path]
        return list(dict.fromkeys(found))


def _declared(file: FileInfo) -> list[str]:
    """Every namespace the file declares; `attrs["package"]` alone for older parses."""
    packages = file.module.attrs.get("packages")
    if isinstance(packages, list) and packages:
        return [p for p in packages if isinstance(p, str) and p]
    return [file.package] if file.package else []


def _namespace_files(ctx: Context, namespace: str) -> list[str]:
    return list(_by_namespace(ctx).get(namespace, []))


def _by_namespace(ctx: Context) -> dict[str, list[str]]:
    """Namespace -> files declaring it, built once per run. The context's `by_package`
    table holds only each file's first namespace."""
    table = ctx.cache.get("c_sharp_namespaces")
    if table is None:
        built: dict[str, list[str]] = {}
        for path, info in ctx.files.items():
            if info.language == LANGUAGE:
                for namespace in _declared(info):
                    built.setdefault(namespace, []).append(path)
        table = ctx.cache["c_sharp_namespaces"] = built
    return table  # type: ignore[return-value]


def _class_files(ctx: Context, namespace: str, class_name: str) -> list[str]:
    """Files of `namespace` that define a type called `class_name`."""
    if not namespace:
        return []
    return [p for p in _namespace_files(ctx, namespace) if class_name in ctx.files[p].types]
