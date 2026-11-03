"""Turn the URL text a client wrote into path segments a route can be compared with.

Why: adapters keep URLs as written (`/api/users/${id}`, `BASE + "/users/" + id`,
`http://localhost:8000/api/users?x=1`). Matching needs one shape, so every spelling of
"a parameter" becomes the single segment `{}` and everything around the path is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

PARAM = "{}"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "testserver", "::1"})
# Client name prefix for a call through an imported name that may be an axios instance:
# `axios:http` is `http.post(...)` with `http` imported. The linker finds the base URL.
IMPORTED_AXIOS = "axios:"

_LITERAL, _TEMPLATE, _DYNAMIC = "literal", "template", "dynamic"
_KIND_RANK = {_LITERAL: 0, _TEMPLATE: 1, _DYNAMIC: 2}

# `scheme://host` or protocol-relative `//host`.
_SCHEME_HOST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:)?//([^/?#]*)")
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}|\{[^{}]*\}")
_LEADING_PARAM = re.compile(r"^\{\}(?=/|$)")
_QUOTED = re.compile(r'^(["\'`])(.*)\1$', re.DOTALL)
# `id`, `user.id`, `ids[0]`, `row["id"]`, `getId()`: a value, so one parameter.
_BARE_NAME = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[\w$]+|\[[^\]]*\])*(\(.*\))?$")


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
    """Segments of the request path; `reason` is set when the path is unknowable.

    Placeholders become `{}` first, so a `?` or `#` inside `${...}` cannot cut the path
    and a placeholder host (`http://${API_HOST}/x`) is recognised as one.
    """
    text = _expression_text(url_text) if url_kind == _DYNAMIC else url_text
    if text is None:
        return ClientUrl(reason="dynamic")
    text = _PLACEHOLDER.sub(PARAM, text)
    host = None
    match = _SCHEME_HOST.match(text)
    if match:
        host, text = match.group(1), text[match.end():]
    elif not text.startswith("/"):
        text = _LEADING_PARAM.sub("", text, count=1)  # `${BASE}/users`: a host prefix
    if host is not None and not is_local_host(host):
        return ClientUrl(host=host, reason="external_host")
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    segments = tuple(s for s in text.split("/") if s)
    if not segments and not text:
        return ClientUrl(reason="dynamic")
    return ClientUrl(segments=segments, host=host)


def is_local_host(netloc: str) -> bool:
    """True for a loopback or test host, and for a placeholder (`${API_HOST}:8000`).

    A placeholder host is configuration, almost always pointing at this repository's own
    server in development, so it is treated as local rather than external.
    """
    if PARAM in netloc:
        return True
    try:
        hostname = urlsplit(f"//{netloc}").hostname
    except ValueError:  # a malformed `[` bracket
        return False
    return hostname in LOCAL_HOSTS


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


@lru_cache(maxsize=1024)
def segment_pattern(segment: str) -> re.Pattern[str]:
    """A route segment as a regular expression: `{}.json` matches `report.json`."""
    pieces = (re.escape(p) for p in segment.split(PARAM))
    return re.compile("[^/]+".join(pieces) + r"\Z")


def join_client_url(base: str, base_kind: str, url: str, url_kind: str) -> tuple[str, str]:
    """Join an axios base URL to a request URL: `(text, kind)`.

    Strings and templates are joined as text (`/api` + `/users/${id}`). When either
    part is dynamic the result is an expression, so both are written as one:
    `"/api" + "/users/" + id`. Used by the TypeScript adapter for a local instance and
    by the linker for an imported one.
    """
    if not base:
        return url, url_kind
    kind = max(base_kind, url_kind, key=lambda k: _KIND_RANK.get(k, 2))
    if kind != _DYNAMIC:
        return join_url(base, url), kind
    return f"{_expression(base, base_kind)} + {_expression(url, url_kind)}", kind


def join_url(base: str, path: str) -> str:
    """Join with exactly one `/`: `https://x.io/api/` + `/users` is `https://x.io/api/users`.

    An absolute request URL ignores the base, as axios does.
    """
    if not path:
        return base
    if path.startswith(("http://", "https://")):
        return path
    if base.endswith("/") and path.startswith("/"):
        return base + path[1:]
    if not base.endswith("/") and not path.startswith(("/", "?", "#")):
        return base + "/" + path
    return base + path


def _expression(text: str, kind: str) -> str:
    quote = {_LITERAL: '"', _TEMPLATE: "`"}.get(kind, "")
    return f"{quote}{text}{quote}"
