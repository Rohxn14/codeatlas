"""Text-level mutations of one function: break its body without any other change.

Python: the body becomes `raise RuntimeError("mutant")`. TypeScript/JavaScript:
`throw new Error("mutant");` is inserted as the first statement. Both work on text and
return `None` plus a reason when the function has a shape they do not handle (a one-line
body, an expression-bodied arrow), so the caller can skip it and say why.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

PYTHON_MUTATION = 'raise RuntimeError("mutant")'
TYPESCRIPT_MUTATION = 'throw new Error("mutant");'
PYTHON_LANGUAGES = frozenset({"python"})
TYPESCRIPT_LANGUAGES = frozenset({"typescript", "tsx", "javascript", "jsx"})


@dataclass(frozen=True, slots=True)
class Mutation:
    """The mutated file text, or why no mutation was made."""

    text: bytes | None
    description: str
    reason: str = ""


def mutate_function(
    language: str, source: bytes, name: str, start_line: int, end_line: int, end_col: int
) -> Mutation:
    """Dispatch on the language; lines are 1-based and `end_col` is exclusive, as in `Span`."""
    if language in PYTHON_LANGUAGES:
        return mutate_python(source, name, start_line, end_line)
    if language in TYPESCRIPT_LANGUAGES:
        return mutate_typescript(source, start_line, end_line, end_col)
    return Mutation(None, "", f"no mutator for language {language!r}")


def mutate_python(source: bytes, name: str, start_line: int, end_line: int) -> Mutation:
    """Replace the whole body of the function called `name` that sits inside the span."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return Mutation(None, "", f"file does not parse: {exc}")
    found = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and n.name == name
        and start_line <= n.lineno <= end_line
    ]
    if not found:
        return Mutation(None, "", f"no def {name!r} inside lines {start_line}-{end_line}")
    func = min(found, key=lambda n: (n.end_lineno or 0) - n.lineno)
    first = func.body[0]
    if first.lineno == func.lineno:
        return Mutation(None, "", "the body is on the same line as the def")
    lines = source.splitlines(keepends=True)
    head = lines[first.lineno - 1]
    indent = head[: len(head) - len(head.lstrip())]
    newline = b"\r\n" if head.endswith(b"\r\n") else b"\n"
    replacement = indent + PYTHON_MUTATION.encode() + newline
    last = func.end_lineno or first.lineno
    mutated = b"".join([*lines[: first.lineno - 1], replacement, *lines[last:]])
    return Mutation(mutated, f"{name}: body replaced by {PYTHON_MUTATION}")


def mutate_typescript(source: bytes, start_line: int, end_line: int, end_col: int) -> Mutation:
    """Insert a throw after the `{` whose matching `}` is the last character of the span."""
    starts = [0]
    for i, byte in enumerate(source):
        if byte == 0x0A:
            starts.append(i + 1)
    if end_line > len(starts) or start_line > len(starts):
        return Mutation(None, "", "span is outside the file")
    begin, end = starts[start_line - 1], starts[end_line - 1] + end_col
    if end > len(source) or end <= begin or source[end - 1 : end] != b"}":
        return Mutation(None, "", "the function has no block body ending in }")
    opener = _opener_of_closing_brace(source, begin, end - 1)
    if opener is None:
        return Mutation(None, "", "could not find the opening brace of the body")
    insert = b" " + TYPESCRIPT_MUTATION.encode()
    mutated = source[: opener + 1] + insert + source[opener + 1 :]
    return Mutation(mutated, f"first statement replaced by {TYPESCRIPT_MUTATION}")


def _opener_of_closing_brace(source: bytes, begin: int, closing: int) -> int | None:
    """Offset of the `{` matching the `}` at `closing`, skipping strings and comments."""
    stack: list[int] = []
    i = begin
    while i <= closing:
        c = source[i : i + 1]
        two = source[i : i + 2]
        if two == b"//":
            i = _skip_to(source, i, b"\n")
        elif two == b"/*":
            i = _skip_to(source, i + 2, b"*/") + 1
        elif c in (b'"', b"'", b"`"):
            i = _skip_string(source, i, c)
        elif c == b"{":
            stack.append(i)
        elif c == b"}":
            if not stack:
                return None
            opened = stack.pop()
            if i == closing:
                return opened
        i += 1
    return None


def _skip_to(source: bytes, i: int, marker: bytes) -> int:
    found = source.find(marker, i)
    return len(source) if found < 0 else found


def _skip_string(source: bytes, i: int, quote: bytes) -> int:
    """Offset of the closing quote of the string that opens at `i`."""
    i += 1
    while i < len(source):
        if source[i : i + 1] == b"\\":
            i += 2
            continue
        if source[i : i + 1] == quote:
            return i
        i += 1
    return len(source)
