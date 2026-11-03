"""PHP resolution profile: `use` names map to files through Composer's PSR-4 table."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach, join_relative
from codeatlas.models import NodeKind, RawImport

LANGUAGE = "php"


class PhpProfile(Profile):
    """`use App\\Models\\User;` is the file `<folder>/Models/User.php` for the folder that
    `App\\` maps to in `composer.json` (recorded by T15 as the Package node's
    `autoload_psr4`). If no mapping finds a file, any file that declares that namespace and
    defines that class is used, which also covers repositories without Composer.
    `require`/`include` with a literal path is a file import.
    """

    languages = frozenset({LANGUAGE})
    has_class_chain = True
    type_receivers = True
    unqualified_is_toplevel = True  # `foo()` is a function, never a method
    unqualified_uses_package = True  # functions of the same namespace need no `use`
    self_receivers = frozenset({"$this", "self", "static"})  # `parent::` needs inheritance

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        if _is_path(imp.target):
            return self._include(ctx, file, imp)
        names = [n for n, _ in imp.names] or [""]
        full = imp.target.lstrip("\\") + ("\\" + names[0] if names[0] else "")
        short = full.rsplit("\\", 1)[-1]
        binding = imp.alias or short
        path = self._class_file(ctx, full)
        if path is not None:
            return Reach(imp, (path,), None, binding, short)
        functions = _function_files(ctx, full)  # `use function App\helpers\f;`
        if functions:
            return Reach(imp, tuple(functions), None, None, None, frozenset({short}))
        return Reach(imp, external=full, binding=binding)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        if file.package is None:
            same = ctx.by_directory.get((LANGUAGE, file.directory), [])
        else:
            same = ctx.by_package.get((LANGUAGE, file.package), [])
        return [p for p in same if p != file.path]

    def _include(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        """`require 'a/b.php'` is relative to the including file, then to the repo root."""
        target = imp.target.lstrip("/")
        for directory in (file.directory, ""):
            path = join_relative(directory, target)
            if path is not None and path in ctx.files and path != file.path:
                return Reach(imp, (path,), None, None, None, None)
        return Reach(imp, external=imp.target)

    def _class_file(self, ctx: Context, full: str) -> str | None:
        for prefix, folder in self._psr4(ctx):
            if full.startswith(prefix):
                rest = full[len(prefix) :].replace("\\", "/")
                path = join_relative(folder, rest + ".php")
                if path in ctx.files:
                    return path
        namespace, _, name = full.rpartition("\\")
        for path in ctx.by_package.get((LANGUAGE, namespace), []):
            if name in ctx.files[path].types:
                return path
        return None

    def _psr4(self, ctx: Context) -> list[tuple[str, str]]:
        """(namespace prefix, folder) pairs from every Composer package, longest prefix first."""
        table = ctx.cache.get("php_psr4")
        if table is None:
            table = ctx.cache["php_psr4"] = _psr4_table(ctx)
        return table  # type: ignore[return-value]


def _psr4_table(ctx: Context) -> list[tuple[str, str]]:
    if ctx.index is None:
        return []
    pairs: set[tuple[str, str]] = set()
    seen: set[str] = set()
    for info in ctx.files.values():
        key = info.package_key
        if info.language != LANGUAGE or not key or key in seen:
            continue
        seen.add(key)
        package = ctx.index.by_key(key)
        mapping = package.attrs.get("autoload_psr4") if package is not None else None
        if package is None or package.kind is not NodeKind.PACKAGE or not isinstance(mapping, dict):
            continue
        for prefix, folders in mapping.items():
            for folder in folders if isinstance(folders, list) else []:
                pairs.add((str(prefix), str(folder)))
    return sorted(pairs, key=lambda pair: (-len(pair[0]), pair))


def _is_path(target: str) -> bool:
    """A literal `require`/`include` argument, as opposed to a namespaced `use` name."""
    return "\\" not in target and ("/" in target or target.endswith(".php"))


def _function_files(ctx: Context, full: str) -> list[str]:
    namespace, _, name = full.rpartition("\\")
    return [
        p
        for p in ctx.by_package.get((LANGUAGE, namespace), [])
        if any(f.owner_key is None for f in ctx.files[p].functions.get(name, []))
    ]
