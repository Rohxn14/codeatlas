"""Checks the owner's contract files against docs/contract.md, sections 3 to 7.

The expected values below are copied from the spec, so a typo in either contract file
(a renamed field, a wrong default, a missing enum member) fails here first.
"""

import dataclasses
import inspect
from enum import StrEnum

import pytest

from codeatlas import models
from codeatlas.indexer import adapter

ENUMS = {
    "Tier": {"DEEP": "deep", "STRUCTURAL": "structural", "TEXT": "text"},
    "NodeKind": {
        "PACKAGE": "package",
        "MODULE": "module",
        "CLASS": "class",
        "INTERFACE": "interface",
        "FUNCTION": "function",
        "TEST": "test",
        "ROUTE": "route",
        "EXTERNAL": "external",
        "SECTION": "section",
    },
    "EdgeKind": {
        "CONTAINS": "contains",
        "DEPENDS_ON": "depends_on",
        "IMPORTS": "imports",
        "CALLS": "calls",
        "INHERITS": "inherits",
        "TESTS": "tests",
        "HANDLES": "handles",
        "CALLS_HTTP": "calls_http",
        "CO_CHANGES": "co_changes",
    },
    "Resolution": {
        "STRUCTURAL": "structural",
        "DIRECT": "direct",
        "SELF_METHOD": "self_method",
        "ROUTE_EXACT": "route_exact",
        "ROUTE_PATTERN": "route_pattern",
        "IMPORT_SCOPED": "import_scoped",
        "NAME_GUESS": "name_guess",
        "CONVENTION": "convention",
        "HISTORY": "history",
    },
}

REQUIRED = object()  # marks a field with no default
FACTORY_DICT = object()  # marks `field(default_factory=dict)`

DATACLASSES = {
    "Span": {"start_line": REQUIRED, "end_line": REQUIRED, "start_col": 0, "end_col": 0},
    "FileRecord": {
        "path": REQUIRED,
        "language": REQUIRED,
        "tier": REQUIRED,
        "sha256": REQUIRED,
        "size_bytes": REQUIRED,
    },
    "Snapshot": {
        "id": REQUIRED,
        "repo": REQUIRED,
        "commit_sha": REQUIRED,
        "indexed_at": REQUIRED,
        "indexer_version": REQUIRED,
        "source": REQUIRED,
        "limits_hit": (),
    },
    "Node": {
        "id": REQUIRED,
        "key": REQUIRED,
        "snapshot_id": REQUIRED,
        "kind": REQUIRED,
        "language": REQUIRED,
        "name": REQUIRED,
        "qualname": REQUIRED,
        "path": REQUIRED,
        "span": REQUIRED,
        "signature": None,
        "docstring": None,
        "owner_key": None,
        "attrs": FACTORY_DICT,
    },
    "Edge": {
        "src_id": REQUIRED,
        "dst_id": REQUIRED,
        "kind": REQUIRED,
        "confidence": REQUIRED,
        "resolution": REQUIRED,
        "line": None,
        "attrs": FACTORY_DICT,
    },
    "RawImport": {
        "module_key": REQUIRED,
        "target": REQUIRED,
        "names": (),
        "alias": None,
        "level": 0,
        "is_reexport": False,
        "line": 0,
    },
    "RawCall": {
        "caller_key": REQUIRED,
        "callee_text": REQUIRED,
        "name": REQUIRED,
        "receiver": None,
        "line": 0,
    },
    "RawRoute": {
        "handler_key": REQUIRED,
        "method": REQUIRED,
        "path_pattern": REQUIRED,
        "framework": REQUIRED,
        "router": None,
        "line": 0,
    },
    "RawHttpCall": {
        "caller_key": REQUIRED,
        "client": REQUIRED,
        "method": None,
        "url_text": REQUIRED,
        "url_kind": REQUIRED,
        "line": 0,
    },
    "ParseResult": {
        "path": REQUIRED,
        "language": REQUIRED,
        "tier": REQUIRED,
        "nodes": REQUIRED,
        "imports": (),
        "calls": (),
        "routes": (),
        "http_calls": (),
        "errors": (),
    },
}

