"""What imports reach, for the Java and Go profiles."""

from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.go import GoProfile, _guess
from codeatlas.indexer.structural.java import JavaProfile
from codeatlas.models import RawImport
from tests.indexer.structural.helpers import (
    GO_INDEX_ATTRS,
    GO_PACKAGE_KEY,
    FakeIndex,
    go_module,
    parse,
)


def java_context() -> Context:
    files = {
        "src/main/java/a/b/C.java": (
            "package a.b;\npublic class C { static class Inner {} void m() {} }"
        ),
        "src/main/java/a/b/D.java": "package a.b;\nclass D {}",
        "src/test/java/a/x/E.java": "package a.x;\nclass E {}",
        "Loose.java": "class Loose {}",
    }
    return Context.build([parse(path, text) for path, text in files.items()], None)


def reach_java(ctx: Context, target: str, *names: str):
    imp = RawImport("src/main/java/a/Z.java::", target, tuple((n, None) for n in names))
    return JavaProfile().reach(ctx, ctx.files["src/main/java/a/b/D.java"], imp)


def test_java_class_import_maps_to_file_under_any_source_root() -> None:
    reach = reach_java(java_context(), "a.b.C")
    assert reach.paths == ("src/main/java/a/b/C.java",)
    assert reach.binding == "C"
    assert reach_java(java_context(), "a.x.E").paths == ("src/test/java/a/x/E.java",)


def test_java_wildcard_import_reaches_every_file_of_the_package() -> None:
    reach = reach_java(java_context(), "a.b", "*")
    assert reach.paths == ("src/main/java/a/b/C.java", "src/main/java/a/b/D.java")
    assert reach.wildcard and reach.binding is None


def test_java_static_import_brings_a_member_unqualified() -> None:
    reach = reach_java(java_context(), "a.b.C.m")
    assert reach.paths == ("src/main/java/a/b/C.java",)
    assert reach.names == frozenset({"m"}) and reach.class_name == "C"
    star = reach_java(java_context(), "a.b.C", "*")
    assert star.names is None and star.class_name == "C"


def test_java_nested_class_import_binds_the_inner_name() -> None:
    reach = reach_java(java_context(), "a.b.C.Inner")
    assert reach.binding == "Inner" and reach.class_name == "Inner"


def test_java_import_outside_the_repository_is_external() -> None:
    reach = reach_java(java_context(), "java.util.List")
    assert reach.external == "java.util.List" and reach.paths == ()


def test_java_package_scope_is_the_same_package_without_imports() -> None:
    ctx = java_context()
    scope = JavaProfile().package_scope(ctx, ctx.files["src/main/java/a/b/C.java"])
    assert scope == ["src/main/java/a/b/D.java"]


def go_context() -> Context:
    files = {
        "store/store.go": "package store\nfunc New() {}",
        "store/more.go": "package store\nfunc Other() {}",
        "store/store_test.go": "package store\nfunc TestNew() {}",
        "tools/cmd/main.go": "package main\nfunc main() {}",
    }
    results = [go_module(parse(path, text), GO_PACKAGE_KEY) for path, text in files.items()]
    return Context.build(results, FakeIndex(GO_INDEX_ATTRS))  # type: ignore[arg-type]


def reach_go(target: str, alias: str | None = None):
    ctx = go_context()
    imp = RawImport("tools/cmd/main.go::", target, alias=alias)
    return GoProfile().reach(ctx, ctx.files["tools/cmd/main.go"], imp)


def test_go_import_path_under_the_module_path_is_a_directory() -> None:
    reach = reach_go("example.com/shop/store")
    assert reach.paths == ("store/more.go", "store/store.go")  # no _test.go file
    assert reach.binding == "store"


def test_go_alias_dot_and_blank_imports() -> None:
    assert reach_go("example.com/shop/store", "s").binding == "s"
    assert reach_go("example.com/shop/store", "_").binding is None
    dot = reach_go("example.com/shop/store", ".")
    assert dot.binding is None and dot.names is None and dot.paths


def test_go_standard_library_and_third_party_are_external() -> None:
    assert reach_go("fmt").external == "fmt"
    third = reach_go("github.com/x/y/v2")
    assert third.external == "github.com/x/y/v2" and third.binding == "y"
    assert _guess("gopkg.in/yaml.v3") == "yaml"


def test_go_module_path_with_missing_directory_is_external() -> None:
    assert reach_go("example.com/shop/gone").external == "example.com/shop/gone"


def test_go_package_scope_is_the_directory_and_tests_see_test_files() -> None:
    ctx = go_context()
    profile = GoProfile()
    assert profile.package_scope(ctx, ctx.files["store/store.go"]) == ["store/more.go"]
    assert profile.package_scope(ctx, ctx.files["store/store_test.go"]) == [
        "store/more.go",
        "store/store.go",
    ]
