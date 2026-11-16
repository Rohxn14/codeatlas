"""The local web app: FastAPI routes over one CodeAtlas database.

The app only reads the database. It never clones, installs or runs anything from an
indexed repository, and every value from a repository reaches the page through Jinja's
autoescape, because names, paths and docstrings there are untrusted text.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from codeatlas import __version__
from codeatlas.config import Config
from codeatlas.indexer.pipeline.index import load_report
from codeatlas.models import Snapshot
from codeatlas.store import GraphStore
from codeatlas.web.confidence import MEANING
from codeatlas.web.data import Loaded, load_snapshot
from codeatlas.web.diagram import arrow_edges, build_diagram, crumbs
from codeatlas.web.overview import build_overview
from codeatlas.web.pages import MAX_HITS, file_page, search, symbol_page
from codeatlas.web.source import MAX_LINES, checkout_root, read_lines

_HERE = Path(__file__).parent
MAX_SYMBOL_LINES = 400


def snapshot_slug(snapshot_id: str) -> str:
    """A snapshot id as one URL path segment: `owner/name@sha` becomes `owner~name@sha`."""
    return snapshot_id.replace("/", "~")


def find_snapshot(store: GraphStore, slug: str) -> Snapshot | None:
    """The snapshot a slug stands for. Compared slug to slug, so `~` in a name is safe."""
    return next((s for s in store.snapshots() if snapshot_slug(s.id) == slug), None)


def percent(value: float | None) -> str:
    """`0.553` as `55%`; a dash when there was nothing to take a share of."""
    return "–" if value is None else f"{value * 100:.0f}%"


def thousands(value: int) -> str:
    return f"{value:,}"


def create_app(db_path: Path, config: Config) -> FastAPI:
    """The app for one database. Each request opens its own connection (see `open_store`)."""
    app = FastAPI(title="CodeAtlas", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.filters.update(percent=percent, thousands=thousands, slug=snapshot_slug)
    templates.env.globals.update(version=__version__, level_meaning=MEANING)
    # Snapshots already read, by slug. A snapshot never changes once written, so it is read
    # once and kept for the life of the server; re-indexing with --force needs a restart.
    cache: dict[str, Loaded] = {}
    cache_lock = threading.Lock()

    def open_store() -> GraphStore:
        """A connection for the request that asks, to be used in a `with` block.

        A SQLite connection belongs to the thread that opened it, and requests that
        arrive together run on different worker threads. So a handler opens its own
        connection and closes it itself. A FastAPI dependency would not do: it can be
        run on a different thread from the handler it serves.
        """
        if not db_path.exists():
            raise HTTPException(503, f"no database at {db_path}: run `codeatlas index` first")
        return GraphStore(db_path)

    def get_loaded(slug: str) -> Loaded:
        """The snapshot a page is about, read on first use. The lock stops two requests
        arriving together from both reading the same snapshot."""
        with cache_lock:
            if slug not in cache:
                with open_store() as store:
                    snapshot = find_snapshot(store, slug)
                    if snapshot is None:
                        raise HTTPException(404, f"no snapshot {slug!r} in {db_path}")
                    saved = load_report(config, snapshot.id)
                    cache[slug] = load_snapshot(
                        store, snapshot, saved.to_dict() if saved else None
                    )
            return cache[slug]

    def page(request: Request, name: str, loaded: Loaded, tab: str, **values: Any) -> Any:
        return templates.TemplateResponse(
            request, name,
            {"snapshot": loaded.snapshot, "tab": tab,
             "base": f"/s/{snapshot_slug(loaded.snapshot.id)}", **values},
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Any:
        """With one snapshot, go straight to it; otherwise list them."""
        with open_store() as store:
            snapshots = store.snapshots()
        if len(snapshots) == 1:
            return RedirectResponse(f"/s/{snapshot_slug(snapshots[0].id)}/")
        return templates.TemplateResponse(request, "snapshots.html", {"snapshots": snapshots})

    @app.get("/snapshots", response_class=HTMLResponse)
    def snapshot_list(request: Request) -> Any:
        with open_store() as store:
            snapshots = store.snapshots()
        return templates.TemplateResponse(request, "snapshots.html", {"snapshots": snapshots})

    @app.get("/s/{slug}/", response_class=HTMLResponse)
    def map_page(
        request: Request,
        slug: str,
        focus: str = "",
        src: str = "",
        dst: str = "",
        pick: str = "",
        all: bool = False,  # noqa: A002  (the name is the address parameter `?all=1`)
    ) -> Any:
        """The architecture diagram of one folder. `src` and `dst` open one arrow, `pick`
        keeps one box's arrows, `all` draws every arrow of a crowded diagram."""
        loaded = get_loaded(slug)
        diagram = build_diagram(loaded.files, loaded.links, focus, pick, all)
        if focus and not diagram["exists"]:
            raise HTTPException(404, f"no folder {focus!r} in {loaded.snapshot.id}")
        picked = arrow_edges(loaded.links, loaded.nodes, focus, src, dst) if src and dst else None
        return page(request, "map.html", loaded, "map", d=diagram, picked=picked)

    @app.get("/s/{slug}/coverage", response_class=HTMLResponse)
    def coverage(request: Request, slug: str) -> Any:
        loaded = get_loaded(slug)
        if loaded.overview is None:
            loaded.overview = build_overview(loaded)
        return page(request, "coverage.html", loaded, "coverage", o=loaded.overview)

    @app.get("/s/{slug}/file", response_class=HTMLResponse)
    def file_view(request: Request, slug: str, path: str) -> Any:
        """One file: what it uses, what uses it, its symbols and its source."""
        loaded = get_loaded(slug)
        facts = file_page(loaded, path)
        if facts is None:
            raise HTTPException(404, f"no file {path!r} in {loaded.snapshot.id}")
        lines, why_not = read_lines(checkout_root(loaded.snapshot, config), path)
        cut = lines is not None and len(lines) > MAX_LINES
        return page(request, "file.html", loaded, "map", f=facts, path=path,
                    crumbs=crumbs(path), lines=(lines or [])[:MAX_LINES], cut=cut,
                    total_lines=len(lines or []), why_not=why_not)

    @app.get("/s/{slug}/symbol", response_class=HTMLResponse)
    def symbol_view(request: Request, slug: str, key: str) -> Any:
        """One symbol: its source, what it uses, what uses it, calls that got no edge."""
        loaded = get_loaded(slug)
        facts = symbol_page(loaded, key)
        if facts is None:
            raise HTTPException(404, f"no symbol {key!r} in {loaded.snapshot.id}")
        node = facts["node"]
        lines, why_not = read_lines(checkout_root(loaded.snapshot, config), node.path)
        start = node.span.start_line
        end = min(node.span.end_line, start + MAX_SYMBOL_LINES - 1)
        body = (lines or [])[start - 1:end]
        return page(request, "symbol.html", loaded, "map", y=facts, node=node,
                    crumbs=crumbs(node.path), body=body, start=start,
                    cut=node.span.end_line > end, why_not=why_not)

    @app.get("/s/{slug}/search", response_class=HTMLResponse)
    def search_view(request: Request, slug: str, q: str = "") -> Any:
        """Symbols and files by name, docstring or path."""
        loaded = get_loaded(slug)
        with open_store() as store:
            ranked = [node for node, _ in store.search_text(loaded.snapshot.id, q, k=MAX_HITS)]
        hits = search(loaded, ranked, q) if q.strip() else []
        return page(request, "search.html", loaded, "search", q=q, hits=hits)

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> Any:
        """Every error as a page, including a 404 for an address no route matches."""
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    return app
