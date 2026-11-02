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
    result = parse("a.rb", "require 'json'\nclass A; end\n")
    assert result.imports == ()
