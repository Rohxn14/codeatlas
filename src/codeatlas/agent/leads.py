"""Names in a question that look like code, looked up before the model's first step.

In every real run of Nov 19, the model's first steps went on finding a symbol the question
had already named: 5 steps for `contracts.validate`, up to 9 for `classify_pit_passage`
(gpt-oss-20b repeated the same search). The lookup is local and takes milliseconds, so
the question is sent with what it names already found: each symbol's key, for the
tools, and its citation, for the answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from codeatlas.agent.tools import ToolSet
from codeatlas.models import NodeKind

MAX_NAMES = 3  # names looked up per question
MAX_FOUND = 5  # exact matches shown per name
MAX_SIGNATURE = 120
# A word of letters, digits and underscores, possibly dotted: `contracts.validate`.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_BACKTICKED = re.compile(r"`([^`\s]+)`")
_FILE_WORD = re.compile(r"[\w./-]*\w")
# A dotted word ending like this is a file name (`main.py`), not a symbol.
_FILE_ENDINGS = frozenset({"py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "md", "rst", "txt",
                           "json", "toml", "yaml", "yml", "rs", "go", "java", "kt", "rb",
                           "php", "c", "h", "cc", "cpp", "hpp", "cs", "swift", "scala",
                           "lua", "ex", "exs", "html", "css", "sql", "sh"})
LEADS_INTRO = "Looked up before you start (search_symbols, exact matches only):"
# The first wording ("Start from these keys") led the model to cite keys
# (`cleaner.py::build_silver`) instead of citations in its answer (Nov 19).
EARLIER_MARK = " (named in an earlier question)"
LEADS_OUTRO = ("Give these keys to the tools instead of searching for them again. In the "
               "answer, cite places by their citation (repo@sha:path:line), never by key.")


def code_names(question: str) -> list[str]:
    """Words of the question that look like code, in order, at most MAX_NAMES.

    Code-like: written in backticks, or dotted (`contracts.validate`), snake_case
    (`classify_pit_passage`) or camelCase (`createUser`, `UserService`). Plain words never
    are, so an ordinary question looks nothing up.
    """
    names: list[str] = []
    candidates = _BACKTICKED.findall(question) + _WORD.findall(question)
    for word in candidates:
        word = word.strip(".")
        if _looks_like_code(word) and word.lower() not in {n.lower() for n in names}:
            names.append(word)
    return names[:MAX_NAMES]


def _looks_like_code(word: str) -> bool:
    parts = word.split(".")
    if len(word) < 3 or any(len(p) < 2 for p in parts):
        return False  # "e.g", "a.b", "x"
    if len(parts) > 1:
        return parts[-1].lower() not in _FILE_ENDINGS
    inner = word.strip("_")
    return "_" in inner or re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", word) is not None


def file_names(question: str, tools: ToolSet) -> list[str]:
    """Files the question names by file name or path: `.gitignore` (also as `gitignore`),
    `requirements.txt`, `src/main.py`. Only a name that one file has, so a plain word never
    becomes a lead."""
    paths: dict[str, list[str]] = {}
    for node in tools.context.store.nodes(tools.context.snapshot_id):
        if node.kind is NodeKind.MODULE:
            name = node.path.rsplit("/", 1)[-1].lower()
            names = {node.path.lower(), name}
            if name.startswith(".") and "." not in name[1:]:
                names.add(name[1:])
            for each in names:
                paths.setdefault(each, []).append(node.path)
    found: list[str] = []
    for word in _FILE_WORD.findall(question.replace("\\", "/")):
        match = paths.get(word.lower().rstrip("."), [])
        if len(match) == 1 and match[0] not in found:
            found.append(match[0])
    return found


def look_up(question: str, tools: ToolSet, earlier: Sequence[str] = ()
            ) -> list[dict[str, Any]]:
    """Each code-like name with its exact matches; names that match nothing are left out.

    A follow-up often names nothing ("and who calls it?"): its subject is in a question
    before it. So the newest of the `earlier` questions that names something adds its leads
    too, marked `earlier`, while there is room (MAX_NAMES in all). This is what the owner's
    claim verifier does with a model call that rewrites the question; here it is a lookup
    (D-64).
    """
    leads = _look_up(question, tools)
    named = {lead["name"].lower() for lead in leads}
    for text in reversed(earlier):
        found = _look_up(text, tools)
        if found:
            room = max(0, MAX_NAMES - len(leads))
            new = [lead for lead in found if lead["name"].lower() not in named]
            leads += [{**lead, "earlier": True} for lead in new[:room]]
            break
    return leads


def _look_up(question: str, tools: ToolSet) -> list[dict[str, Any]]:
    leads = []
    for path in file_names(question, tools)[:MAX_NAMES]:
        result = tools.call("search_symbols", {"name": path, "kind": "file", "limit": 50})
        exact = [s for s in result["symbols"] if s["path"] == path]
        leads.append({"name": path, "symbols": exact[:1], "more": 0})
    for name in code_names(question):
        # Exact matches come first, so 50 (the most the tool returns) counts them all
        # but in a very large repository.
        result = tools.call("search_symbols", {"name": name, "limit": 50})
        exact = [s for s in result.get("symbols", []) if s.get("match") == "exact"]
        if exact:
            leads.append({"name": name, "symbols": exact[:MAX_FOUND],
                          "more": len(exact) - min(len(exact), MAX_FOUND)})
    return leads


def leads_text(leads: list[dict[str, Any]]) -> str:
    """The lines added to the question, or "" when there are none."""
    if not leads:
        return ""
    lines = ["", "", LEADS_INTRO]
    for lead in leads:
        for symbol in lead["symbols"]:
            signature = (symbol.get("signature") or "")[:MAX_SIGNATURE]
            lines.append(f"- {lead['name']}: {symbol['key']} ({symbol['kind']}) "
                         f"{symbol['citation']}" + (f" `{signature}`" if signature else "")
                         + (EARLIER_MARK if lead.get("earlier") else ""))
        if lead["more"]:
            lines.append(f"  ({lead['more']} more matches for {lead['name']} not shown)")
    lines.append(LEADS_OUTRO)
    return "\n".join(lines)
