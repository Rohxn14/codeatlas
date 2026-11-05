"""T21: a C/C++ function's node spans its body, and C# files record every namespace."""

from __future__ import annotations

import hashlib
from pathlib import Path

from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.csharp import CSharpProfile
from codeatlas.models import NodeKind, Resolution
from tests.indexer.structural.helpers import parse
from tests.indexer.structural.test_native_profiles import _resolve
from tests.indexer.structural.test_structural_resolver import calls, resolve

BRIEF = "static int h(void){return 0;} int f(void){ return h(); } int g(void){ return h(); }\n"


def functions(path: str, source: str) -> dict[str, tuple[int, int]]:
    """Function key -> (start line, end line)."""
    result = parse(path, source)
    return {
        n.key: (n.span.start_line, n.span.end_line)
        for n in result.nodes
        if n.kind is NodeKind.FUNCTION
    }


# C and C++: callers


def test_calls_inside_a_c_function_name_that_function_as_caller() -> None:
    result = parse("a.c", BRIEF)
    assert [(c.caller_key, c.name) for c in result.calls] == [("a.c::f", "h"), ("a.c::g", "h")]
    assert calls(resolve({"a.c": BRIEF})) == [
        ("a.c::f", "a.c::h", 1.0, Resolution.IMPORT_SCOPED),
        ("a.c::g", "a.c::h", 1.0, Resolution.IMPORT_SCOPED),
    ]


def test_one_node_per_function_spanning_its_body() -> None:
    source = "int f(void)\n{\n    return 0;\n}\nint *p(int n) {\n    return 0;\n}\n"
    assert functions("a.c", source) == {"a.c::f": (1, 4), "a.c::p": (5, 7)}


def test_declarations_without_a_body_keep_the_declarator() -> None:
    source = "int f(void);\nstruct S {\n  S() = default;\n  void m();\n};\n"
    result = parse("a.cpp", source)
    spans = {n.key: n.span for n in result.nodes if n.kind is NodeKind.FUNCTION}
    assert spans["a.cpp::f"].start_col == 4  # `f(void)`, not `int f(void);`
    assert spans["a.cpp::S.S"].start_col == 2
    assert spans["a.cpp::S.m"].start_col == 7


def test_a_function_declarator_in_a_parameter_is_not_the_definition() -> None:
    source = "int apply(int op(int), int x) {\n  return op(x);\n}\n"
    found = functions("a.c", source)
    assert found["a.c::apply"] == (1, 3)
    assert parse("a.c", source).calls[0].caller_key == "a.c::apply"


def test_keys_and_signatures_stay_those_of_the_declarator() -> None:
    """The `#hash` suffix of a repeated name is computed from the declarator text."""
    source = "static double sq(double x);\nstatic double sq(double x) { return x * x; }\n"
    result = parse("a.c", source)
    found = [(n.key, n.signature) for n in result.nodes if n.kind is NodeKind.FUNCTION]
    digest = hashlib.sha1(b"sq(double x)", usedforsecurity=False).hexdigest()[:4]
    assert found == [(f"a.c::sq#{digest}", "sq(double x)"), (f"a.c::sq#{digest}-2", "sq(double x)")]


def test_a_comment_above_a_c_function_is_its_docstring() -> None:
    result = parse("a.c", "/* Adds one. */\nint inc(int x) { return x + 1; }\n")
    assert result.nodes[1].docstring == "Adds one."


def test_cpp_methods_in_and_out_of_the_class_are_callers() -> None:
    source = (
        "namespace ns {\n"
        "struct C {\n  int a() { return b(); }\n  int b();\n};\n"
        "int C::b() { return helper(); }\n"
        "int helper() { return 1; }\n"
        "}\n"
    )
    result = parse("a.cpp", source)
    assert [(c.caller_key, c.name) for c in result.calls] == [
        ("a.cpp::ns.C.a", "b"),
        ("a.cpp::ns.b", "helper"),
    ]


