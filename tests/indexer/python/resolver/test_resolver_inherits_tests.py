"""INHERITS and TESTS edges, and the resolver's contract-level behaviour."""

from resolver_support import load_tree, of_kind, run_resolver

from codeatlas.indexer.languages.python.resolver import PythonResolver
from codeatlas.indexer.pipeline.plugins import RESOLVERS, load_plugins

FILES = {
    "lib.py": "class Base:\n    pass\n",
    "app.py": (
        "import abc\nfrom lib import Base as B\nfrom typing import Generic\n\n"
        "class Child(B):\n    pass\n\n"
        "class Multi(Child, abc.ABC, Generic[int]):\n    pass\n\n"
        "class Odd(make_base()):\n    pass\n"
    ),
}


def test_inherits_resolves_aliases_and_outside_bases() -> None:
    rows = of_kind(run_resolver(FILES), "inherits")
    assert [r[1:] for r in rows] == [
        ("app.py::Child", "lib.py::Base", "structural", 1.0, 5),
        ("app.py::Multi", "::external:abc.ABC", "structural", 1.0, 8),
        ("app.py::Multi", "::external:typing.Generic", "structural", 1.0, 8),
        ("app.py::Multi", "app.py::Child", "structural", 1.0, 8),
        # make_base() is not a name: no edge, and no guess
    ]


def test_tests_edges_follow_calls_outside_the_test_files() -> None:
    files = {
        "svc.py": "class Svc:\n    def __init__(self): pass\n    def go(self): pass\n",
        "tests/test_svc.py": (
            "from svc import Svc\n\n"
            "def make():\n    return Svc()\n\n"
            "def test_go():\n    s = make()\n    Svc().go()\n    len([])\n"
        ),
    }
    rows = run_resolver(files)
    tests = [r[1:] for r in of_kind(rows, "tests")]
    # make() is a test helper and len is external: neither gets a TESTS edge.
    assert tests == [
        ("tests/test_svc.py::test_go", "svc.py::Svc.__init__", "direct", 1.0, 8),
        ("tests/test_svc.py::test_go", "svc.py::Svc.go", "self_method", 0.9, 8),
    ]


def test_the_plugin_entry_loads() -> None:
    loaded, failures = load_plugins({"python": RESOLVERS["python"]})
    assert not failures
    assert isinstance(loaded[0][1], PythonResolver)
    assert PythonResolver.languages == frozenset({"python"})


def test_only_python_results_and_empty_input_are_fine() -> None:
    assert run_resolver({}) == []
    assert run_resolver(load_tree("chain")) != []


def test_class_named_like_its_imported_base_does_not_recurse() -> None:
    """`class Foo(Foo.Base)` evaluates `Foo` before the class exists: it is the import."""
    rows = run_resolver({
        "lib.py": "class Foo:\n    class Base:\n        def run(self):\n            pass\n",
        "app.py": ("from lib import Foo\n\n"
                   "class Foo(Foo.Base):\n    def go(self):\n        self.run()\n"),
    })
    inherits = [(r[1], r[2]) for r in rows if r[0] == "inherits"]
    assert ("app.py::Foo", "lib.py::Foo.Base") in inherits
    assert ("app.py::Foo.go", "lib.py::Foo.Base.run") in [(r[1], r[2]) for r in rows
                                                         if r[0] == "calls"]


def test_subclass_with_the_same_name_inherits_the_import_not_itself() -> None:
    rows = run_resolver({
        "base.py": "class Foo:\n    def run(self):\n        pass\n",
        "sub.py": ("from base import Foo\n\n"
                   "class Foo(Foo):\n    def go(self):\n        self.run()\n"),
    })
    inherits = [(r[1], r[2]) for r in rows if r[0] == "inherits"]
    assert inherits == [("sub.py::Foo", "base.py::Foo")]  # no self-loop


def test_inside_a_package_a_sibling_does_not_shadow_the_standard_library() -> None:
    rows = run_resolver({
        "pkg/__init__.py": "",
        "pkg/logging.py": "def info():\n    pass\n",
        "pkg/app.py": "import logging\n\ndef main():\n    logging.getLogger()\n",
    })
    imports = [r[2] for r in rows if r[0] == "imports" and r[1] == "pkg/app.py::"]
    assert imports == ["::external:logging"]


def test_name_guesses_do_not_become_tests_edges() -> None:
    """D-23: an untyped receiver gives a guessed CALLS edge but no TESTS edge."""
    files = {
        "svc.py": "class Svc:\n    def launch(self): pass\n",
        "tests/test_guess.py": "def test_launch(thing):\n    thing.launch()\n",
    }
    rows = run_resolver(files)
    calls = [r[1:] for r in of_kind(rows, "calls")]
    assert ("tests/test_guess.py::test_launch", "svc.py::Svc.launch") in [c[:2] for c in calls]
    assert all(c[2] == "name_guess" for c in calls)
    assert of_kind(rows, "tests") == []
