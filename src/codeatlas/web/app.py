"""The local web app: FastAPI routes over one CodeAtlas database.

The app only reads the database. It never clones, installs or runs anything from an
indexed repository, and every value from a repository reaches the page through Jinja's
autoescape, because names, paths and docstrings there are untrusted text.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
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
from codeatlas.web.diagram import arrow_edges, build_diagram
from codeatlas.web.overview import build_overview

_HERE = Path(__file__).parent


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
    """The app for one database. Each request opens its own connection (see `get_store`)."""
    app = FastAPI(title="CodeAtlas", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.filters.update(percent=percent, thousands=thousands, slug=snapshot_slug)
    templates.env.globals.update(version=__version__, level_meaning=MEANING)
    # Snapshots already read, by id. A snapshot never changes once written, so it is read
    # once and kept for the life of the server; re-indexing with --force needs a restart.
    cache: dict[str, Loaded] = {}
    cache_lock = threading.Lock()

    def get_store() -> Iterator[GraphStore]:
        # SQLite connections belong to the thread that opened them, and FastAPI runs each
        # request on a worker thread, so a shared connection would fail.
        if not db_path.exists():
            raise HTTPException(503, f"no database at {db_path}: run `codeatlas index` first")
        with GraphStore(db_path) as store:
            yield store

    def get_loaded(slug: str, store: GraphStore = Depends(get_store)) -> Loaded:  # noqa: B008
        """The snapshot a page is about, read on first use. The lock stops two requests
        arriving together from both reading the same snapshot."""
        snapshot = find_snapshot(store, slug)
        if snapshot is None:
            raise HTTPException(404, f"no snapshot {slug!r} in {db_path}")
        with cache_lock:
            if snapshot.id not in cache:
                saved = load_report(config, snapshot.id)
                cache[snapshot.id] = load_snapshot(
                    store, snapshot, saved.to_dict() if saved else None
                )
            return cache[snapshot.id]

    def page(request: Request, name: str, loaded: Loaded, tab: str, **values: Any) -> Any:
        return templates.TemplateResponse(
            request, name, {"snapshot": loaded.snapshot, "tab": tab, **values}
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, store: GraphStore = Depends(get_store)) -> Any:  # noqa: B008
        """With one snapshot, go straight to it; otherwise list them."""
        snapshots = store.snapshots()
        if len(snapshots) == 1:
            return RedirectResponse(f"/s/{snapshot_slug(snapshots[0].id)}/")
        return templates.TemplateResponse(request, "snapshots.html", {"snapshots": snapshots})

    @app.get("/snapshots", response_class=HTMLResponse)
    def snapshot_list(request: Request, store: GraphStore = Depends(get_store)) -> Any:  # noqa: B008
        return templates.TemplateResponse(
            request, "snapshots.html", {"snapshots": store.snapshots()}
        )

    @app.get("/s/{slug}/", response_class=HTMLResponse)
    def map_page(
        request: Request,
        loaded: Loaded = Depends(get_loaded),  # noqa: B008
        focus: str = "",
        src: str = "",
        dst: str = "",
        pick: str = "",
        all: bool = False,  # noqa: A002  (the name is the address parameter `?all=1`)
    ) -> Any:
        """The architecture diagram of one folder. `src` and `dst` open one arrow, `pick`
        keeps one box's arrows, `all` draws every arrow of a crowded diagram."""
        diagram = build_diagram(loaded.files, loaded.links, focus, pick, all)
        if focus and not diagram["exists"]:
            raise HTTPException(404, f"no folder {focus!r} in {loaded.snapshot.id}")
        picked = arrow_edges(loaded.links, loaded.nodes, focus, src, dst) if src and dst else None
        return page(request, "map.html", loaded, "map", d=diagram, picked=picked)

    @app.get("/s/{slug}/coverage", response_class=HTMLResponse)
    def coverage(request: Request, loaded: Loaded = Depends(get_loaded)) -> Any:  # noqa: B008
        if loaded.overview is None:
            loaded.overview = build_overview(loaded)
        return page(request, "coverage.html", loaded, "coverage", o=loaded.overview)

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> Any:
        """Every error as a page, including a 404 for an address no route matches."""
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    return app
