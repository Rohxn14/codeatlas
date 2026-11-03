"""The Java and Go imports queries on small snippets."""

from codeatlas.models import RawImport
from tests.indexer.structural.helpers import parse


def imports(path: str, source: str) -> list[RawImport]:
    return list(parse(path, source).imports)


def test_java_plain_wildcard_and_static_imports() -> None:
    result = parse(
        "A.java",
        "package a.b;\n"
        "import x.y.C;\n"
        "import x.y.*;\n"
        "import static x.y.C.m;\n"
        "import static x.y.C.*;\n"
        "class A {}\n",
    )
    found = [(i.target, i.names, i.line) for i in result.imports]
    assert found == [
        ("x.y.C", (), 2),
        ("x.y", (("*", None),), 3),
        ("x.y.C.m", (), 4),
        ("x.y.C", (("*", None),), 5),
    ]
    assert result.nodes[0].attrs["package"] == "a.b"
    assert all(i.module_key == "A.java::" for i in result.imports)


def test_java_file_without_package_or_imports() -> None:
    result = parse("A.java", "class A {}\n")
    assert result.imports == ()
    assert "package" not in result.nodes[0].attrs


def test_go_single_grouped_alias_dot_and_blank_imports() -> None:
    result = parse(
        "main.go",
        'package main\n\nimport "fmt"\n\nimport (\n\tf "os"\n\t. "a/b"\n\t_ "c/d"\n\t"e/f"\n)\n'
        "import `g/h`\n",
    )
    found = [(i.target, i.alias) for i in result.imports]
    assert found == [
        ("fmt", None),
        ("os", "f"),
        ("a/b", "."),
        ("c/d", "_"),
        ("e/f", None),
        ("g/h", None),
    ]
    assert result.nodes[0].attrs["package"] == "main"


def test_a_language_without_an_imports_query_has_no_imports() -> None:
    result = parse("a.lua", "local json = require('json')\nfunction a() end\n")
    assert result.imports == ()


def test_c_quoted_and_angle_includes() -> None:
    source = '#include "x.h"\n#include "../y/z.h"\n#include <sys/stat.h>\nint f(void);\n'
    found = imports("a.c", source)
    assert [(i.target, i.line) for i in found] == [
        ("x.h", 1), ("../y/z.h", 2), ("<sys/stat.h>", 3),  # brackets kept: the only marker
    ]


def test_cpp_includes_and_a_file_without_any() -> None:
    assert [i.target for i in imports("a.cpp", '#include <vector>\n#include "a/b.hpp"\n')] == [
        "<vector>", "a/b.hpp",
    ]
    assert imports("b.cpp", "int main() { return 0; }\n") == []


def test_cpp_calls_and_namespace_scopes_from_extra_query() -> None:
    result = parse(
        "a.cpp",
        "namespace ns { int f() { return 1; } }\n"
        "int main() { ns::f(); a::B::make(); g<int>(); obj.m(); p->q(); return h(); }\n",
    )
    assert "a.cpp::ns.f" in {n.key for n in result.nodes}
    found = {(c.name, c.receiver) for c in result.calls}
    assert found == {
        ("f", "ns"), ("make", "a::B"), ("g", None), ("m", "obj"), ("q", "p"), ("h", None)
    }


def test_c_calls_from_extra_query() -> None:
    result = parse("a.c", "int main(void) { s.f(); p->g(); return h(); }\n")
    assert {(c.name, c.receiver) for c in result.calls} == {("f", "s"), ("g", "p"), ("h", None)}


def test_rust_use_shapes_mod_and_extern_crate() -> None:
    result = parse(
        "a.rs",
        "use crate::a::b::C;\n"
        "use std::collections::HashMap as Map;\n"
        "use super::x::{self, Y, z::W as V, q::{R, S}};\n"
        "use self::m::*;\n"
        "pub use serde;\n"
        "mod child;\n"
        "mod inline { fn f() {} }\n"
        "extern crate foo;\n",
    )
    found = [(i.target, i.names, i.alias) for i in result.imports]
    assert found == [
        ("crate::a::b::C", (), None),
        ("std::collections::HashMap", (), "Map"),
        ("super::x", (("self", None), ("Y", None), ("z::W as V", None), ("q::{R, S}", None)), None),
        ("self::m", (("*", None),), None),
        ("serde", (), None),
        ("child", (), "mod"),  # `mod child;`, not the inline `mod inline { }`
        ("foo", (), None),
    ]


def test_rust_file_without_imports() -> None:
    assert imports("a.rs", "fn main() {}\n") == []
