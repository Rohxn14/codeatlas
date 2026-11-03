"""T17f: the review fixes of T17a and T17b, each pinned by its failing example."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.indexer.structural import context as context_module
from codeatlas.indexer.structural.c import _read_cmake_folders
from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.php import PhpProfile
from codeatlas.indexer.structural.ruby import RubyProfile
from codeatlas.indexer.structural.rust import RustProfile
from codeatlas.models import EdgeKind, RawCall, Resolution
from tests.indexer.structural.helpers import parse
from tests.indexer.structural.test_native_profiles import Index, _resolve, context
from tests.indexer.structural.test_structural_resolver import calls, resolve

# 1. Rust: a capitalised qualifier that is not in scope


RUST_A = (
    "struct A;\nenum E { V(i32) }\nimpl A {\n fn new() -> A { A }\n fn V() {}\n}\n"
    "fn g() { HashMap::new(); T::new(); E::V(1); A::new(); }\n"
)


def test_rust_unknown_type_qualifier_does_not_land_on_another_types_method(
    tmp_path: Path,
) -> None:
    edges = _resolve(tmp_path, {"a.rs": RUST_A})
    # Only the written `A::new()` reaches A.new; HashMap/T/E calls claim nothing.
    assert edges == [("a.rs::g", "a.rs::A.new", 1.0)]


def test_rust_narrow_keeps_methods_of_the_named_type_only(tmp_path: Path) -> None:
    ctx = context(tmp_path, {"a.rs": RUST_A})
    info = ctx.files["a.rs"]
    nodes = info.functions["new"]
    profile = RustProfile()
    hashmap = RawCall("a.rs::g", "HashMap::new", "new", "HashMap", 7)
    assert profile.narrow(ctx, info, hashmap, nodes) == []
    own = RawCall("a.rs::g", "a::A::new", "new", "a::A", 7)
    assert profile.narrow(ctx, info, own, nodes) == nodes
    method = RawCall("a.rs::g", "x.new", "new", "x", 7)  # a variable: unchanged
    assert profile.narrow(ctx, info, method, nodes) == nodes


# 2. Rust: `crate`, `self`, `super` and inline modules are never external


def test_rust_super_without_a_crate_root_is_not_external(tmp_path: Path) -> None:
    files = {"x/a.rs": "fn f() {}\nfn g() { super::f(); crate::h(); }\n"}
    edges = _resolve(tmp_path, files)
    assert not [e for e in edges if "::external:" in e[1]]


def test_rust_inline_module_path_resolves_inside_the_file(tmp_path: Path) -> None:
    files = {"lib.rs": "mod inner { pub fn f() {} }\nfn g() { inner::f(); }\n"}
    assert _resolve(tmp_path, files) == [("lib.rs::g", "lib.rs::inner.f", 1.0)]


def test_rust_unknown_crate_is_still_external(tmp_path: Path) -> None:
    files = {"lib.rs": "fn g() { regex::escape(); }\n"}
    assert _resolve(tmp_path, files) == [("lib.rs::g", "::external:regex.escape", 1.0)]


# 3. Untyped receivers: the 5-candidate cut-off in every tier


def _seven_saves(language: str) -> dict[str, str]:
    if language == "csharp":
        classes = "".join(f"class C{i} {{ public void Save() {{}} }}\n" for i in range(7))
        return {"Lib.cs": "namespace Lib {\n" + classes
                + "class U { void G(object x) { x.Save(); } }\n}\n"}
    classes = "".join(f"class C{i} {{ function save() {{}} }}\n" for i in range(7))
    return {"lib.php": "<?php\nnamespace Lib;\n" + classes
            + "function g($x) { $x->save(); }\n"}


@pytest.mark.parametrize("language", ["csharp", "php"])
def test_untyped_receiver_in_the_own_file_gives_up_past_five(language: str) -> None:
    assert calls(resolve(_seven_saves(language), packages={})) == []


def test_untyped_receiver_in_the_package_scope_gives_up_past_five() -> None:
    classes = "".join(f"class C{i} {{ public void Save() {{}} }}\n" for i in range(7))
    files = {
        "a/Defs.cs": "namespace Lib;\n" + classes,
        "b/Use.cs": "namespace Lib;\nclass U { void G(object x) { x.Save(); } }\n",
    }
    assert calls(resolve(files, packages={})) == []


# 4. A class-named receiver that is not in scope


def test_out_of_scope_class_receiver_is_not_the_callers_own_method() -> None:
    files = {
        "src/User.php": (
            "<?php\nnamespace App;\nclass User {\n"
            "  static function find($i) { return \\Vendor\\Lib\\Repo::find(1); }\n}\n"
        )
    }
    found = calls(resolve(files, packages={}))
    assert all(r is Resolution.NAME_GUESS and c <= 0.3 for _, _, c, r in found)


def test_class_receiver_in_scope_still_resolves() -> None:
    files = {
        "src/User.php": "<?php\nnamespace App;\nclass User {\n"
        "  static function find($i) { return Repo::find(1); }\n}\n",
        "src/Repo.php": "<?php\nnamespace App;\nclass Repo { static function find($i) {} }\n",
    }
    found = calls(resolve(files, packages={}))
    assert found == [
        ("src/User.php::User.find", "src/Repo.php::Repo.find", 1.0, Resolution.IMPORT_SCOPED)
    ]


# 5. Ruby: a guessed constant never hides repository code


def test_ruby_external_require_does_not_bind_a_constant_the_repo_defines() -> None:
    files = {
        "util.rb": "module Util\n  def self.slug(s); s; end\nend\n",
        "app.rb": "require 'util'\nclass App\n  def go\n    Util.slug(1)\n  end\nend\n",
    }
    found = calls(resolve(files, packages={}))
    assert not [d for _, d, _, _ in found if "::external:" in d]
    assert [d for _, d, _, _ in found] == ["util.rb::Util.slug"]


def test_ruby_external_require_still_binds_an_outside_constant() -> None:
    parsed = [parse("app.rb", "require 'json'\nJSON.parse(1)\n")]
    ctx = Context.build(parsed, None)
    info = ctx.files["app.rb"]
    reach = RubyProfile().reach(ctx, info, info.imports[0])
    assert (reach.external, reach.binding) == ("json", "JSON")


# 6. PHP: dynamic includes


def test_php_double_quoted_include_with_a_variable_is_not_an_import() -> None:
    source = (
        '<?php\nrequire "$dir/x.php";\nrequire __DIR__ . "/$v.php";\n'
        'require "lib/y.php";\nrequire __DIR__ . "/w.php";\n'
    )
    assert [(i.target, i.line) for i in parse("a.php", source).imports] == [
        ("lib/y.php", 4), ("/w.php", 5),
    ]
    edges = resolve({"a.php": source, "x.php": "<?php\n"}, packages={})
    assert not [e for e in edges if e.kind is EdgeKind.IMPORTS and e.dst_id.endswith("x.php::")]


# 7. CMake: source-dir variables, comments, generator expressions


def test_cmake_root_variables_comments_and_build_interface(tmp_path: Path) -> None:
    files = {
        "sub/CMakeLists.txt": (
            "include_directories(${CMAKE_SOURCE_DIR}/inc)  # the shared headers\n"
            "# include_directories(other)\n"
            "#[[ include_directories(old) ]]\n"
            "target_include_directories(t PUBLIC\n"
            "  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/api>\n"
            "  $<INSTALL_INTERFACE:include>\n"
            "  ${PROJECT_SOURCE_DIR}/gen)\n"
        ),
        "inc/a.h": "int a(void);\n",
    }
    ctx = context(tmp_path, files)
    assert _read_cmake_folders(ctx) == ["inc", "sub/api", "gen"]


# 8. Context.read guards itself


def test_context_read_stays_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.c").write_bytes(b"int a;\n")
    (tmp_path / "secret.txt").write_bytes(b"secret")
    ctx = Context(None, root=root)
    assert ctx.read("src/a.c") == b"int a;\n"
    assert ctx.read("../secret.txt") is None
    assert ctx.read("src/../../secret.txt") is None
    assert ctx.read(str(tmp_path / "secret.txt")) is None
    assert ctx.read("/etc/hostname") is None
    assert ctx.read("src") is None  # a folder, not a file
    assert ctx.read("missing.c") is None


def test_context_read_rejects_a_symlink_leaving_the_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")
    (root / "inside.c").write_bytes(b"ok")
    try:
        os.symlink(tmp_path / "secret.txt", root / "out.c")
        os.symlink(root / "inside.c", root / "alias.c")
    except (OSError, NotImplementedError):
        pytest.skip("this OS or account cannot create symlinks")
    ctx = Context(None, root=root)
    assert ctx.read("out.c") is None
    assert ctx.read("alias.c") == b"ok"  # a link that stays inside is fine


def test_context_read_caps_the_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "big.c").write_bytes(b"x" * 100)
    monkeypatch.setattr(context_module, "MAX_READ_BYTES", 10)
    assert Context(None, root=tmp_path).read("big.c") is None


def test_context_read_without_a_root(tmp_path: Path) -> None:
    assert Context(None).read("a.c") is None


# 11. PHP: backslash include paths and case-insensitive class names


def test_php_backslash_include_path_and_case_insensitive_class() -> None:
    files = {
        "lib/x.php": "<?php\nfunction helper() {}\n",
        "src/Models/User.php": "<?php\nnamespace App\\Models;\nclass User { function go() {} }\n",
        "main.php": (
            "<?php\nuse App\\Models\\user;\nrequire __DIR__ . '\\lib\\x.php';\n"
            "user::go();\n"
        ),
    }
    parsed = [parse(p, t) for p, t in files.items()]
    ctx = Context.build(parsed, Index({}))  # type: ignore[arg-type]
    info = ctx.files["main.php"]
    reaches = [PhpProfile().reach(ctx, info, imp) for imp in info.imports]
    assert [(r.paths, r.class_name) for r in reaches] == [
        (("src/Models/User.php",), "User"),
        (("lib/x.php",), None),
    ]
