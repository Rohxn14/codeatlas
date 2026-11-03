"""Choose which functions to mutate: called from somewhere, not a test, deterministic."""

from __future__ import annotations

import random
from dataclasses import dataclass

from codeatlas.models import EdgeKind, Node, NodeKind
from codeatlas.repo.test_conventions import classify
from codeatlas.store import GraphStore
from eval.mutants.mutate import PYTHON_LANGUAGES, TYPESCRIPT_LANGUAGES

MUTABLE_LANGUAGES = PYTHON_LANGUAGES | TYPESCRIPT_LANGUAGES


@dataclass(frozen=True, slots=True)
class Candidates:
    """The pool functions are sampled from, and how callers were found."""

    functions: list[Node]
    basis: str  # "calls-edges" or "raw-call-names"


def candidate_functions(store: GraphStore, snapshot_id: str) -> Candidates:
    """FUNCTION nodes with at least one caller, outside test files, sorted by key.

    A caller is a CALLS edge into the function. If the graph has no CALLS edges at all
    (no resolver registered for these languages yet), a function counts as called when
    another function's raw call has its name; the basis is recorded in the output.
    """
    nodes = store.nodes(snapshot_id)
    functions = [
        n
        for n in nodes
        if n.kind is NodeKind.FUNCTION
        and n.language in MUTABLE_LANGUAGES
        and classify(n.path, n.language) is None
    ]
    has_calls = any(e.kind is EdgeKind.CALLS for e in store.edges(snapshot_id))
    if has_calls:
        called = {e.dst_id for e in store.edges(snapshot_id) if e.kind is EdgeKind.CALLS}
        pool = [n for n in functions if n.id in called]
        basis = "calls-edges"
    else:
        callers: dict[str, set[str]] = {}
        for call, _ in store.raw_calls(snapshot_id):
            callers.setdefault(call.name, set()).add(call.caller_key)
        pool = [n for n in functions if callers.get(n.name, set()) - {n.key}]
        basis = "raw-call-names"
    return Candidates(sorted(pool, key=lambda n: n.key), basis)


def pick(candidates: list[Node], count: int, seed: int) -> list[Node]:
    """`count` functions chosen by `seed`; the same inputs always give the same list."""
    if count >= len(candidates):
        return list(candidates)
    chosen = random.Random(seed).sample(candidates, count)
    return sorted(chosen, key=lambda n: n.key)
