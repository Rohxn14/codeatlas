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
