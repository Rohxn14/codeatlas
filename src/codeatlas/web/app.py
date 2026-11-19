"""The local web app: FastAPI routes over one CodeAtlas database.

The pages read the database. Two actions change it: indexing a repository (the same
`index_repository` the command line calls, on a background thread) and removing a
snapshot. A third, asking a question, calls a language model with the keys set in the
shell. All three are switched off with `read_only`, and all three refuse a form posted
from another website. The app never installs or runs anything from a repository, and
every value from a repository reaches the page through Jinja's autoescape, because
names, paths and docstrings there are untrusted text.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from codeatlas import __version__
from codeatlas.agent.loop import Answer, OnStep
from codeatlas.config import Config
from codeatlas.impact.engine import LOAD_KINDS, ImpactEngine
from codeatlas.impact.evaluate import all_test_files
from codeatlas.impact.models import Change
from codeatlas.indexer.intake import IntakeError, looks_like_url, parse_repo_url
from codeatlas.indexer.pipeline.index import index_repository, load_report, report_path
from codeatlas.llm.client import OnWait
from codeatlas.models import Snapshot
from codeatlas.store import GraphStore
from codeatlas.web.asks import (
    MAX_QUESTION_CHARS,
    Questions,
    TooManyQuestions,
    answer_parts,
    step_rows,
)
from codeatlas.web.changes import (
    MAX_DIFF_BYTES,
    ChangeError,
    ChangeSet,
    at_snapshot,
    commit_changes,
    pasted_changes,
    recent_commits,
    worktree_changes,
)
from codeatlas.web.confidence import MEANING
from codeatlas.web.data import Loaded, load_snapshot
from codeatlas.web.diagram import arrow_edges, build_diagram, crumbs
from codeatlas.web.impact_page import impact_view
from codeatlas.web.jobs import Job, Jobs, TooManyJobs
from codeatlas.web.overview import build_overview
from codeatlas.web.pages import MAX_DOC_HITS, MAX_HITS, file_page, search, symbol_page
from codeatlas.web.source import MAX_LINES, checkout_root, read_lines

_HERE = Path(__file__).parent
MAX_SYMBOL_LINES = 400
LLM_KEYS = ("GROQ_API_KEY", "GEMINI_API_KEY")


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


async def posted_form(request: Request) -> dict[str, str]:
    """The fields of a posted form, each with its first value.

    Read by hand because FastAPI's own form reader needs one more package. This is a
    dependency, not part of the handler, because reading a request body must be awaited
    and the handlers are plain functions.
    """
    body = await request.body()
    if len(body) > MAX_DIFF_BYTES:
        raise HTTPException(413, f"the form is larger than {MAX_DIFF_BYTES:,} bytes")
    fields = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {name: values[0] for name, values in fields.items()}


# Made once here: a `Depends(...)` call may not sit in a parameter default (ruff B008).
POSTED_FORM = Depends(posted_form)


def posted_diff(form: dict[str, str] = POSTED_FORM) -> str:
    return form.get("diff", "")


def from_this_app(request: Request) -> None:
    """Refuse a form that another website posted.

    Any page open in the same browser can post a form to `http://127.0.0.1:8765/index`.
    A browser adds an `Origin` header to such a post, naming the site the form is on;
    when that is not this app's own address the request is refused.
    """
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "this form was posted from another website")
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(403, "this form was posted from another website")


def checked_source(text: str) -> str:
    """What someone typed into the index form, refused early when it cannot work.

    The job would fail on the same input a moment later; checking here puts the
    message next to the form instead of on a progress page.
    """
    source = text.strip().strip('"').strip("'").strip()
    if not source:
        raise IntakeError("type a repository address or a folder on this machine")
    if looks_like_url(source):
        parse_repo_url(source)
    elif not Path(source).expanduser().is_dir():
        raise IntakeError(f"not a folder on this machine: {source}")
    return source


def create_app(
    db_path: Path,
    config: Config,
    read_only: bool = False,
    hosts: Sequence[str] | None = None,
    llm: Callable[[], Any] | None = None,
) -> FastAPI:
    """The app for one database. Each request opens its own connection (see `open_store`).

    `read_only` leaves out indexing, removing and asking: what a public demo must run
    with, because a visitor must never cause a call to a language model.
    `llm` makes the client a question is answered with; None means `LLMClient` from the
    configuration and the environment's keys (tests pass a scripted one).
    `hosts` are the names the app may be reached by; a request for any other name is
    refused, which stops another website from reaching the app through a DNS name
    that points at this machine. None means no check (tests).
    """
    app = FastAPI(title="CodeAtlas", version=__version__, docs_url=None, redoc_url=None)
    if hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.filters.update(percent=percent, thousands=thousands, slug=snapshot_slug)
    templates.env.globals.update(version=__version__, level_meaning=MEANING)
    templates.env.globals.update(read_only=read_only)
    # Snapshots already read, by slug. A snapshot only changes when it is indexed again or
    # removed; both happen through this app and take it out of the cache (`forget`). An
    # index run from the command line while the server is up still needs a restart.
    cache: dict[str, Loaded] = {}
    cache_lock = threading.Lock()

    def forget(snapshot_id: str) -> None:
        with cache_lock:
            cache.pop(snapshot_slug(snapshot_id), None)

    def run_index(source: str, force: bool, progress: Callable[[str, str], None]) -> dict:
        """One index job. `reused` says the commit was already stored and nothing ran."""
        seen: set[str] = set()

        def tell(step: str, detail: str) -> None:
            seen.add(step)
            progress(step, detail)

        report = index_repository(source, config, db_path, force=force, progress=tell)
        return {**report.to_dict(), "reused": "save" not in seen}

    def index_done(job: Job) -> None:
        if job.report is not None:
            forget(job.report["snapshot"]["id"])

    jobs = Jobs(run_index, index_done)

    def make_client() -> Any:
        if llm is not None:
            return llm()
        from codeatlas.llm import LLMClient

        return LLMClient.from_config()

    def run_question(snapshot_id: str, text: str, on_step: OnStep, on_wait: OnWait) -> Answer:
        """One question, on its own thread and so with its own connection."""
        from codeatlas.agent.loop import ask
        from codeatlas.llm import LLMError

        client = make_client()
        client.on_wait = on_wait  # so the page can say when it waits for a rate limit
        with GraphStore(db_path) as store:
            try:
                return ask(text, store, snapshot_id, client, config=config, on_step=on_step)
            except LLMError as exc:  # the trajectory so far is already on disk
                raise RuntimeError(f"the language model could not be reached: {exc}") from exc

    questions = Questions(run_question)

    def keys_missing() -> bool:
        """True when no question could reach a model. Never reads a key's value."""
        return llm is None and not any(os.environ.get(name) for name in LLM_KEYS)

    def can_change() -> None:
        if read_only:
            raise HTTPException(403, "this copy of CodeAtlas is read-only")

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

    def home_response(request: Request, error: str = "", typed: str = "") -> Any:
        """The start page: the index form, jobs under way, and every stored snapshot.

        It works with no database yet, so a first index can be started from the page.
        """
        rows = []
        if db_path.exists():
            with open_store() as store:
                snapshots = store.snapshots()
            for snapshot in snapshots:
                saved = load_report(config, snapshot.id)
                rows.append({"s": snapshot, "files": saved.files["total"] if saved else None})
        shown = [job for job in jobs.recent() if job.state != "done"][:5]
        return templates.TemplateResponse(
            request, "snapshots.html",
            {"rows": rows, "jobs": shown, "error": error, "typed": typed},
            status_code=400 if error else 200,
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Any:
        return home_response(request)

    @app.get("/snapshots", response_class=HTMLResponse)
    def snapshot_list(request: Request) -> Any:
        return home_response(request)

    @app.post("/index", response_class=HTMLResponse,
              dependencies=[Depends(from_this_app)])
    def start_index(request: Request, form: dict[str, str] = POSTED_FORM) -> Any:
        """Start indexing what was typed, then show its progress page."""
        can_change()
        typed = form.get("source", "")
        try:
            job = jobs.start(checked_source(typed), force=form.get("force") == "1")
        except (IntakeError, TooManyJobs) as exc:
            return home_response(request, str(exc), typed)
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> Any:
        """Where one index has got to. The page reloads itself while the job is active."""
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such index job: jobs are forgotten when the "
                                     "server stops. The list of repositories shows what "
                                     "was stored")
        waiting = [j for j in jobs.recent() if j.state == "running" and j is not job]
        return templates.TemplateResponse(
            request, "job.html", {"job": job, "ahead": waiting[0] if waiting else None})

    @app.get("/s/{slug}/remove", response_class=HTMLResponse)
    def remove_ask(request: Request, slug: str) -> Any:
        """Ask before removing: there is no undo short of indexing again."""
        can_change()
        with open_store() as store:
            snapshot = find_snapshot(store, slug)
        if snapshot is None:
            raise HTTPException(404, f"no snapshot {slug!r} in {db_path}")
        return templates.TemplateResponse(
            request, "remove.html",
            {"s": snapshot, "is_url": looks_like_url(snapshot.source)})

    @app.post("/s/{slug}/remove", response_class=HTMLResponse,
              dependencies=[Depends(from_this_app)])
    def remove(slug: str) -> Any:
        """Remove one snapshot from the database. The checkout on disk is not touched."""
        can_change()
        if jobs.busy():
            raise HTTPException(409, "a repository is being indexed: remove this one "
                                     "when that has finished")
        with open_store() as store:
            snapshot = find_snapshot(store, slug)
            if snapshot is None:
                raise HTTPException(404, f"no snapshot {slug!r} in {db_path}")
            store.delete_snapshot(snapshot.id)
        report_path(config, snapshot.id).unlink(missing_ok=True)
        forget(snapshot.id)
        return RedirectResponse("/", status_code=303)

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
        """Symbols and files by name, docstring or path; documentation sections apart."""
        loaded = get_loaded(slug)
        sid = loaded.snapshot.id
        with open_store() as store:
            ranked = [node for node, _ in store.search_text(sid, q, k=MAX_HITS)]
            docs = [node for node, _ in store.search_text(sid, q, k=MAX_DOC_HITS, docs=True)]
        hits = search(loaded, ranked, q) if q.strip() else []
        return page(request, "search.html", loaded, "search", q=q, hits=hits, docs=docs)

    def impact_response(request: Request, loaded: Loaded, chosen: ChangeSet | None,
                        error: str = "") -> Any:
        """The impact page: the ways to choose a change, or the result for one."""
        root = checkout_root(loaded.snapshot, config)
        values: dict[str, Any] = {"chosen": chosen, "error": error, "v": None}
        if chosen is None:
            values.update(commits=recent_commits(root, loaded.snapshot),
                          worktree=at_snapshot(root, loaded.snapshot),
                          has_checkout=root is not None)
        else:
            with open_store() as store:
                if loaded.graph is None:
                    loaded.graph = store.graph(loaded.snapshot.id, LOAD_KINDS)
                engine = ImpactEngine(store, loaded.snapshot.id, graph=loaded.graph)
                result = engine.impact(chosen.changes)
                tests = all_test_files(engine)
            values["v"] = impact_view(loaded, result, engine.config.test_threshold, tests)
            values["changed_files"] = len({c.path for c in chosen.changes})
        response = page(request, "impact.html", loaded, "impact", **values)
        response.status_code = 400 if error else 200
        return response

    @app.get("/s/{slug}/impact", response_class=HTMLResponse)
    def impact_page(request: Request, slug: str, commit: str = "", change: str = "",
                    file: str = "", symbol: str = "") -> Any:
        """What a change could break. The change is a commit, the uncommitted edits, one
        file or one symbol; with none of them the page offers the choices."""
        loaded = get_loaded(slug)
        root = checkout_root(loaded.snapshot, config)
        try:
            chosen = None
            if commit:
                chosen = commit_changes(root, loaded.snapshot, commit)
            elif change == "worktree":
                chosen = worktree_changes(root, loaded.snapshot)
            elif symbol:
                node = loaded.by_key.get(symbol)
                if node is None:
                    raise HTTPException(404, f"no symbol {symbol!r} in {loaded.snapshot.id}")
                chosen = ChangeSet(f"A change to {node.qualname or node.name}",
                                   (Change(node.path, symbol_keys=(symbol,)),), exact=True)
            elif file:
                if file_page(loaded, file) is None:
                    raise HTTPException(404, f"no file {file!r} in {loaded.snapshot.id}")
                chosen = ChangeSet(f"A change anywhere in {file}", (Change(file),), exact=True)
        except ChangeError as exc:
            return impact_response(request, loaded, None, str(exc))
        return impact_response(request, loaded, chosen)

    @app.post("/s/{slug}/impact", response_class=HTMLResponse)
    def impact_of_diff(request: Request, slug: str, diff: str = Depends(posted_diff)) -> Any:
        """What a pasted diff could break."""
        loaded = get_loaded(slug)
        try:
            return impact_response(request, loaded, pasted_changes(diff))
        except ChangeError as exc:
            return impact_response(request, loaded, None, str(exc))

    def ask_response(request: Request, loaded: Loaded, error: str = "",
                     typed: str = "") -> Any:
        response = page(request, "ask.html", loaded, "ask", error=error, typed=typed,
                        keys_missing=keys_missing(), max_chars=MAX_QUESTION_CHARS,
                        asked=questions.recent(loaded.snapshot.id))
        response.status_code = 400 if error else 200
        return response

    @app.get("/s/{slug}/ask", response_class=HTMLResponse)
    def ask_page(request: Request, slug: str) -> Any:
        """The question box and the questions already asked about this snapshot."""
        loaded = get_loaded(slug)
        can_change()
        return ask_response(request, loaded)

    @app.post("/s/{slug}/ask", response_class=HTMLResponse,
              dependencies=[Depends(from_this_app)])
    def ask_question(request: Request, slug: str, form: dict[str, str] = POSTED_FORM) -> Any:
        """Start answering a question, then show its answer page."""
        loaded = get_loaded(slug)
        can_change()
        text = form.get("question", "").strip()
        if keys_missing():
            return ask_response(request, loaded, "No language model key is set.", text)
        if not text:
            return ask_response(request, loaded, "Type a question first.", text)
        if len(text) > MAX_QUESTION_CHARS:
            return ask_response(request, loaded, f"A question can be at most "
                                f"{MAX_QUESTION_CHARS:,} characters long.", text)
        try:
            question = questions.start(loaded.snapshot.id, text)
        except TooManyQuestions as exc:
            return ask_response(request, loaded, str(exc), text)
        return RedirectResponse(f"/s/{slug}/ask/{question.id}", status_code=303)

    @app.get("/s/{slug}/ask/{question_id}", response_class=HTMLResponse)
    def answer_page(request: Request, slug: str, question_id: str) -> Any:
        """One question: its steps so far, then its answer. Reloads while it is active."""
        loaded = get_loaded(slug)
        question = questions.get(question_id)
        if question is None or question.snapshot_id != loaded.snapshot.id:
            raise HTTPException(404, "no such question: questions are forgotten when the "
                                     "server stops. Each one's record stays in the "
                                     "trajectories folder")
        # Read the state once and build the whole page from that reading: the question's
        # thread may finish while this page is being made. Reading it twice once gave a
        # "done" page built from "no answer yet": no answer text, and no reload to fix it.
        # The thread sets `answer` before `state`, so "done" here means the answer is set.
        state = question.state
        answer = question.answer if state == "done" else None
        last = question.steps[-1] if question.steps else {}
        return page(request, "answer.html", loaded, "ask", qn=question, state=state,
                    active=state in ("waiting", "running"), answer=answer,
                    rows=step_rows(question), model=last.get("model", ""),
                    provider=last.get("provider", ""),
                    pieces=answer_parts(answer) if answer else [])

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException) -> Any:
        """Every error as a page, including a 404 for an address no route matches."""
        return templates.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    return app
