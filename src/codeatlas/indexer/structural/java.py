"""Java resolution profile: imports map to files by package and path, packages are scopes."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import RawImport


class JavaProfile(Profile):
    """`a.b.C` is a file `a/b/C.java` under any source root; `a.b.*` is a folder `a/b`."""

    languages = frozenset({"java"})
    has_class_chain = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        wildcard = any(name == "*" for name, _ in imp.names)
        if wildcard:
            return self._wildcard(ctx, imp)
        return self._single(ctx, imp)

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        if file.package is None:
            return [p for p in ctx.by_directory[("java", file.directory)] if p != file.path]
        return [p for p in ctx.by_package[("java", file.package)] if p != file.path]

    def _single(self, ctx: Context, imp: RawImport) -> Reach:
        """Shorten the name until a file matches: `a.b.C.m` -> `a/b/C.java` member `m`."""
        parts = imp.target.split(".")
        for cut in range(len(parts), 0, -1):
            paths = _class_files(ctx, parts[:cut])
            if paths:
                member = parts[cut] if cut < len(parts) else None
                if member is None:  # `import a.b.C`
                    return Reach(imp, tuple(paths), None, parts[-1], parts[-1])
                if _is_type(ctx, paths, member):  # `import a.b.C.Inner`
                    return Reach(imp, tuple(paths), None, member, member)
                # `import static a.b.C.m` brings the member m, unqualified.
                return Reach(imp, tuple(paths), None, None, parts[cut - 1], frozenset({member}))
        if len(parts) >= 2 and parts[-1][:1].islower() and parts[-2][:1].isupper():
            # `import static org.junit.Assert.assertEquals`: a member of an outside class,
            # used unqualified as `assertEquals(...)`. The import statement does not say
            # "static" in the raw import, but Java naming does: Class.member.
            owner = ".".join(parts[:-1])
            return Reach(imp, external=owner, binding=None, names=frozenset({parts[-1]}))
        return Reach(imp, external=imp.target, binding=parts[-1])

    def _wildcard(self, ctx: Context, imp: RawImport) -> Reach:
        """`a.b.*` reaches a folder; `a.b.C.*` (static) reaches the members of class C."""
        parts = imp.target.split(".")
        class_paths = _class_files(ctx, parts)
        if class_paths:
            return Reach(imp, tuple(class_paths), None, None, parts[-1], None, True)
        paths = _package_files(ctx, imp.target)
        if paths:
            return Reach(imp, tuple(paths), None, None, None, frozenset(), True)
        return Reach(imp, external=f"{imp.target}.*", wildcard=True)


def _class_files(ctx: Context, parts: list[str]) -> list[str]:
    """Files named `<parts[-1]>.java` whose package is `parts[:-1]` (or whose path ends so)."""
    package, name = ".".join(parts[:-1]), parts[-1]
    suffix = "/".join(parts) + ".java"
    found = []
    for path in ctx.by_basename[("java", f"{name}.java")]:
        declared = ctx.files[path].package
        if declared == package or (declared is None and _ends_with(path, suffix)):
            found.append(path)
    return found


def _package_files(ctx: Context, package: str) -> list[str]:
    found = list(ctx.by_package[("java", package)])
    folder = package.replace(".", "/")
    for (language, directory), paths in ctx.by_directory.items():
        if language == "java" and _ends_with(directory, folder):
            found += [p for p in paths if ctx.files[p].package is None]
    return sorted(set(found))


def _is_type(ctx: Context, paths: list[str], member: str | None) -> bool:
    """Whether `member` is a nested type of the class in `paths` (`import a.b.C.Inner`)."""
    return member is not None and any(member in ctx.files[p].types for p in paths)


def _ends_with(path: str, suffix: str) -> bool:
    return path == suffix or path.endswith("/" + suffix)
