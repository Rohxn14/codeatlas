"""PHP: the imports query, PSR-4 mapping, includes, scopes and the sample project."""

from __future__ import annotations

from dataclasses import replace

from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.php import PhpProfile
from codeatlas.models import ParseResult, Resolution, make_key
from tests.indexer.structural.helpers import FakeIndex, parse
from tests.indexer.structural.test_structural_resolver import calls, kind_scores, resolve, scored

PROFILE = PhpProfile()
PKG = make_key("composer.json", "package:acme/shop")
PSR4 = {PKG: {"autoload_psr4": {"Shop\\": ["src"], "Shop\\Tests\\": ["tests"]}}}
USER = "<?php\nnamespace Shop\\Models;\nclass User { public static function find($i) {} }\n"


def keyed(result: ParseResult) -> ParseResult:
    module = replace(result.nodes[0], attrs={**result.nodes[0].attrs, "package_key": PKG})
    return replace(result, nodes=(module, *result.nodes[1:]))


def reach(source: str, files: dict[str, str], where: str = "bin/app.php") -> list:
    parsed = [keyed(parse(p, t)) for p, t in {**files, where: source}.items()]
    ctx = Context.build(parsed, FakeIndex(PSR4))  # type: ignore[arg-type]
    main = ctx.files[where]
    return [PROFILE.reach(ctx, main, imp) for imp in main.imports]


def test_imports_query_single_alias_group_function_and_include() -> None:
    result = parse(
        "a.php",
        "<?php\nnamespace App\\Http;\nuse App\\Models\\User;\nuse App\\Models\\Post as P;\n"
        "use App\\{A, B as C};\nuse function App\\helpers\\f;\n"
        "require 'x.php';\ninclude_once __DIR__ . '/y.php';\n",
    )
    found = [(i.target, i.names, i.alias, i.line) for i in result.imports]
    assert found == [
        ("App\\Models\\User", (), None, 3),
        ("App\\Models\\Post", (), "P", 4),
        ("App", (("A", None),), None, 5),
        ("App", (("B", None),), "C", 5),
        ("App\\helpers\\f", (), None, 6),
        ("x.php", (), None, 7),
        ("/y.php", (), None, 8),
    ]
    assert result.nodes[0].attrs["package"] == "App\\Http"


def test_a_file_without_namespace_or_imports() -> None:
    result = parse("a.php", "<?php\nfunction f() {}\n")
    assert result.imports == () and "package" not in result.nodes[0].attrs


def test_use_maps_through_the_psr4_table() -> None:
    files = {"src/Models/User.php": USER}
    (found,) = reach("<?php\nuse Shop\\Models\\User;\n", files)
    assert (found.paths, found.binding, found.class_name) == (
        ("src/Models/User.php",), "User", "User")


def test_use_alias_and_grouped_use() -> None:
    files = {"src/Models/User.php": USER, "src/Models/Post.php": USER.replace("User", "Post")}
    alias, grouped, aliased = reach(
        "<?php\nuse Shop\\Models\\User as U;\nuse Shop\\Models\\{Post, User as V};\n", files
    )
    assert (alias.binding, alias.class_name) == ("U", "User")
    assert (grouped.binding, grouped.paths) == ("Post", ("src/Models/Post.php",))
    assert (aliased.binding, aliased.paths) == ("V", ("src/Models/User.php",))


def test_without_composer_the_declared_namespace_finds_the_class() -> None:
    parsed = [parse("lib/Odd.php", USER), parse("bin/a.php", "<?php\nuse Shop\\Models\\User;\n")]
    ctx = Context.build(parsed, None)
    main = ctx.files["bin/a.php"]
    (found,) = [PROFILE.reach(ctx, main, i) for i in main.imports]
    assert found.paths == ("lib/Odd.php",)


def test_unknown_class_is_external_with_its_binding() -> None:
    (found,) = reach("<?php\nuse Illuminate\\Support\\Str;\n", {})
    assert (found.external, found.binding) == ("Illuminate\\Support\\Str", "Str")


def test_use_function_reaches_the_file_declaring_it() -> None:
    helpers = "<?php\nnamespace Shop\\Util;\nfunction money($c) {}\n"
    (found,) = reach("<?php\nuse function Shop\\Util\\money;\n", {"src/Util/helpers.php": helpers})
    assert found.paths == ("src/Util/helpers.php",) and found.names == frozenset({"money"})


def test_require_with_a_literal_path_is_a_file_import() -> None:
    files = {"src/b.php": "<?php\nfunction b() {}\n"}
    near, rooted, missing = reach(
        "<?php\nrequire __DIR__ . '/../src/b.php';\nrequire 'src/b.php';\nrequire 'nope.php';\n",
        files, where="bin/app.php",
    )
    assert near.paths == ("src/b.php",) and rooted.paths == ("src/b.php",)
    assert missing.external == "nope.php"


def test_package_scope_is_the_namespace() -> None:
    files = {"a.php": USER, "b.php": USER.replace("User", "Other"),
             "c.php": "<?php\nnamespace Else;\nclass C {}\n"}
    ctx = Context.build([parse(p, t) for p, t in files.items()], None)
    assert PROFILE.package_scope(ctx, ctx.files["a.php"]) == ["b.php"]


def test_this_and_static_calls_stay_in_the_class_but_a_function_is_not_a_method() -> None:
    edges = resolve(
        {"a.php": "<?php\nclass A { function go() { $this->x(); self::y(); z(); }"
                  " function x() {} static function y() {} function z() {} }\n"},
        packages={},
    )
    scoped = {d for _, d, _, r in calls(edges) if r is Resolution.IMPORT_SCOPED}
    assert scoped == {"a.php::A.x", "a.php::A.y"}
    # `z()` is a function call, so the method `z` is never an import-scoped answer; it is
    # only found as a name guess, with the guess's low confidence.
    guesses = [(d, c) for _, d, c, r in calls(edges) if r is Resolution.NAME_GUESS]
    assert guesses == [("a.php::A.z", 0.3)]


def test_sample_project_matches_the_hand_labels_exactly() -> None:
    result = scored("php")
    for kind in ("calls", "imports"):
        assert kind_scores(result, kind)["precision"] == 1.0
        assert kind_scores(result, kind)["recall"] == 1.0


def test_resolution_is_import_scoped_not_a_guess() -> None:
    edges = resolve(
        {
            "src/Models/User.php": USER,
            "bin/a.php": "<?php\nuse Shop\\Models\\User;\nUser::find(1);\n",
        },
        packages=PSR4,
    )
    assert [(d, r) for _, d, _, r in calls(edges)] == [
        ("src/Models/User.php::User.find", Resolution.IMPORT_SCOPED)
    ]