def test_calls_outside_any_function_stay_with_the_module() -> None:
    result = parse("a.c", "int one(void) { return 1; }\nint x = one();\n")
    assert result.calls[0].caller_key == "a.c::"


# The C prototype rule


def test_a_definition_followed_by_a_global_is_not_a_prototype(tmp_path: Path) -> None:
    """The header prototype is swapped for the definition, even with `int counter;` after."""
    edges = _resolve(tmp_path, {
        "geo.h": "int area(int w);\n",
        "geo.c": '#include "geo.h"\nint area(int w) { return w; }\nint counter;\n',
        "main.c": '#include "geo.h"\nint main(void) { return area(2); }\n',
    })
    assert ("main.c::main", "geo.c::area", 1.0) in edges


def test_a_prototype_with_no_definition_stays_the_target(tmp_path: Path) -> None:
    edges = _resolve(tmp_path, {
        "geo.h": "int area(int w);\nint counter;\n",
        "main.c": '#include "geo.h"\nint main(void) { return area(2); }\n',
    })
    assert ("main.c::main", "geo.h::area", 1.0) in edges


# C#: namespaces

NESTED = (
    "namespace Shop {\n"
    "  namespace Text { public static class Pad { public static void Left() {} } }\n"
    "  namespace Labels { public static class Label { public static void Make() {} } }\n"
    "}\n"
)


def test_nested_namespaces_are_joined_and_every_one_is_recorded() -> None:
    attrs = parse("Labels.cs", NESTED).nodes[0].attrs
    assert attrs["packages"] == ["Shop.Text", "Shop.Labels"]  # `Shop` only wraps them
    assert attrs["package"] == "Shop.Text"


def test_a_namespace_holding_code_and_a_nested_one_are_both_recorded() -> None:
    source = "namespace A { class X {} namespace B { class Y {} } }\n"
    assert parse("a.cs", source).nodes[0].attrs["packages"] == ["A", "A.B"]


def test_file_scoped_and_java_packages_are_unchanged() -> None:
    cs = parse("a.cs", "namespace Shop.Models;\npublic class User {}\n").nodes[0].attrs
    java = parse("A.java", "package shop.models;\nclass A {}\n").nodes[0].attrs
    assert (cs["package"], cs["packages"]) == ("Shop.Models", ["Shop.Models"])
    assert (java["package"], java["packages"]) == ("shop.models", ["shop.models"])


def test_using_reaches_a_file_by_any_of_its_namespaces() -> None:
    main = (
        "using Shop.Labels;\nusing Shop.Text;\n"
        "class M { void Run() { Label.Make(); Pad.Left(); } }\n"
    )
    edges = resolve({"Labels.cs": NESTED, "Main.cs": main})
    assert calls(edges) == [
        ("Main.cs::M.Run", "Labels.cs::Shop.Labels.Label.Make", 1.0, Resolution.IMPORT_SCOPED),
        ("Main.cs::M.Run", "Labels.cs::Shop.Text.Pad.Left", 1.0, Resolution.IMPORT_SCOPED),
    ]
    parsed = [parse(p, t) for p, t in {"Labels.cs": NESTED, "Main.cs": main}.items()]
    ctx = Context.build(parsed, None)
    reached = [CSharpProfile().reach(ctx, ctx.files["Main.cs"], i) for i in parsed[1].imports]
    assert [r.paths for r in reached] == [("Labels.cs",), ("Labels.cs",)]


def test_package_scope_covers_every_namespace_of_the_file() -> None:
    other = "namespace Shop.Labels;\nclass Tag {}\n"
    parsed = [parse("Labels.cs", NESTED), parse("Tag.cs", other)]
    ctx = Context.build(parsed, None)
    assert CSharpProfile().package_scope(ctx, ctx.files["Labels.cs"]) == ["Tag.cs"]
    assert CSharpProfile().package_scope(ctx, ctx.files["Tag.cs"]) == ["Labels.cs"]