PROTOCOLS = {
    "LanguageAdapter": {"attrs": {"language", "tier", "extensions"}, "methods": {"parse"}},
    "SymbolIndex": {
        "attrs": set(),
        "methods": {"by_key", "by_name", "module_for_path", "members", "files"},
    },
    "RepoAnalyzer": {"attrs": {"name"}, "methods": {"analyze"}},
    "Resolver": {"attrs": {"languages"}, "methods": {"resolve"}},
    "Linker": {"attrs": {"name"}, "methods": {"link"}},
}

METHOD_PARAMS = {
    ("LanguageAdapter", "parse"): ["self", "path", "source", "snapshot_id"],
    ("SymbolIndex", "by_key"): ["self", "key"],
    ("SymbolIndex", "by_name"): ["self", "name", "language"],
    ("SymbolIndex", "module_for_path"): ["self", "path"],
    ("SymbolIndex", "members"): ["self", "class_key"],
    ("SymbolIndex", "files"): ["self"],
    ("RepoAnalyzer", "analyze"): ["self", "repo_root", "files", "snapshot_id"],
    ("Resolver", "resolve"): ["self", "results", "index"],
    ("Linker", "link"): ["self", "results", "index", "snapshot_id"],
}


def test_deep_languages() -> None:
    assert frozenset({"python", "typescript", "tsx", "javascript"}) == models.DEEP_LANGUAGES


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enum_members(name: str) -> None:
    enum = getattr(models, name)
    assert issubclass(enum, StrEnum)
    assert {member.name: member.value for member in enum} == ENUMS[name]


@pytest.mark.parametrize("name", sorted(DATACLASSES))
def test_dataclass_fields_and_defaults(name: str) -> None:
    cls = getattr(models, name)
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen, f"{name} must be frozen"
    assert hasattr(cls, "__slots__"), f"{name} must use slots=True"
    actual = {f.name: f for f in dataclasses.fields(cls)}
    expected = DATACLASSES[name]
    assert set(actual) == set(expected)
    for field_name, default in expected.items():
        field = actual[field_name]
        if default is REQUIRED:
            assert field.default is dataclasses.MISSING, field_name
            assert field.default_factory is dataclasses.MISSING, field_name
        elif default is FACTORY_DICT:
            assert field.default_factory is dict, field_name
        else:
            assert field.default == default, field_name


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_protocols(name: str) -> None:
    protocol = getattr(adapter, name)
    assert getattr(protocol, "_is_protocol", False)
    assert getattr(protocol, "_is_runtime_protocol", False), f"{name} must be runtime_checkable"
    spec = PROTOCOLS[name]
    annotations = inspect.get_annotations(protocol)
    assert spec["attrs"] <= set(annotations), f"{name} attributes"
    for method in spec["methods"]:
        assert callable(getattr(protocol, method)), f"{name}.{method}"


@pytest.mark.parametrize(("protocol", "method"), sorted(METHOD_PARAMS))
def test_method_signatures(protocol: str, method: str) -> None:
    function = getattr(getattr(adapter, protocol), method)
    params = list(inspect.signature(function).parameters)
    assert params == METHOD_PARAMS[(protocol, method)]


def test_by_name_language_defaults_to_none() -> None:
    signature = inspect.signature(adapter.SymbolIndex.by_name)
    assert signature.parameters["language"].default is None


def test_id_helpers() -> None:
    sha = "3f2a9c1e5b7d0123456789abcdef0123456789ab"
    snapshot_id = models.make_snapshot_id("polyglot_app", sha)
    assert snapshot_id == "polyglot_app@3f2a9c1e5b7d"
    key = models.make_key("backend/users.py", "UserService.save")
    assert key == "backend/users.py::UserService.save"
    assert models.make_key("backend/users.py", "") == "backend/users.py::"
    assert (
        models.make_node_id(snapshot_id, key)
        == "polyglot_app@3f2a9c1e5b7d/backend/users.py::UserService.save"
    )
