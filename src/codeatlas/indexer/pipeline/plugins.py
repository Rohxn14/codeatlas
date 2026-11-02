"""Where resolvers and linkers plug into the pipeline, in the style of `DEEP_ADAPTERS`.

Each entry is `"name": "module.path:ClassName"`; the class is constructed with no
arguments and satisfies the contract's `Resolver` or `Linker` protocol. Wave 2 tasks add
one line each, so parallel sessions never edit the same line.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

# Filled in ahead of the Wave 2 tasks that build them, so parallel sessions never edit
# this file. Until a task merges, its entry fails to import and the build reports it as
# "not loaded", which is true.
RESOLVERS: dict[str, str] = {
    "python": "codeatlas.indexer.languages.python.resolver:PythonResolver",  # T06
    "typescript": "codeatlas.indexer.languages.typescript.resolver:TypeScriptResolver",  # T07
    "structural": "codeatlas.indexer.structural:StructuralResolver",  # T16
}
LINKERS: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class PluginFailure:
    """A plugin that could not be loaded; reported, never fatal."""

    name: str
    error: str


def load_plugins(table: dict[str, str]) -> tuple[list[tuple[str, object]], list[PluginFailure]]:
    """Instances of every plugin in `table` that imports and constructs, in name order.

    A broken plugin must not stop an index: it is skipped and named in the failures, so
    the report says which edges are missing and why.
    """
    loaded: list[tuple[str, object]] = []
    failures: list[PluginFailure] = []
    for name, target in sorted(table.items()):
        module_name, _, class_name = target.partition(":")
        try:
            cls = getattr(importlib.import_module(module_name), class_name)
            loaded.append((name, cls()))
        except Exception as exc:  # any import or constructor error, by design
            failures.append(PluginFailure(name, f"{type(exc).__name__}: {exc}"))
    return loaded, failures
