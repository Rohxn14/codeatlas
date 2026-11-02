"""What each file's imports bind, and the IMPORTS edges they produce."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from codeatlas.indexer.languages.typescript.resolver.modules import ModuleResolver
from codeatlas.indexer.languages.typescript.resolver.tables import Exports, FileInfo, Found
from codeatlas.models import RawImport

EXTERNAL_PREFIX = "::external:"
AddImport = Callable[[str, str, int], None]  # (source key, target key, line)


@dataclass(frozen=True, slots=True)
class Binding:
    """A local name bound by an import.

    kind: `symbol` (target is a node key), `module` (a variable: target is a file path),
    `namespace` (`import * as ns` or `require`: a file path) or `external` (target is the
    specifier, `name` the imported name, None for a whole-package import).
    """

    kind: str
    target: str
    name: str | None = None


@dataclass(slots=True)
class FileContext:
    info: FileInfo
    bindings: dict[str, Binding] = field(default_factory=dict)
    imported_files: set[str] = field(default_factory=set)


def build_context(
    info: FileInfo, modules: ModuleResolver, exports: Exports, add: AddImport
) -> FileContext:
    ctx = FileContext(info)
    for raw in info.imports:
        target = modules.resolve(raw.target, info.path)
        if target.path is not None:
            _internal(ctx, raw, target.path, exports, add)
        elif target.external is not None:
            _external(ctx, raw, target.external, add)
    return ctx


def _internal(ctx: FileContext, raw: RawImport, path: str, exports: Exports, add: AddImport) -> None:
    source, module = ctx.info.module_key, f"{path}::"
    ctx.imported_files.add(path)
    if raw.is_reexport:
        _reexport(ctx, raw, path, exports, add)
        return
    for original, alias in raw.names:
        found = exports.lookup(path, original)
        if found is None:
            ctx.bindings[alias or original] = Binding("module", path)
            add(source, module, raw.line)
            continue
        ctx.imported_files.add(found.path)
        kind = "module" if found.is_module else "symbol"
        ctx.bindings[alias or original] = Binding(kind, found.path if found.is_module else found.key)
        add(source, found.key, raw.line)
    if raw.alias is not None:
        ctx.bindings[raw.alias] = Binding("namespace", path)
        ctx.imported_files.update(f.path for f in exports.symbols(path).values())
    if not raw.names:
        add(source, module, raw.line)


def _reexport(ctx: FileContext, raw: RawImport, path: str, exports: Exports, add: AddImport) -> None:
    """The barrel gets an IMPORTS edge to each symbol it re-exports (the real definition)."""
    source, module = ctx.info.module_key, f"{path}::"
    hits: list[Found] = []
    if raw.names:
        for original, _alias in raw.names:
            found = exports.lookup(path, original)
            hits.append(found if found is not None else Found(module, is_module=True))
    elif raw.alias is None:
        hits = list(exports.symbols(path).values())
    for found in hits:
        ctx.imported_files.add(found.path)
        add(source, found.key, raw.line)
    if raw.alias is not None or not hits:
        add(source, module, raw.line)


def _external(ctx: FileContext, raw: RawImport, specifier: str, add: AddImport) -> None:
    add(ctx.info.module_key, EXTERNAL_PREFIX + specifier, raw.line)
    for original, alias in raw.names:
        ctx.bindings[alias or original] = Binding("external", specifier, original)
    if raw.alias is not None:
        ctx.bindings[raw.alias] = Binding("external", specifier, None)
