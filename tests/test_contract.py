"""Checks the owner's contract files against docs/contract.md, to catch typos early."""

import dataclasses
import inspect
import typing
from enum import StrEnum

import pytest

from codeatlas import models
from codeatlas.indexer import adapter

MISSING = dataclasses.MISSING

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

# Field name -> default (MISSING when required, "factory" for default_factory=dict).
DATACLASSES = {
    "Span": {"start_line": MISSING, "end_line": MISSING, "start_col": 0, "end_col": 0},
    "FileRecord": {
        "path": MISSING,
        "language": MISSING,
        "tier": MISSING,
        "sha256": MISSING,
        "size_bytes": MISSING,
    },
    "Snapshot": {
        "id": MISSING,
        "repo": MISSING,
        "commit_sha": MISSING,
        "indexed_at": MISSING,
        "indexer_version": MISSING,
        "source": MISSING,
        "limits_hit": (),
    },
    "Node": {
        "id": MISSING,
        "key": MISSING,
        "snapshot_id": MISSING,
        "kind": MISSING,
        "language": MISSING,
        "name": MISSING,
        "qualname": MISSING,
        "path": MISSING,
        "span": MISSING,
        "signature": None,
        "docstring": None,
        "owner_key": None,
        "attrs": "factory",
    },
    "Edge": {
        "src_id": MISSING,
        "dst_id": MISSING,
        "kind": MISSING,
        "confidence": MISSING,
        "resolution": MISSING,
        "line": None,
        "attrs": "factory",
    },
    "RawImport": {
        "module_key": MISSING,
        "target": MISSING,
        "names": (),
        "alias": None,
        "level": 0,
        "is_reexport": False,
        "line": 0,
    },
    "RawCall": {
        "caller_key": MISSING,
        "callee_text": MISSING,
        "name": MISSING,
        "receiver": None,
        "line": 0,
    },
    "RawRoute": {
        "handler_key": MISSING,
        "method": MISSING,
        "path_pattern": MISSING,
        "framework": MISSING,
        "router": None,
        "line": 0,
    },
    "RawHttpCall": {
        "caller_key": MISSING,
        "client": MISSING,
        "method": None,
        "url_text": MISSING,
        "url_kind": MISSING,
        "line": 0,
    },
    "ParseResult": {
        "path": MISSING,
        "language": MISSING,
        "tier": MISSING,
        "nodes": MISSING,
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
    assert models.DEEP_LANGUAGES == frozenset({"python", "typescript", "tsx", "javascript"})


def test_id_helpers() -> None:
    sha = "3f2a9c1e5b7d0011223344556677889900aabbcc"
    snapshot_id = models.make_snapshot_id("polyglot_app", sha)
    assert snapshot_id == "polyglot_app@3f2a9c1e5b7d"
    key = models.make_key("backend/users.py", "UserService.save")
    assert key == "backend/users.py::UserService.save"
    assert models.make_key("backend/users.py", "") == "backend/users.py::"
    assert (
        models.make_node_id(snapshot_id, key)
        == "polyglot_app@3f2a9c1e5b7d/backend/users.py::UserService.save"
    )


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enum(name: str) -> None:
    enum = getattr(models, name)
    assert issubclass(enum, StrEnum)
    assert {member.name: member.value for member in enum} == ENUMS[name]


@pytest.mark.parametrize("name", sorted(DATACLASSES))
def test_dataclass(name: str) -> None:
    cls = getattr(models, name)
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__
    assert params.frozen, f"{name} must be frozen"
    assert hasattr(cls, "__slots__"), f"{name} must use slots"
    fields = {f.name: f for f in dataclasses.fields(cls)}
    assert set(fields) == set(DATACLASSES[name]), f"{name} fields differ from the contract"
    for field_name, expected in DATACLASSES[name].items():
        field = fields[field_name]
        if expected == "factory":
            assert field.default_factory is dict, f"{name}.{field_name} needs default_factory=dict"
        elif expected is MISSING:
            assert field.default is MISSING and field.default_factory is MISSING, (
                f"{name}.{field_name} must be required"
            )
        else:
            assert field.default == expected, f"{name}.{field_name} default"


def test_required_fields_come_in_contract_order() -> None:
    """Positional construction depends on order; spot-check the most used classes."""
    names = [f.name for f in dataclasses.fields(models.Node)]
    assert names[:9] == [
        "id", "key", "snapshot_id", "kind", "language", "name", "qualname", "path", "span"
    ]
    assert [f.name for f in dataclasses.fields(models.Span)][:2] == ["start_line", "end_line"]


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_protocol(name: str) -> None:
    proto = getattr(adapter, name)
    assert getattr(proto, "_is_protocol", False), f"{name} must be a typing.Protocol"
    assert getattr(proto, "_is_runtime_protocol", False), f"{name} must be runtime_checkable"
    members = _protocol_members(proto)
    expected = PROTOCOLS[name]
    assert set(members) == expected["attrs"] | expected["methods"]
    for method in expected["methods"]:
        assert callable(getattr(proto, method))


@pytest.mark.parametrize(("proto", "method"), sorted(METHOD_PARAMS))
def test_method_signature(proto: str, method: str) -> None:
    fn = getattr(getattr(adapter, proto), method)
    assert list(inspect.signature(fn).parameters) == METHOD_PARAMS[(proto, method)]


def test_by_name_language_defaults_to_none() -> None:
    params = inspect.signature(adapter.SymbolIndex.by_name).parameters
    assert params["language"].default is None


def _protocol_members(proto: type) -> set[str]:
    """`typing.get_protocol_members` arrived in Python 3.13; older versions keep a helper."""
    if hasattr(typing, "get_protocol_members"):
        return set(typing.get_protocol_members(proto))
    return set(typing._get_protocol_attrs(proto))  # Python 3.11 and 3.12
