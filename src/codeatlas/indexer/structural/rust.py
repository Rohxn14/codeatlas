"""Rust resolution profile: `use` paths walk the module tree from a crate root.

A Rust module is a file (`a.rs` or `a/mod.rs`) declared by `mod a;` in its parent. A path
`crate::a::b::C` starts at the crate root (`src/lib.rs`, `src/main.rs`, a `src/bin` file,
from T15's Cargo packages), descends through module files while the segments name child
modules, and the first segment left over is an item of the last module reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import Node, NodeKind, RawCall, RawImport

MAX_REEXPORT_HOPS = 5
_OWN_ROOT_FOLDERS = ("tests", "examples", "benches")  # each file there is its own crate
# Prelude types and variants: in scope everywhere without a `use`, and never in the repo.
_PRELUDE = frozenset({
    "Vec", "String", "Box", "Option", "Some", "None", "Result", "Ok", "Err", "ToString",
    "ToOwned", "Default", "Iterator", "IntoIterator", "From", "Into", "Clone", "Drop",
})


@dataclass(frozen=True, slots=True)
class _Leaf:
    """One name a `use` statement brings in: its full path and the name used in code."""

    path: tuple[str, ...]
    alias: str | None = None
    wildcard: bool = False

    @property
    def name(self) -> str:
        return self.alias or self.path[-1]


class RustProfile(Profile):
    """Scope is the file; everything else needs a path, written in a `use` or the call.

    Only types and outside names get a `binding` (`C::new()`, `HashMap::new()`); module
    paths are walked by `qualify`, so a variable named like a module is never mistaken
    for it.
    """

    languages = frozenset({"rust"})
    unqualified_is_toplevel = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        reaches = self.reaches(ctx, file, imp)
        return reaches[0] if reaches else Reach(imp, external=imp.target)

    def reaches(self, ctx: Context, file: FileInfo, imp: RawImport) -> list[Reach]:
        if imp.alias == "mod":
            child = _child(ctx, file.path, imp.target)
            return [Reach(imp, (child,) if child else ())]
        return [_leaf_reach(ctx, file, imp, leaf, 0) for leaf in _leaves(imp)]

    def qualify(self, ctx: Context, file: FileInfo, call: RawCall) -> Reach | None:
        """`a::b::f()`, `Self::new()`, `self.m()`: the path is in the call itself."""
        receiver = call.receiver or ""
        imp = RawImport(file.module.key, receiver, line=call.line)
        if receiver == "self" and call.callee_text.startswith("self."):
            owner = _impl_type(file, call.caller_key)
            return Reach(imp, (file.path,), class_name=owner) if owner else None
        if not call.callee_text.endswith("::" + call.name):
            return None  # a method call: `x.f()`, `C::new().f()`
        segments = tuple(s.strip() for s in receiver.split("::"))
        first = segments[0]
        if first == "Self":
            owner = _impl_type(file, call.caller_key)
            if owner and len(segments) == 1:
                return Reach(imp, (file.path,), class_name=owner)
            return None
        bound = _bindings(ctx, file).get(first)
        if bound is not None:
            return _path_reach(ctx, file, imp, bound.path + segments[1:])
        if len(segments) == 1 and first in file.types:
            return Reach(imp, (file.path,), class_name=first)
        if first in _PRELUDE:
            return Reach(imp, external=receiver)
        return _path_reach(ctx, file, imp, segments, unknown_is_external=first.islower())


# Expanding a `use` statement into leaves


def _leaves(imp: RawImport) -> list[_Leaf]:
    base = tuple(s.strip() for s in imp.target.split("::"))
    if not imp.names:
        return [_Leaf(base, imp.alias)]
    leaves: list[_Leaf] = []
    for name, _ in imp.names:
        leaves += _expand(base, name)
    return leaves


def _expand(base: tuple[str, ...], text: str) -> list[_Leaf]:
    """One item of a `{...}` list: `self`, `C`, `c::D as E`, `*`, or `q::{R, S}`."""
    text = " ".join(text.split())
    if text == "*":
        return [_Leaf(base, wildcard=True)]
    if text == "self":
        return [_Leaf(base)]
    if "{" in text:
        prefix, _, inner = text.partition("{")
        nested = base + tuple(s.strip() for s in prefix.rstrip(": ").split("::") if s.strip())
        leaves: list[_Leaf] = []
        for part in _split_top_level(inner.rsplit("}", 1)[0]):
            leaves += _expand(nested, part)
        return leaves
    path, _, alias = text.partition(" as ")
    segments = tuple(s.strip() for s in path.split("::"))
    if segments[-1] == "*":
        return [_Leaf(base + segments[:-1], wildcard=True)]
    return [_Leaf(base + segments, alias.strip() or None)]


def _split_top_level(text: str) -> list[str]:
    """`R, s::{T, U}` -> [`R`, `s::{T, U}`]: commas inside braces stay."""
    parts, depth, current = [], 0, ""
    for char in text:
        depth += char == "{"
        depth -= char == "}"
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _bindings(ctx: Context, file: FileInfo) -> dict[str, _Leaf]:
    """Name used in code -> the `use` leaf it came from, for qualifiers like `a::B::new()`."""
    table = ctx.cache.setdefault("rust_bindings", {})
    assert isinstance(table, dict)
    if file.path not in table:
        found: dict[str, _Leaf] = {}
        for imp in file.imports:
            if imp.alias == "mod":
                continue
            for leaf in _leaves(imp):
                if not leaf.wildcard and leaf.name not in ("self", "super", "crate"):
                    found[leaf.name] = leaf
        table[file.path] = found
    return table[file.path]


# Leaves and paths to reaches


def _leaf_reach(ctx: Context, file: FileInfo, imp: RawImport, leaf: _Leaf, hops: int) -> Reach:
    walked = _walk(ctx, file, leaf.path)
    if walked is None:
        external = "::".join(leaf.path)
        if leaf.wildcard:
            return Reach(imp, external=f"{external}::*", wildcard=True)
        return Reach(imp, external=external, binding=leaf.name)
    module, rest = walked
    if leaf.wildcard:
        names = None if not rest else frozenset()
        return Reach(imp, (module,), names=names, wildcard=True)
    if not rest:
        # No binding for a module: `store.add()` on a variable named like `mod store`
        # would hit it. `store::f()` is a path, and `qualify` walks it.
        return Reach(imp, (module,))
    return _item_reach(ctx, imp, module, rest[0], leaf.name, hops)


def _item_reach(
    ctx: Context, imp: RawImport, module: str, item: str, name: str, hops: int
) -> Reach:
    """An item of a module file: a type (qualifier for `C::new()`), a function, or a
    re-export (`pub use`) of either, followed a few hops."""
    info = ctx.files.get(module)
    if info is not None and item in info.types:
        return Reach(imp, (module,), binding=name, class_name=item, names=frozenset({name}))
    if info is not None and any(_is_toplevel(n) for n in info.functions.get(item, [])):
        return Reach(imp, (module,), names=frozenset({item}))
    if info is not None and hops < MAX_REEXPORT_HOPS:
        followed = _reexport(ctx, info, imp, item, name, hops + 1)
        if followed is not None:
            return followed
    return Reach(imp, (module,), binding=name, names=frozenset({item}))


def _reexport(
    ctx: Context, info: FileInfo, imp: RawImport, item: str, name: str, hops: int
) -> Reach | None:
    """`pub use shapes::Circle;` in lib.rs: `use crate::Circle` means shapes' Circle."""
    for own in info.imports:
        if own.alias == "mod":
            continue
        for leaf in _leaves(own):
            if leaf.wildcard or leaf.name != item:
                continue
            walked = _walk(ctx, info, leaf.path)
            if walked is None:
                return Reach(imp, external="::".join(leaf.path), binding=name)
            module, rest = walked
            if rest:
                return _item_reach(ctx, imp, module, rest[0], name, hops)
    for own in info.imports:  # `pub use shapes::*;`
        for leaf in _leaves(own) if own.alias != "mod" else []:
            walked = _walk(ctx, info, leaf.path) if leaf.wildcard else None
            if walked is not None and not walked[1]:
                target = ctx.files.get(walked[0])
                if target is not None and (item in target.types or item in target.functions):
                    return _item_reach(ctx, imp, walked[0], item, name, hops)
    return None


