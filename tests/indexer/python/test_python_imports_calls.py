from pathlib import Path

from codeatlas.indexer.languages.python.adapter import PythonAdapter
from codeatlas.models import ParseResult, RawImport

SNAPSHOT = "demo@0123456789ab"
DATA = Path(__file__).parents[2] / "data" / "python"


def parse(rel: str) -> ParseResult:
    return PythonAdapter().parse(rel, (DATA / rel).read_bytes(), SNAPSHOT)


def test_every_import_form() -> None:
    key = "app/imports.py::"
    assert parse("app/imports.py").imports == (
        RawImport(key, "__future__", (("annotations", None),), line=1),
        RawImport(key, "os", line=3),
        RawImport(key, "os.path", alias="osp", line=4),
        RawImport(key, "json", line=4),
        RawImport(key, ".", (("models", None),), level=1, line=5),
        RawImport(
            key, "..core.settings", (("load", "load_settings"), ("DEBUG", None)), level=2, line=6
        ),
        RawImport(
            key, ".models", (("UserService", None), ("Repository", "Repo")), level=1, line=7
        ),
        RawImport(key, "typing", (("*", None),), line=11),
        RawImport(key, "ujson", line=14),
        RawImport(key, "..", (("utils", None),), level=2, line=20),
    )


def test_calls_with_receivers_chains_comprehensions_and_lambdas() -> None:
    calls = [(c.caller_key, c.callee_text, c.name, c.receiver, c.line)
             for c in parse("app/calls.py").calls]
    module, handle, top = "app/calls.py::", "app/calls.py::Handler.handle", "app/calls.py::top"
    assert calls == [
        (module, "logging.getLogger", "getLogger", "logging", 3),
        # A class body and a method's decorator and defaults run in the enclosing scope.
        (module, "compute_timeout", "compute_timeout", None, 15),
        (module, "register_method", "register_method", None, 20),
        (module, "make_default", "make_default", None, 21),
        (handle, "self.repo.save", "save", "self.repo", 22),
        (handle, "build().run", "run", "build()", 23),
        (handle, "build", "build", None, 23),
        (handle, "str", "str", None, 24),
        (handle, "u.name.lower", "lower", "u.name", 25),
        (handle, "sorted", "sorted", None, 26),
        (handle, "self.repo.flush", "flush", "self.repo", 27),
        (handle, "handlers[0]", "handlers[0]", None, 29),
        (handle, "super().handle", "handle", "super()", 30),
        (handle, "super", "super", None, 30),
        (top, "print", "print", None, 35),
        (top, "make_default", "make_default", None, 35),  # inside an f-string
    ]


def test_nested_function_calls_belong_to_the_innermost_function() -> None:
    calls = {(c.caller_key, c.callee_text) for c in parse("app/models.py").calls}
    assert ("app/models.py::UserService.fetch.build", "dict") in calls
    assert ("app/models.py::UserService.fetch", "build") in calls
    assert ("app/models.py::", "functools.lru_cache") in calls
