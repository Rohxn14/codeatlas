"""IMPORTS edges: modules, symbols, re-exports, relative imports and outside targets."""

from resolver_support import load_tree, of_kind, run_resolver

APP = "shop/app.py::"


def imports_of(rows, source):
    found = [(r[2], r[3], r[4], r[5]) for r in of_kind(rows, "imports") if r[1] == source]
    return sorted(found, key=lambda t: (t[3], t[0]))


def test_every_import_form_in_one_file() -> None:
    rows = run_resolver(load_tree("shop"))
    assert imports_of(rows, APP) == [
        ("::external:os", "structural", 1.0, 1),
        ("::external:os.path", "structural", 1.0, 2),
        ("::external:requests", "structural", 1.0, 3),
        ("shop/util/money.py::", "structural", 1.0, 4),  # import a.b.c as x
        ("shop/core.py::", "structural", 1.0, 5),  # from . import core: a submodule
        ("shop/util/money.py::fmt", "structural", 1.0, 6),  # alias; through util/__init__
        ("shop/__init__.py::", "structural", 1.0, 7),  # VERSION is a variable: its module
        ("shop/core.py::Order", "structural", 1.0, 7),  # re-exported by shop/__init__
        ("shop/core.py::make_order", "structural", 1.0, 7),
        ("shop/util/money.py::", "structural", 1.0, 8),  # from pkg import submodule
        ("::external:shop.missing.nothing", "structural", 1.0, 9),
        # line 10 climbs out of the repository: no edge and no guess
    ]


def test_reexport_in_a_package_init_points_at_the_definition() -> None:
    rows = run_resolver(load_tree("shop"))
    assert imports_of(rows, "shop/__init__.py::") == [
        ("shop/core.py::Order", "structural", 1.0, 1),
        ("shop/core.py::make_order", "structural", 1.0, 1),
    ]


def test_reexports_are_followed_for_three_hops_and_no_further() -> None:
    rows = run_resolver(load_tree("chain"))
    # h2 -> h3 -> h4 -> h5 is three hops: the real definition is reached.
    assert imports_of(rows, "chain/use3.py::") == [("chain/h5.py::f", "structural", 1.0, 1)]
    # h1 -> h2 -> h3 -> h4 -> h5 is four: the edge stops at the module that was imported.
    assert imports_of(rows, "chain/use4.py::") == [("chain/h1.py::", "structural", 1.0, 1)]


def test_src_folder_and_package_roots_are_import_roots() -> None:
    files = load_tree("src")
    rows = run_resolver(files, packages={"src/lib": "lib"})
    assert imports_of(rows, "src/lib/pkg/main.py::") == [
        ("src/lib/pkg/tools.py::helper", "structural", 1.0, 1),
        ("src/lib/pkg/tools.py::", "structural", 1.0, 2),  # from . import tools
    ]
    # Without the manifest's package root, `pkg` cannot be placed: it reads as external.
    bare = run_resolver(files)
    assert imports_of(bare, "src/lib/pkg/main.py::")[0] == (
        "::external:pkg.tools.helper", "structural", 1.0, 1)


def test_a_src_layout_needs_no_manifest() -> None:
    rows = run_resolver({"src/app/x.py": "def f(): pass\n", "main.py": "from app.x import f\n"})
    assert imports_of(rows, "main.py::") == [("src/app/x.py::f", "structural", 1.0, 1)]


def test_several_matching_files_split_the_confidence() -> None:
    files = load_tree("ambiguous")
    rows = run_resolver(files, packages={"ambiguous/a": "a", "ambiguous/b": "b"})
    assert imports_of(rows, "ambiguous/main.py::") == [
        ("ambiguous/a/utils.py::", "structural", 0.5, 1),
        ("ambiguous/b/utils.py::", "structural", 0.5, 1),
    ]


def test_a_star_import_points_at_the_module() -> None:
    files = {"a.py": "def f(): pass\n", "b.py": "from a import *\n\ndef g():\n    f()\n"}
    rows = run_resolver(files)
    assert imports_of(rows, "b.py::") == [("a.py::", "structural", 1.0, 1)]
    assert ("calls", "b.py::g", "a.py::f", "direct", 1.0, 4) in rows  # the name came from it
