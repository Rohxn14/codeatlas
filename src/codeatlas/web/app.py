"""The local web app: FastAPI routes over one CodeAtlas database.

The app only reads the database. It never clones, installs or runs anything from an
indexed repository, and every value from a repository reaches the page through Jinja's
autoescape, because names, paths and docstrings there are untrusted text.
"""

from __future__ import annotations

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
    # Overview facts per snapshot id. A snapshot never changes once written, so the first
    # count is kept for the life of the server; re-indexing with --force needs a restart.
    overviews: dict[str, dict[str, Any]] = {}

    def get_store() -> Iterator[GraphStore]:
        # SQLite connections belong to the thread that opened them, and FastAPI runs each
        # request on a worker thread, so a shared connection would fail.
        if not db_path.exists():
            raise HTTPException(503, f"no database at {db_path}: run `codeatlas index` first")
        with GraphStore(db_path) as store:
            yield store

    def get_snapshot(slug: str, store: GraphStore = Depends(get_store)) -> Snapshot:  # noqa: B008
        snapshot = find_snapshot(store, slug)
        if snapshot is None:
            raise HTTPException(404, f"no snapshot {slug!r} in {db_path}")
        return snapshot

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
    def overview(
        request: Request,
        snapshot: Snapshot = Depends(get_snapshot),  # noqa: B008
        store: GraphStore = Depends(get_store),  # noqa: B008
    ) -> Any:
        if snapshot.id not in overviews:
            saved = load_report(config, snapshot.id)
            overviews[snapshot.id] = build_overview(
                store, snapshot.id, saved.to_dict() if saved else None
            )
        return templates.TemplateResponse(
            request, "overview.html", {"o": overviews[snapshot.id], "snapshot": snapshot}
        )

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> Any:
        """Every error as a page, including a 404 for an address no route matches."""
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    return app
