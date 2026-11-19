"""Names in a question that look like code, looked up before the model's first step.

In every real run of Nov 19, the model's first steps went on finding a symbol the question
had already named: 5 steps for `contracts.validate`, up to 9 for `classify_pit_passage`
(gpt-oss-20b repeated the same search). The lookup is local and takes milliseconds, so
the question is sent with what it names already found: each symbol's key, for the
tools, and its citation, for the answer.
"""

from __future__ import annotations

import re
from typing import Any

from codeatlas.agent.tools import ToolSet

MAX_NAMES = 3  # names looked up per question
MAX_FOUND = 5  # exact matches shown per name
MAX_SIGNATURE = 120
# A word of letters, digits and underscores, possibly dotted: `contracts.validate`.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_BACKTICKED = re.compile(r"`([^`\s]+)`")
# A dotted word ending like this is a file name (`main.py`), not a symbol.
_FILE_ENDINGS = frozenset({"py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "md", "rst", "txt",
                           "json", "toml", "yaml", "yml", "rs", "go", "java", "kt", "rb",
                           "php", "c", "h", "cc", "cpp", "hpp", "cs", "swift", "scala",
                           "lua", "ex", "exs", "html", "css", "sql", "sh"})
LEADS_INTRO = "Looked up before you start (search_symbols, exact matches only):"
# The first wording ("Start from these keys") led the model to cite keys
# (`cleaner.py::build_silver`) instead of citations in its answer (Nov 19).
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


def look_up(question: str, tools: ToolSet) -> list[dict[str, Any]]:
    """Each code-like name with its exact matches; names that match nothing are left out."""
    leads = []
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
                         f"{symbol['citation']}" + (f" `{signature}`" if signature else ""))
        if lead["more"]:
            lines.append(f"  ({lead['more']} more matches for {lead['name']} not shown)")
    lines.append(LEADS_OUTRO)
    return "\n".join(lines)
