"""The system prompt: what the repository is, which tools exist, and the citation rule."""

from __future__ import annotations

from collections import Counter

from codeatlas.llm import ToolSpec
from codeatlas.models import NodeKind, Snapshot
from codeatlas.store import GraphStore

MAX_PACKAGES_LISTED = 15


def describe_repository(store: GraphStore, snapshot: Snapshot) -> str:
    """Languages (with file counts) and packages of the snapshot, as plain lines."""
    files = store.files(snapshot.id)
    languages = Counter(f"{f.language} ({f.tier})" for f in files)
    packages = [n for n in store.nodes(snapshot.id) if n.kind is NodeKind.PACKAGE]
    lines = [
        f"Repository: {snapshot.repo}, snapshot {snapshot.id}, {len(files)} files.",
        "Languages: " + (", ".join(f"{k} x{v}" for k, v in sorted(languages.items())) or "none"),
    ]
    if packages:
        names = [f"{p.name} ({p.path})" for p in packages[:MAX_PACKAGES_LISTED]]
        more = len(packages) - len(names)
        lines.append("Packages: " + ", ".join(names) + (f", and {more} more" if more > 0 else ""))
    stopped = [name for name in snapshot.limits_hit if name != "max_file_bytes"]
    if stopped:
        lines.append("The index is incomplete; limits hit: " + ", ".join(stopped))
    return "\n".join(lines)


def system_prompt(store: GraphStore, snapshot: Snapshot, specs: list[ToolSpec]) -> str:
    """The full system prompt for one snapshot.

    Tools are named, not described: each request also carries the tool specs, so their
    descriptions here were sent twice on every step (D-50).
    """
    tools = ", ".join(s.name for s in specs)
    return f"""You answer questions about a code repository using a map built by static analysis.

{describe_repository(store, snapshot)}

Tools (call them; do not guess): {tools}.

Rules:
1. Every claim about the code must cite its evidence as `repo@sha:path:line`, copied from the
   `citation` field of a tool result, for example `{snapshot.id}:path/to/file.py:42`.
   Never invent a citation. If no tool result supports a claim, say you could not confirm it.
2. Edges carry a confidence below 1.0 when they are guesses. Say so when you rely on one.
3. Tool results can be cut short (`truncated: true`); say that the list may be incomplete.
4. You can read code but never run it. Tests are only listed, not executed.
5. Be brief. Find the key with search_symbols first when you only have a name.
"""