def _path_reach(
    ctx: Context,
    file: FileInfo,
    imp: RawImport,
    segments: tuple[str, ...],
    unknown_is_external: bool = True,
) -> Reach | None:
    """A qualifier written in a call: a module (`util::f()`) or a type (`a::C::new()`)."""
    walked = _walk(ctx, file, segments)
    if walked is None:
        return Reach(imp, external="::".join(segments)) if unknown_is_external else None
    module, rest = walked
    if not rest:
        return Reach(imp, (module,))
    if len(rest) == 1:
        return Reach(imp, (module,), class_name=rest[0])
    return None


def _walk(
    ctx: Context, file: FileInfo, segments: tuple[str, ...]
) -> tuple[str, tuple[str, ...]] | None:
    """(module file reached, segments left over), or None when the path leaves the repo."""
    first, rest = segments[0], segments[1:]
    if first == "crate":
        current = _crate_root(ctx, file.path)
    elif first == "self":
        current = file.path
    elif first == "super":
        current = _parent_module(ctx, file.path)
        while current is not None and rest and rest[0] == "super":
            current, rest = _parent_module(ctx, current), rest[1:]
    else:
        current = _child(ctx, file.path, first) or _crates(ctx).get(_normalise(first))
    if current is None:
        return None
    while rest:
        child = _child(ctx, current, rest[0])
        if child is None:
            break
        current, rest = child, rest[1:]
    return current, rest


