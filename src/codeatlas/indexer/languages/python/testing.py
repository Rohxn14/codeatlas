"""Which functions are tests, by the rules pytest and unittest use to collect them.

Detection is by naming alone, so it needs no import of the repository's code: a test
file is `test_*.py` or `*_test.py`; in it, a test is a module-level function, or a
method of a test class, whose name starts with `test`. A test class is named `Test*`
or derives from a `...TestCase` base, and may be nested only inside other test classes.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from codeatlas.indexer.languages.python.definitions import PyDefinition
from codeatlas.models import NodeKind


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def mark_tests(definitions: list[PyDefinition], path: str) -> None:
    """Turn test functions into TEST nodes with a pytest node id in `attrs["test_id"]`."""
    if not is_test_file(path):
        return
    for definition in definitions:
        if definition.kind is NodeKind.FUNCTION and _is_test(definition):
            definition.kind = NodeKind.TEST
            definition.attrs["test_id"] = _test_id(definition, path)


def _is_test(definition: PyDefinition) -> bool:
    if not definition.name.startswith("test"):
        return False
    return definition.parent is None or _is_test_class(definition.parent)


def _is_test_class(definition: PyDefinition) -> bool:
    if definition.kind is not NodeKind.CLASS:
        return False
    bases = definition.attrs.get("bases")
    last_segments = [str(b).rsplit(".", 1)[-1] for b in bases] if isinstance(bases, list) else []
    named_like_test = definition.name.startswith("Test")
    is_test_case = any(name.endswith("TestCase") for name in last_segments)
    if not (named_like_test or is_test_case):
        return False
    return definition.parent is None or _is_test_class(definition.parent)


def _test_id(definition: PyDefinition, path: str) -> str:
    """`path::Class::test_name`, from the plain names (no duplicate-key suffixes)."""
    names: list[str] = []
    current: PyDefinition | None = definition
    while current is not None:
        names.insert(0, current.name)
        current = current.parent
    return "::".join([path, *names])
