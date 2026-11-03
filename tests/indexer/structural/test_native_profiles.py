"""C, C++ and Rust profiles: each import shape, the scopes, and the hand-labelled samples."""

from __future__ import annotations

from pathlib import Path

from codeatlas.indexer.structural.c import CppProfile, CProfile
from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.indexer.structural.resolver import StructuralResolver
from codeatlas.indexer.structural.rust import RustProfile
from codeatlas.models import (
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    RawCall,
    Span,
    Tier,
    make_node_id,
)
from tests.indexer.structural.helpers import SNAPSHOT, parse
from tests.indexer.structural.test_structural_resolver import kind_scores, scored


class Index:
    """Package nodes by key, and the file list (for `CMakeLists.txt`)."""

    def __init__(self, files: dict[str, str], packages: dict[str, Node] | None = None) -> None:
        self.records = [FileRecord(p, "text", Tier.TEXT, "", len(t)) for p, t in files.items()]
        self.packages = packages or {}

    def by_key(self, key: str) -> Node | None:
        return self.packages.get(key)

    def files(self) -> list[FileRecord]:
        return self.records


def cargo(name: str, root: str, library: str | None, entries: list[str]) -> Node:
    key = f"{root}/Cargo.toml::package:{name}"
    attrs: dict[str, object] = {"ecosystem": "cargo", "root": root, "entry_points": entries}
    if library:
        attrs["library"] = library
    return Node(make_node_id(SNAPSHOT, key), key, SNAPSHOT, NodeKind.PACKAGE, "rust", name,
                "", f"{root}/Cargo.toml", Span(1, 1), attrs=attrs)


def context(tmp_path: Path, files: dict[str, str], packages: dict[str, Node] | None = None,
            owner: dict[str, str] | None = None) -> Context:
    """Write the files, parse those with a grammar, and build the resolver's context."""
    results = []
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(text.encode())  # no \r\n on Windows: offsets matter
        if path.rsplit(".", 1)[-1] in ("c", "h", "cpp", "hpp", "rs"):
            result = parse(path, text)
            if owner and path in owner:
                from dataclasses import replace

                module = result.nodes[0]
                attrs = {**module.attrs, "package_key": owner[path]}
                result = replace(result, nodes=(replace(module, attrs=attrs), *result.nodes[1:]))
            results.append(result)
    return Context.build(results, Index(files, packages), tmp_path)  # type: ignore[arg-type]


def reach_of(ctx: Context, profile: Profile, path: str, line: int = 1) -> list[Reach]:
    info = ctx.files[path]
    imp = next(i for i in info.imports if i.line == line)
    return profile.reaches(ctx, info, imp)


# C and C++: includes


C_FILES = {
    "CMakeLists.txt": "target_include_directories(app PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/api)\n",
    "api/geo.h": "double area(double w);\n",
    "lib/geo.c": '#include "geo.h"\ndouble area(double w) { return w; }\n',
    "src/util/log.h": "void log_line(void);\n",
    "src/util/log.c": '#include "log.h"\nvoid log_line(void) {}\n',
    "include/cfg.h": "int cfg(void);\n",
    "deep/only/here.h": "int here(void);\n",
    "src/main.c": (
        '#include "util/log.h"\n#include "geo.h"\n#include <cfg.h>\n#include <stdio.h>\n'
        '#include "here.h"\n#include "missing.h"\n#include "../src/util/log.h"\n'
        "int main(void) { return 0; }\n"
    ),
}


