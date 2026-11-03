"""Turn the URL text a client wrote into path segments a route can be compared with.

Why: adapters keep URLs as written (`/api/users/${id}`, `BASE + "/users/" + id`,
`http://localhost:8000/api/users?x=1`). Matching needs one shape, so every spelling of
"a parameter" becomes the single segment `{}` and everything around the path is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARAM = "{}"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "testserver", "[::1]"})

_SCHEME_HOST = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]*)")
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}|\{[^{}]*\}")
_HOST_PLACEHOLDER = re.compile(r"^(?:\$\{[^}]*\}|\{[^{}]*\})(?=/|$)")
_QUOTED = re.compile(r'^(["\'`])(.*)\1$', re.DOTALL)
_BARE_NAME = re.compile(r"^[A-Za-z_$][\w$.]*(\(.*\))?$")


@dataclass(frozen=True, slots=True)
class ClientUrl:
    """A normalised client URL, or the reason it could not be normalised."""

    segments: tuple[str, ...] = ()
    host: str | None = None
    reason: str | None = None

    @property
    def has_params(self) -> bool:
        return any(PARAM in s for s in self.segments)


def normalise_client_url(url_text: str, url_kind: str) -> ClientUrl:
    """Segments of the request path; `reason` is set when the path is unknowable."""
    text = _expression_text(url_text) if url_kind == "dynamic" else url_text
    if text is None:
        return ClientUrl(reason="dynamic")
    host = None
    match = _SCHEME_HOST.match(text)
    if match:
        host, text = match.group(1), text[match.end():]
    else:
        text = _HOST_PLACEHOLDER.sub("", text, count=1) if not text.startswith("/") else text
    if host is not None and host.rsplit("@", 1)[-1].split(":")[0] not in LOCAL_HOSTS:
        return ClientUrl(host=host, reason="external_host")
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    text = _PLACEHOLDER.sub(PARAM, text)
    segments = tuple(s for s in text.split("/") if s)
    if not segments and not text:
        return ClientUrl(reason="dynamic")
    return ClientUrl(segments=segments, host=host)


def _expression_text(expression: str) -> str | None:
    """Text of `BASE + "/users/" + id`: quoted parts as written, bare names as parameters.

    A bare name first is a host prefix and is dropped. None when no quoted text is found.
    """
    pieces = [p.strip() for p in _split_plus(expression)]
    out: list[str] = []
    saw_text = False
    for index, piece in enumerate(pieces):
        quoted = _QUOTED.match(piece)
        if quoted:
            out.append(quoted.group(2))
            saw_text = True
        elif _BARE_NAME.match(piece) and index > 0:
            out.append(PARAM)
        elif index > 0:
            return None
    return "".join(out) if saw_text else None


def _split_plus(expression: str) -> list[str]:
    """Split on `+` outside quotes and brackets."""
    parts, depth, quote, current = [], 0, "", []
    for char in expression:
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "+" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def route_segments(path_pattern: str) -> tuple[str, ...]:
    """Segments of a server pattern like `/api/users/{id}`; every `{name}` becomes `{}`."""
    text = re.split(r"[?#]", path_pattern, maxsplit=1)[0]
    return tuple(s for s in _PLACEHOLDER.sub(PARAM, text).split("/") if s)
