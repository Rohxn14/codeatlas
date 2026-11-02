"""Server endpoints declared with FastAPI or Flask decorators.

A decorator `@<router>.<verb>(path)` or `@<router>.route(path, methods=[...])` on a
function makes it a route handler. The framework comes from the strongest evidence in
the file: what `<router>` was created from (`FastAPI()`, `APIRouter()`, `Flask()`,
`Blueprint()`), then the decorator itself (`route` is Flask's, `api_route` FastAPI's),
then which framework the file imports, and FastAPI when nothing says otherwise (a
`views.py` that imports `app` from elsewhere still declares routes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.python.definitions import PyDefinition
from codeatlas.indexer.languages.python.syntax import (
    argument,
    callee_parts,
    keyword,
    line,
    plain_string,
    text,
    walk,
)
from codeatlas.models import RawImport, RawRoute

VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})

# Constructor (last segment of the callee) -> framework, and its prefix keyword.
_FACTORIES: dict[str, tuple[str, str | None]] = {
    "FastAPI": ("fastapi", None),
    "APIRouter": ("fastapi", "prefix"),
    "Flask": ("flask", None),
    "Blueprint": ("flask", "url_prefix"),
}
_FRAMEWORK_BY_DECORATOR = {"route": "flask", "api_route": "fastapi"}

_FLASK_PARAM = re.compile(r"<(?:[^<>:]+:)?([^<>:]+)>")  # <int:id> or <id>
_TYPED_PARAM = re.compile(r"\{([^{}:]+):[^{}]*\}")  # Starlette's {id:int} or {path:path}


@dataclass(frozen=True, slots=True)
class Router:
    """A router variable created in this file: what made it, and its path prefix."""

    framework: str
    prefix: str = ""


def collect_routes(
    root: TSNode,
    source: bytes,
    definitions: list[PyDefinition],
    imports: list[RawImport],
) -> list[RawRoute]:
    routers = _routers(root, source)
    imported = _imported_framework(imports)
    routes = []
    for definition in definitions:
        for decorator in definition.decorators:
            routes.extend(_routes_from(decorator, definition, source, routers, imported))
    return routes


def normalise_path(path: str) -> str:
    """`/users/<int:id>`, `/users/<id>` and `/users/{id:int}` all become `/users/{id}`."""
    return _TYPED_PARAM.sub(r"{\1}", _FLASK_PARAM.sub(r"{\1}", path))


def _routes_from(
    decorator: TSNode,
    definition: PyDefinition,
    source: bytes,
    routers: dict[str, Router],
    imported: str | None,
) -> list[RawRoute]:
    call = decorator.named_children[0] if decorator.named_child_count else None
    if call is None or call.type != "call":
        return []
    parts = callee_parts(call, source)
    if parts is None or parts[2] is None:
        return []
    _, decorator_name, router_name = parts
    if decorator_name not in VERBS and decorator_name not in _FRAMEWORK_BY_DECORATOR:
        return []
    router = routers.get(router_name)
    framework = (
        (router.framework if router else None)
        or _FRAMEWORK_BY_DECORATOR.get(decorator_name)
        or imported
        or "fastapi"
    )
    path = plain_string(argument(call, 0, "rule" if framework == "flask" else "path"), source)
    if path is None:  # a path built at runtime cannot be matched by the linker
        return []
    pattern = normalise_path(_join(router.prefix if router else "", path))
    return [
        RawRoute(definition.key, method, pattern, framework, router_name, line(decorator))
        for method in _methods(call, decorator_name, source)
    ]


def _methods(call: TSNode, decorator_name: str, source: bytes) -> list[str]:
    """`@app.get` is GET; `route`/`api_route` list theirs, defaulting to GET like both do."""
    if decorator_name in VERBS:
        return [decorator_name.upper()]
    methods = keyword(call, "methods")
    if methods is None:
        return ["GET"]
    if methods.type not in ("list", "tuple", "set"):
        return ["ANY"]  # a variable: the methods are not known statically
    names = [plain_string(m, source) for m in methods.named_children]
    known = [n.upper() for n in names if n]
    return known if known and len(known) == len(names) else ["ANY"]


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path or path == "/":
        return prefix.rstrip("/") + path
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _routers(root: TSNode, source: bytes) -> dict[str, Router]:
    """`name = APIRouter(prefix="/api")` and the like, anywhere in the file."""
    routers: dict[str, Router] = {}
    for node in walk(root):
        if node.type != "assignment":
            continue
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None or left.type != "identifier" or right.type != "call":
            continue
        parts = callee_parts(right, source)
        factory = _FACTORIES.get(parts[1]) if parts else None
        if factory is None:
            continue
        framework, prefix_keyword = factory
        prefix = plain_string(keyword(right, prefix_keyword), source) if prefix_keyword else None
        routers[text(left, source)] = Router(framework, prefix or "")
    return routers


def _imported_framework(imports: list[RawImport]) -> str | None:
    """The one web framework the file imports, if exactly one."""
    found = {
        root
        for i in imports
        if (root := i.target.split(".", 1)[0]) in ("fastapi", "flask") and i.level == 0
    }
    return found.pop() if len(found) == 1 else None