# The module tree


def _module_dir(ctx: Context, path: str) -> str:
    """Where a module's children live: beside lib.rs/main.rs/mod.rs, else in `a/` for a.rs."""
    pure = PurePosixPath(path)
    parent = "" if str(pure.parent) == "." else str(pure.parent)
    if pure.name == "mod.rs" or _crate_root(ctx, path) == path:
        return parent
    return f"{parent}/{pure.stem}" if parent else pure.stem


def _child(ctx: Context, path: str, name: str) -> str | None:
    directory = _module_dir(ctx, path)
    for candidate in (f"{name}.rs", f"{name}/mod.rs"):
        full = f"{directory}/{candidate}" if directory else candidate
        if full in ctx.files:
            return full
    return None


def _parent_module(ctx: Context, path: str) -> str | None:
    """`super`: the file whose module folder holds this file's module."""
    if _crate_root(ctx, path) == path:
        return None
    own = _module_dir(ctx, path)
    above = own.rsplit("/", 1)[0] if "/" in own else ""
    root = _crate_root(ctx, path)
    if root is not None and _module_dir(ctx, root) == above:
        return root
    for candidate in (f"{above}/mod.rs" if above else "mod.rs", f"{above}.rs"):
        if candidate in ctx.files:
            return candidate
    return None


def _crate_root(ctx: Context, path: str) -> str | None:
    """The root file of the crate a file belongs to: the deepest root whose folder holds
    it (a library wins a tie with `main.rs`); files under `tests/` are roots themselves."""
    roots = _roots(ctx)
    if path in roots:
        return path
    parts = PurePosixPath(path).parts
    if len(parts) >= 2 and parts[-2] in _OWN_ROOT_FOLDERS:
        return path
    best: tuple[int, int, str] | None = None
    for root, is_library in roots.items():
        folder = str(PurePosixPath(root).parent)
        folder = "" if folder == "." else folder
        if folder and not path.startswith(folder + "/"):
            continue
        rank = (len(folder), int(is_library), root)
        if best is None or rank[:2] > best[:2]:
            best = rank
    return best[2] if best else None


def _roots(ctx: Context) -> dict[str, bool]:
    """Every crate root file -> whether it is a library root."""
    cached = ctx.cache.get("rust_roots")
    if cached is None:
        cached = ctx.cache["rust_roots"] = _find_roots(ctx)
    return cached  # type: ignore[return-value]


def _find_roots(ctx: Context) -> dict[str, bool]:
    """From the Cargo Package nodes (T15); without them, every lib.rs and main.rs."""
    roots: dict[str, bool] = {}
    for package in _packages(ctx):
        library = package.attrs.get("library")
        if isinstance(library, str) and library in ctx.files:
            roots[library] = True
        entries = package.attrs.get("entry_points")
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, str) and entry in ctx.files:
                roots.setdefault(entry, False)
    if not roots:
        for path, info in ctx.files.items():
            name = PurePosixPath(path).name
            if info.language == "rust" and name in ("lib.rs", "main.rs"):
                roots[path] = name == "lib.rs"
    return roots


def _crates(ctx: Context) -> dict[str, str]:
    """Workspace crate name (`-` and `_` equal) -> its library root file."""
    cached = ctx.cache.get("rust_crates")
    if cached is None:
        cached = {}
        for package in _packages(ctx):
            library = package.attrs.get("library")
            if isinstance(library, str) and library in ctx.files:
                cached[_normalise(package.name)] = library
        ctx.cache["rust_crates"] = cached
    return cached  # type: ignore[return-value]


def _packages(ctx: Context) -> list[Node]:
    if ctx.index is None:
        return []
    found: dict[str, Node] = {}
    for info in ctx.files.values():
        key = info.package_key
        if info.language != "rust" or not key or key in found:
            continue
        package = ctx.index.by_key(key)
        if (
            package is not None
            and package.kind is NodeKind.PACKAGE
            and package.attrs.get("ecosystem") == "cargo"
        ):
            found[key] = package
    return list(found.values())


def _normalise(name: str) -> str:
    return name.replace("-", "_").lower()


def _impl_type(file: FileInfo, caller_key: str) -> str | None:
    """`Self` inside `impl C { fn f() { ... } }` is C."""
    caller = file.nodes.get(caller_key)
    if caller is None:
        return None
    receiver = caller.attrs.get("receiver")
    if isinstance(receiver, str):
        return receiver
    owner = file.nodes.get(caller.owner_key or "")
    return owner.name if owner is not None else None


def _is_toplevel(node: Node) -> bool:
    return node.owner_key is None and "receiver" not in node.attrs