def test_c_include_relative_to_the_file(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    assert reach_of(ctx, CProfile(), "src/main.c", 1)[0].paths == ("src/util/log.h",)
    assert reach_of(ctx, CProfile(), "src/main.c", 7)[0].paths == ("src/util/log.h",)


def test_c_include_through_a_cmake_folder(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    reach = reach_of(ctx, CProfile(), "src/main.c", 2)[0]
    assert reach.paths == ("api/geo.h",)
    assert reach.names is None  # every name of a header is usable unqualified


def test_c_angle_include_found_in_an_include_folder_else_external(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    assert reach_of(ctx, CProfile(), "src/main.c", 3)[0].paths == ("include/cfg.h",)
    assert reach_of(ctx, CProfile(), "src/main.c", 4)[0].external == "stdio.h"


def test_c_quoted_include_falls_back_to_a_unique_suffix_then_external(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    assert reach_of(ctx, CProfile(), "src/main.c", 5)[0].paths == ("deep/only/here.h",)
    assert reach_of(ctx, CProfile(), "src/main.c", 6)[0].external == "missing.h"


def test_c_header_and_source_are_one_scope(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    profile = CProfile()
    assert profile.package_scope(ctx, ctx.files["src/util/log.c"]) == ["src/util/log.h"]
    assert profile.package_scope(ctx, ctx.files["src/util/log.h"]) == ["src/util/log.c"]
    # Not side by side: the only `geo.c` in the repository.
    assert profile.package_scope(ctx, ctx.files["api/geo.h"]) == ["lib/geo.c"]
    assert profile.package_scope(ctx, ctx.files["src/main.c"]) == []


def test_c_prototype_is_swapped_for_its_definition(tmp_path: Path) -> None:
    ctx = context(tmp_path, C_FILES)
    call = RawCall("src/main.c::", "area", "area", None, 8)
    header = ctx.files["api/geo.h"].functions["area"]
    narrowed = CProfile().narrow(ctx, ctx.files["src/main.c"], call, header)
    assert [n.key for n in narrowed] == ["lib/geo.c::area"]


FORWARD = "static int g(int);\nint f(void) { return g(1); }\nstatic int g(int x) { return x; }\n"


def test_c_forward_declaration_in_the_same_file_gives_way(tmp_path: Path) -> None:
    files = {"a.c": FORWARD}
    definition = [n for n in parse("a.c", files["a.c"]).nodes if n.name == "g"][1]
    # The second `g`, the one with a body. The caller is the module: see the explainer.
    assert _resolve(tmp_path, files) == [("a.c::", definition.key, 1.0)]


def test_without_a_checkout_prototypes_cannot_be_told_apart(tmp_path: Path) -> None:
    """No root, no source text: both `g` nodes stay, 0.5 each. Recorded, not hidden."""
    files = {"a.c": FORWARD}
    results = [parse("a.c", files["a.c"])]
    edges = StructuralResolver().resolve(results, Index(files))  # type: ignore[arg-type]
    assert sorted(e.confidence for e in edges if e.kind is EdgeKind.CALLS) == [0.5, 0.5]


# C++: namespaces and classes


CPP_FILES = {
    "m.hpp": (
        "namespace util { inline int half(int x) { return x / 2; } }\n"
        "namespace legacy { inline int half(int x) { return x; } }\n"
        "class C { public: int get() const; static C make(); };\n"
    ),
    "m.cpp": '#include "m.hpp"\nint C::get() const { return 1; }\nC C::make() { return C(); }\n',
    "main.cpp": (
        '#include "m.hpp"\n'
        "int main() { util::half(2); legacy::half(2); C::make(); std::sort(); return 0; }\n"
    ),
}


def test_cpp_namespace_qualifier_picks_one_of_two_same_named_functions(tmp_path: Path) -> None:
    edges = _resolve(tmp_path, CPP_FILES)
    assert ("main.cpp::", "m.hpp::util.half", 1.0) in edges
    assert ("main.cpp::", "m.hpp::legacy.half", 1.0) in edges


def test_cpp_static_method_call_reaches_the_out_of_line_definition(tmp_path: Path) -> None:
    """`C C::make() {...}` is keyed `make` (the adapter does not read `C::`); the profile
    reads the qualifier from the source, so `C::make()` still finds it."""
    edges = _resolve(tmp_path, CPP_FILES)
    assert ("main.cpp::", "m.cpp::make", 1.0) in edges


def test_cpp_qualified_call_outside_the_repository_has_no_edge(tmp_path: Path) -> None:
    edges = _resolve(tmp_path, CPP_FILES)
    assert not [e for e in edges if e[1].endswith("sort")]


def test_cpp_profile_has_a_class_chain_and_c_does_not() -> None:
    assert CppProfile.has_class_chain and not CProfile.has_class_chain


# Rust: use paths


RUST_FILES = {
    "app/src/main.rs": (
        "mod net;\n"
        "use crate::net::Client;\n"
        "use crate::net::{self, tls::{Config, connect as dial}};\n"
        "use std::fs;\n"
        "use shared_util::helpers::*;\n"
        "use serde::Serialize;\n"
        "use crate::Missing;\n"
        "fn main() {}\n"
    ),
    "app/src/net/mod.rs": "pub mod tls;\npub struct Client;\nuse super::*;\n",
    "app/src/net/tls.rs": "pub struct Config;\npub fn connect() {}\nuse super::super::net;\n",
    "shared/src/lib.rs": "pub mod helpers;\npub use helpers::trim;\n",
    "shared/src/helpers.rs": "pub fn trim() {}\n",
    "app/tests/flow.rs": "use shared_util::trim;\nuse crate::x;\n",
}
APP = cargo("app", "app", None, ["app/src/main.rs"])
SHARED = cargo("shared-util", "shared", "shared/src/lib.rs", [])
RUST_OWNERS = {p: (SHARED if p.startswith("shared") else APP).key for p in RUST_FILES}


def rust(tmp_path: Path) -> Context:
    return context(tmp_path, RUST_FILES, {APP.key: APP, SHARED.key: SHARED}, RUST_OWNERS)


def test_rust_mod_declaration_reaches_the_child_file(tmp_path: Path) -> None:
    ctx = rust(tmp_path)
    reach = reach_of(ctx, RustProfile(), "app/src/main.rs", 1)[0]
    assert reach.paths == ("app/src/net/mod.rs",)
    assert reach.binding is None  # a variable named `net` must not hit it
    assert reach_of(ctx, RustProfile(), "app/src/net/mod.rs", 1)[0].paths == ("app/src/net/tls.rs",)


def test_rust_crate_path_to_a_type(tmp_path: Path) -> None:
    reach = reach_of(rust(tmp_path), RustProfile(), "app/src/main.rs", 2)[0]
    assert (reach.paths, reach.binding, reach.class_name) == (
        ("app/src/net/mod.rs",), "Client", "Client",
    )


def test_rust_list_gives_one_reach_per_leaf(tmp_path: Path) -> None:
    reaches = reach_of(rust(tmp_path), RustProfile(), "app/src/main.rs", 3)
    found = [(r.paths, r.binding, r.class_name, r.names) for r in reaches]
    assert found == [
        (("app/src/net/mod.rs",), None, None, frozenset()),  # self
        (("app/src/net/tls.rs",), "Config", "Config", frozenset({"Config"})),
        (("app/src/net/tls.rs",), None, None, frozenset({"connect"})),  # `as dial`: no rename
    ]


def test_rust_outside_paths_are_external(tmp_path: Path) -> None:
    ctx = rust(tmp_path)
    assert reach_of(ctx, RustProfile(), "app/src/main.rs", 4)[0].external == "std::fs"
    serde = reach_of(ctx, RustProfile(), "app/src/main.rs", 6)[0]
    assert (serde.external, serde.binding) == ("serde::Serialize", "Serialize")


def test_rust_workspace_crate_by_name_with_wildcard(tmp_path: Path) -> None:
    reach = reach_of(rust(tmp_path), RustProfile(), "app/src/main.rs", 5)[0]
    assert (reach.paths, reach.names, reach.wildcard) == (("shared/src/helpers.rs",), None, True)


def test_rust_reexport_is_followed(tmp_path: Path) -> None:
    reach = reach_of(rust(tmp_path), RustProfile(), "app/tests/flow.rs", 1)[0]
    assert (reach.paths, reach.names) == (("shared/src/helpers.rs",), frozenset({"trim"}))


def test_rust_unknown_item_stays_in_the_module_reached(tmp_path: Path) -> None:
    reach = reach_of(rust(tmp_path), RustProfile(), "app/src/main.rs", 7)[0]
    assert reach.paths == ("app/src/main.rs",)


def test_rust_super_and_integration_test_crate_root(tmp_path: Path) -> None:
    ctx = rust(tmp_path)
    assert reach_of(ctx, RustProfile(), "app/src/net/mod.rs", 3)[0].paths == ("app/src/main.rs",)
    tls = reach_of(ctx, RustProfile(), "app/src/net/tls.rs", 3)[0]
    assert tls.paths == ("app/src/net/mod.rs",)
    # A file in tests/ is its own crate root: `crate::x` is an item of that file.
    assert reach_of(ctx, RustProfile(), "app/tests/flow.rs", 2)[0].paths == ("app/tests/flow.rs",)


def test_rust_qualify_paths_written_in_calls(tmp_path: Path) -> None:
    ctx = rust(tmp_path)
    main = ctx.files["app/src/main.rs"]
    profile = RustProfile()

    def qualify(callee: str) -> Reach:
        receiver, _, name = callee.rpartition("::")
        call = RawCall("app/src/main.rs::main", callee, name, receiver, 8)
        found = profile.qualify(ctx, main, call)
        assert found is not None
        return found

    assert qualify("net::tls::connect").paths == ("app/src/net/tls.rs",)
    assert qualify("crate::net::Client::new").class_name == "Client"
    assert qualify("fs::read").external == "std::fs"
    assert qualify("Vec::new").external == "Vec"
    assert qualify("regex::Regex::new").external == "regex::Regex"
    unknown = RawCall("app/src/main.rs::main", "Unknown::new", "new", "Unknown", 8)
    assert profile.qualify(ctx, main, unknown) is None  # a type from a glob import: scopes decide
    method = RawCall("app/src/main.rs::main", "Client::new().go", "go", "Client::new()", 8)
    assert profile.qualify(ctx, main, method) is None


def test_rust_self_in_an_impl(tmp_path: Path) -> None:
    files = {
        "a.rs": "struct P;\nimpl P {\n fn new() -> P { P }\n"
        " fn m(&self) { self.n(); Self::new(); }\n fn n(&self) {}\n}\nfn n() {}\n"
    }
    edges = _resolve(tmp_path, files)
    assert ("a.rs::P.m", "a.rs::P.n", 1.0) in edges  # not the free function `n`
    assert ("a.rs::P.m", "a.rs::P.new", 1.0) in edges


# Samples scored against hand labels


def test_c_sample_matches_the_hand_labels_exactly() -> None:
    result = scored("c")
    for kind in ("calls", "imports"):
        assert kind_scores(result, kind)["precision"] == 1.0
        assert kind_scores(result, kind)["recall"] == 1.0


def test_cpp_sample_matches_the_hand_labels_exactly() -> None:
    result = scored("cpp")
    for kind in ("calls", "imports"):
        assert kind_scores(result, kind)["precision"] == 1.0
        assert kind_scores(result, kind)["recall"] == 1.0


def test_rust_sample_finds_every_labelled_edge() -> None:
    result = scored("rust")
    assert kind_scores(result, "calls")["precision"] == 1.0
    assert kind_scores(result, "calls")["recall"] == 1.0
    assert kind_scores(result, "imports")["recall"] == 1.0
    # The one wrong edge: `use super::*` inside `mod tests { }` of store/mod.rs means the
    # file itself, but a RawImport does not say it sits in an inline module, so it
    # resolves to the parent module, main.rs.
    assert kind_scores(result, "imports")["fp"] == 1


def _resolve(tmp_path: Path, files: dict[str, str]) -> list[tuple[str, str, float]]:
    results = []
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(text.encode())  # no \r\n on Windows: offsets matter
        results.append(parse(path, text))
    resolver = StructuralResolver()
    resolver.set_repo_root(tmp_path)
    edges = resolver.resolve(results, Index(files))  # type: ignore[arg-type]
    return [
        (e.src_id.split("/", 1)[1], e.dst_id.split("/", 1)[1], e.confidence)
        for e in edges
        if e.kind is EdgeKind.CALLS
    ]
