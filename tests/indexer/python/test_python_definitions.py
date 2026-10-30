from pathlib import Path

import pytest

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.languages.python.adapter import PythonAdapter
from codeatlas.indexer.registry import Registry
from codeatlas.models import Node, NodeKind, ParseResult, Tier

SNAPSHOT = "demo@0123456789ab"
DATA = Path(__file__).parents[2] / "data" / "python"
SAMPLES = sorted(p.relative_to(DATA).as_posix() for p in DATA.rglob("*.py"))


def parse(rel: str) -> ParseResult:
    return PythonAdapter().parse(rel, (DATA / rel).read_bytes(), SNAPSHOT)


def by_qualname(result: ParseResult) -> dict[str, Node]:
    return {n.qualname: n for n in result.nodes}


def test_registered_as_the_deep_python_adapter() -> None:
    adapter = Registry().adapter_for("python")
    assert isinstance(adapter, PythonAdapter)
    assert isinstance(adapter, LanguageAdapter)
    assert adapter.tier is Tier.DEEP
    assert ".py" in adapter.extensions


def test_module_node_comes_first_with_its_docstring() -> None:
    result = parse("app/models.py")
    assert result.tier is Tier.DEEP and result.language == "python" and result.errors == ()
    module = result.nodes[0]
    assert (module.kind, module.key, module.qualname) == (NodeKind.MODULE, "app/models.py::", "")
    assert module.id == f"{SNAPSHOT}/app/models.py::"
    assert module.docstring == "User models and services."
    assert sum(1 for n in result.nodes if n.kind is NodeKind.MODULE) == 1


def test_classes_methods_and_nesting() -> None:
    nodes = by_qualname(parse("app/models.py"))
    assert {q: (n.kind, n.owner_key) for q, n in nodes.items() if q} == {
        "Repository": (NodeKind.CLASS, None),
        "Repository.save": (NodeKind.FUNCTION, "app/models.py::Repository"),
        "UserService": (NodeKind.CLASS, None),
        "UserService.Config": (NodeKind.CLASS, "app/models.py::UserService"),
        "UserService.Config.load": (NodeKind.FUNCTION, "app/models.py::UserService.Config"),
        "UserService.__init__": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.name#dc8b": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.name#7962": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.version": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.create": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.fetch": (NodeKind.FUNCTION, "app/models.py::UserService"),
        "UserService.fetch.build": (NodeKind.FUNCTION, None),
        "helper#66c7": (NodeKind.FUNCTION, None),
        "helper#4113": (NodeKind.FUNCTION, None),
    }


def test_class_details() -> None:
    service = by_qualname(parse("app/models.py"))["UserService"]
    assert service.name == "UserService"
    assert service.signature == "class UserService(Repository, metaclass=Meta)"
    assert service.attrs == {"decorators": [], "bases": ["Repository"]}
    assert service.docstring == "Business logic for users."
    assert (service.span.start_line, service.span.end_line) == (13, 48)


def test_decorators_properties_static_and_class_methods() -> None:
    nodes = by_qualname(parse("app/models.py"))
    getter, setter = nodes["UserService.name#dc8b"], nodes["UserService.name#7962"]
    assert getter.name == setter.name == "name"
    assert getter.key == "app/models.py::UserService.name#dc8b"
    assert getter.attrs["decorators"] == ["property"]
    assert getter.docstring == "The service name."
    assert getter.signature == "def name(self) -> str"
    assert setter.attrs["decorators"] == ["name.setter"]
    assert setter.signature == "def name(self, value: str) -> None"
    assert nodes["UserService.version"].attrs["decorators"] == ["staticmethod"]
    assert nodes["UserService.create"].attrs["decorators"] == ["classmethod"]
    # A decorated span starts at its first decorator.
    assert (getter.span.start_line, getter.span.end_line) == (25, 28)


def test_async_function_signature_spans_lines_and_stops_at_the_colon() -> None:
    fetch = by_qualname(parse("app/models.py"))["UserService.fetch"]
    assert fetch.attrs == {
        "decorators": ["functools.lru_cache(maxsize=None)"],
        "is_async": True,
    }
    assert fetch.signature == "async def fetch(self, user_id: int, *, fresh: bool = False) -> dict"
    assert fetch.docstring is None


def test_pytest_tests() -> None:
    nodes = by_qualname(parse("tests/test_users.py"))
    tests = {q: n.attrs["test_id"] for q, n in nodes.items() if n.kind is NodeKind.TEST}
    assert tests == {
        "test_create_user": "tests/test_users.py::test_create_user",
        "test_fetch": "tests/test_users.py::test_fetch",
        "TestUserService.test_save": "tests/test_users.py::TestUserService::test_save",
        "TestUserService.TestNested.test_deep":
            "tests/test_users.py::TestUserService::TestNested::test_deep",
        "UserCase.test_load": "tests/test_users.py::UserCase::test_load",
        "UserCase.testLegacyName": "tests/test_users.py::UserCase::testLegacyName",
    }
    # Fixtures, helpers, nested functions and methods of non-test classes are not tests.
    for qualname in ("user", "helper_for_tests", "test_fetch.test_inner",
                     "TestUserService.setup_method", "Helper.test_not_collected"):
        assert nodes[qualname].kind is NodeKind.FUNCTION, qualname
    assert nodes["TestUserService"].kind is NodeKind.CLASS
    assert nodes["TestUserService.test_save"].owner_key == "tests/test_users.py::TestUserService"


def test_unittest_style_tests_in_a_suffix_named_file() -> None:
    nodes = by_qualname(parse("app/users_test.py"))
    tests = {q: n.attrs["test_id"] for q, n in nodes.items() if n.kind is NodeKind.TEST}
    assert tests == {
        "ApiTests.test_list": "app/users_test.py::ApiTests::test_list",
        "test_top": "app/users_test.py::test_top",
    }


def test_test_names_outside_test_files_are_plain_functions() -> None:
    source = b"def test_something():\n    pass\n"
    result = PythonAdapter().parse("app/checks.py", source, SNAPSHOT)
    assert result.nodes[1].kind is NodeKind.FUNCTION


def test_syntax_error_gives_a_partial_result_and_an_error() -> None:
    result = parse("app/broken.py")
    assert result.errors == ("syntax error: missing ')' at line 5, column 11",)
    nodes = by_qualname(result)
    assert {"ok", "Fine", "Fine.method"} <= set(nodes)
    assert [(c.caller_key, c.callee_text) for c in result.calls] == [
        ("app/broken.py::Fine.method", "ok")
    ]


def test_empty_and_undecodable_files_never_raise() -> None:
    adapter = PythonAdapter()
    empty = adapter.parse("empty.py", b"", SNAPSHOT)
    assert [n.kind for n in empty.nodes] == [NodeKind.MODULE] and empty.errors == ()
    binary = adapter.parse("odd.py", b"\xff\xfe def \x00 (:", SNAPSHOT)
    assert binary.nodes[0].kind is NodeKind.MODULE and binary.errors


@pytest.mark.parametrize("rel", SAMPLES)
def test_keys_match_the_structural_tier(rel: str) -> None:
    """T00's key rule: a symbol has the same key whichever tier parses it."""
    structural = Registry(deep={}).adapter_for("python")
    assert structural.tier is Tier.STRUCTURAL
    source = (DATA / rel).read_bytes()
    deep_keys = {n.key for n in PythonAdapter().parse(rel, source, SNAPSHOT).nodes}
    assert deep_keys == {n.key for n in structural.parse(rel, source, SNAPSHOT).nodes}
