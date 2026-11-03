"""Exact edges for the sample project in tests/data/typescript_resolver/proj."""

import pytest
from ts_resolver_edges import Edges, build


@pytest.fixture(scope="module")
def proj(tmp_path_factory: pytest.TempPathFactory) -> Edges:
    return build(tmp_path_factory.mktemp("ts"))

M = "src/main.ts::"


def test_specifier_forms_resolve_to_the_real_definition(proj: Edges) -> None:
    assert proj.out("imports", M) == {
        "packages/ui/src/button.ts::Button": ("structural", 1.0, 9),  # workspace `exports`
        "src/chain/deep.ts::deep": ("structural", 1.0, 10),  # barrel -> mid -> deep
        "src/cjs.js::": ("structural", 1.0, 14),  # const cjs = require(...)
        "src/cjs.js::fromCjs": ("structural", 1.0, 15),  # destructured require
        "src/classes.ts::Child": ("structural", 1.0, 13),
        "src/classes.ts::NoCtor": ("structural", 1.0, 13),
        "src/cyc/b.ts::inB": ("structural", 1.0, 12),  # through a cycle of `export *`
        "src/lib/thing.ts::thing": ("structural", 1.0, 5),  # baseUrl; `@exact` is the same pair
        "src/lib/util.ts::default": ("structural", 1.0, 4),  # default import, paths `@lib/*`
        "src/lib/util.ts::slug": ("structural", 1.0, 4),
        "src/ns/index.ts::": ("structural", 1.0, 7),  # namespace import
        "src/side.ts::": ("structural", 1.0, 8),  # side effect
        "src/swap.ts::sw": ("structural", 1.0, 11),  # `./swap.js` names swap.ts
    }


def test_third_party_specifiers_are_external(proj: Edges) -> None:
    external = {k for k in proj.out("imports", M, externals=True) if k.startswith("::external:")}
    assert external == {"::external:axios", "::external:react", "::external:node:fs"}


def test_barrels_point_at_the_real_symbols_and_cycles_end(proj: Edges) -> None:
    assert set(proj.out("imports", "src/chain/index.ts::")) == {"src/chain/deep.ts::deep"}
    assert set(proj.out("imports", "src/cyc/a.ts::")) == {
        "src/cyc/a.ts::inA", "src/cyc/b.ts::inB"
    }


def test_main_calls(proj: Edges) -> None:
    direct = ("direct", 1.0)
    got = proj.out("calls", "src/main.ts::run")
    assert {k: v[:2] for k, v in got.items()} == {
        "packages/ui/src/button.ts::Button": direct,
        "src/chain/deep.ts::deep": direct,
        "src/cjs.js::fromCjs": direct,
        "src/classes.ts::Child.constructor": direct,  # new Child(): the written constructor
        "src/classes.ts::Child.go": ("import_scoped", 1.0),  # kid.go(): receiver type unknown
        "src/cyc/b.ts::inB": direct,
        "src/lib/thing.ts::thing": direct,
        "src/lib/util.ts::default": direct,
        "src/lib/util.ts::slug": direct,
        "src/main.ts::run.inner": direct,  # a nested function
        "src/ns/index.ts::Widget.make": direct,  # ns.Widget.make()
        "src/ns/index.ts::f": direct,  # ns.f()
        "src/swap.ts::sw": direct,
    }
    assert "src/classes.ts::NoCtor" not in got  # `new NoCtor()`: no written constructor
    assert got["src/lib/util.ts::slug"][2] == 18  # first line only


def test_externals_and_globals(proj: Edges) -> None:
    got = proj.out("calls", "src/main.ts::run", externals=True)
    assert {k for k in got if k.startswith("::external:")} == {
        "::external:axios.get",
        "::external:react.useState",  # `React.useState` and `useState` are one edge
        "::external:node:fs.readFileSync",
        "::external:globals.console.log",
        "::external:globals.setTimeout",
    }


def test_jsx_component_is_a_direct_call(proj: Edges) -> None:
    assert proj.out("calls", "src/Card.tsx::Card") == {
        "packages/ui/src/button.ts::Button": ("direct", 1.0, 4)
    }
    assert proj.out("calls", "src/Card.tsx::Plain") == {}  # <div /> is not a component


def test_this_and_super_use_the_class_then_its_bases(proj: Edges) -> None:
    assert proj.out("calls", "src/classes.ts::Child.go") == {
        "src/classes.ts::Base.run": ("self_method", 0.9, 13)
    }
    # Grand extends Child (imported under an alias) extends Base; `missing` exists nowhere.
    assert proj.out("calls", "src/sub.ts::Grand.more") == {
        "src/classes.ts::Base.run": ("self_method", 0.9, 6),
        "src/classes.ts::Child.go": ("self_method", 0.9, 7),
    }


def test_import_scoped_splits_confidence_between_candidates(proj: Edges) -> None:
    assert proj.out("calls", "src/scoped.ts::useThem") == {
        "src/helpers.ts::target": ("import_scoped", 1.0, 4),
        "src/helpers.ts::A.pair": ("import_scoped", 0.5, 5),
        "src/helpers.ts::B.pair": ("import_scoped", 0.5, 5),
    }


def test_name_guess_is_capped_and_gives_up_on_many_candidates(proj: Edges) -> None:
    # `lonely` has one definition in a file the caller never imports: 1/1 capped at 0.3.
    assert proj.out("calls", "src/guess.ts::caller") == {
        "src/elsewhere.ts::lonely": ("name_guess", 0.3, 2)
    }  # `many` has six definitions: no edge at all
    # A .js caller may guess a .ts definition (one language family).
    assert proj.out("calls", "src/legacy.js::old") == {
        "src/elsewhere.ts::lonely": ("name_guess", 0.3, 2)
    }


def test_inherits_resolves_through_aliases_and_externals(proj: Edges) -> None:
    assert proj.out("inherits", "src/classes.ts::Child") == {
        "src/classes.ts::Base": ("structural", 1.0, 7),
        "src/classes.ts::Iface": ("structural", 1.0, 7),
    }
    assert proj.out("inherits", "src/sub.ts::Grand") == {
        "src/classes.ts::Child": ("structural", 1.0, 4)
    }
    assert proj.out("inherits", "src/sub.ts::View", externals=True) == {
        "::external:react.Component": ("structural", 1.0, 12)
    }


def test_tests_edges_skip_test_helpers(proj: Edges) -> None:
    test = "tests/main.test.ts::run > works"
    assert proj.out("tests", test) == {"src/main.ts::run": ("direct", 1.0, 9)}
    assert "tests/main.test.ts::helper" in proj.out("calls", test)  # a call, but not a TESTS edge
