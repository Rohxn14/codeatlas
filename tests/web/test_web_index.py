"""Indexing and removing from the web app: the jobs, the form, the progress page."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.indexer.intake import IntakeError
from codeatlas.indexer.pipeline.index import index_repository, report_path
from codeatlas.store import GraphStore
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.app import checked_source
from codeatlas.web.jobs import MAX_ACTIVE, STEPS, Job, Jobs, TooManyJobs

FILES = {
    "app/service.py": "from lib.util import helper\n\n\ndef save():\n    helper()\n",
    "lib/util.py": "def helper():\n    pass\n",
    "README.md": "# demo\n",
}


def job_id(response: Any) -> str:
    assert response.status_code == 303, response.text
    return response.headers["location"].removeprefix("/jobs/")


@pytest.fixture
def setup(make_repo: Callable[..., Path], tmp_path: Path) -> tuple[TestClient, Path, Config, Path]:
    """An app with no database yet, and a small repository to index: (client, db, config, repo)."""
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    client = TestClient(create_app(db_path, config), follow_redirects=False)
    return client, db_path, config, make_repo(FILES, name="demo")


def finish(client: TestClient, job: str) -> str:
    """Wait for a job through its page, as a browser would; returns the last page."""
    for _ in range(600):
        page = client.get(f"/jobs/{job}")
        assert page.status_code == 200
        if 'http-equiv="refresh"' not in page.text:
            return page.text
        threading.Event().wait(0.05)
    raise AssertionError("the job did not finish")


# Jobs


def test_a_job_runs_and_reports_each_step_it_was_told() -> None:
    seen: list[str] = []

    def work(source: str, force: bool, progress: Callable[[str, str], None]) -> dict[str, Any]:
        progress("parse", "3 of 9 files")
        seen.append(source)
        return {"snapshot": {"id": "demo@abc"}}

    done: list[Job] = []
    jobs = Jobs(work, done.append)
    job = jobs.wait(jobs.start("some/folder").id)
    assert (job.state, job.step, job.detail) == ("done", "parse", "3 of 9 files")
    assert seen == ["some/folder"] and done == [job]
    assert all(step["status"] == "done" for step in job.steps())
    assert [step["name"] for step in job.steps()] == [name for name, _ in STEPS]


def test_a_failing_job_keeps_its_message_and_the_step_it_stopped_at() -> None:
    def work(source: str, force: bool, progress: Callable[[str, str], None]) -> dict[str, Any]:
        progress("intake", "")
        raise IntakeError("git clone failed: not found")

    jobs = Jobs(work)
    job = jobs.wait(jobs.start("x").id)
    assert (job.state, job.error) == ("failed", "git clone failed: not found")
    assert job.steps()[0]["status"] == "failed"
    assert not jobs.busy()


def test_jobs_run_one_at_a_time_and_the_same_source_is_not_queued_twice() -> None:
    gate = threading.Event()
    running: list[str] = []
    most = [0]

    def work(source: str, force: bool, progress: Callable[[str, str], None]) -> dict[str, Any]:
        running.append(source)
        most[0] = max(most[0], len(running))
        gate.wait(10)
        running.remove(source)
        return {"snapshot": {"id": source}}

    jobs = Jobs(work)
    first = jobs.start("a")
    assert jobs.start("a") is first
    others = [jobs.start(name) for name in "bcdef"[: MAX_ACTIVE - 1]]
    with pytest.raises(TooManyJobs):
        jobs.start("one-too-many")
    gate.set()
    for job in (first, *others):
        assert jobs.wait(job.id).state == "done"
    assert most[0] == 1


# The form


def test_checked_source_refuses_what_cannot_work(tmp_path: Path) -> None:
    assert checked_source(f'  "{tmp_path}" ') == str(tmp_path)
    assert checked_source("https://gitlab.com/owner/repo") == "https://gitlab.com/owner/repo"
    for bad in ("", "   ", "https://example.com/owner/repo", str(tmp_path / "absent")):
        with pytest.raises(IntakeError):
            checked_source(bad)


def test_index_from_the_page_then_open_it(setup: tuple[TestClient, Path, Config, Path]) -> None:
    client, db_path, config, repo = setup
    assert "Nothing is indexed yet" in client.get("/").text
    last = finish(client, job_id(client.post("/index", data={"source": str(repo)})))
    assert "Open the map" in last and "Done in" in last
    with GraphStore(db_path) as store:
        (snapshot,) = store.snapshots()
    base = f"/s/{snapshot_slug(snapshot.id)}"
    assert f'href="{base}/"' in last
    assert client.get(f"{base}/").status_code == 200
    assert "demo" in client.get("/").text

    # The same commit again: nothing is done, and the page says so.
    again = finish(client, job_id(client.post("/index", data={"source": str(repo)})))
    assert "already indexed" in again


def test_index_again_shows_the_changed_files(setup: tuple[TestClient, Path, Config, Path]) -> None:
    """A snapshot opened before a second index must not be served from memory after it."""
    client, db_path, config, repo = setup
    finish(client, job_id(client.post("/index", data={"source": str(repo)})))
    with GraphStore(db_path) as store:
        (snapshot,) = store.snapshots()
    # The file page lists the file's symbols from the map (its source comes from disk).
    file_page = f"/s/{snapshot_slug(snapshot.id)}/file?path=lib/util.py"
    assert "helper" in client.get(file_page).text

    (repo / "lib" / "util.py").write_text("def brand_new():\n    pass\n", encoding="utf-8")
    form = {"source": str(repo), "force": "1"}
    assert "Done in" in finish(client, job_id(client.post("/index", data=form)))
    after = client.get(file_page).text
    assert "brand_new" in after and "helper" not in after


def test_a_bad_source_comes_back_to_the_form_with_the_reason(
    setup: tuple[TestClient, Path, Config, Path],
) -> None:
    client, db_path, _, _ = setup
    page = client.post("/index", data={"source": "https://example.com/a/b"})
    assert page.status_code == 400
    assert "github.com, gitlab.com" in page.text
    assert 'value="https://example.com/a/b"' in page.text  # what was typed is kept
    assert not db_path.exists()


def test_a_failed_index_says_why(
    setup: tuple[TestClient, Path, Config, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, repo = setup

    def fail(*args: object, **options: object) -> None:
        raise IntakeError("git clone failed: <b>no such repository</b>")

    monkeypatch.setattr("codeatlas.web.app.index_repository", fail)
    last = finish(client, job_id(client.post("/index", data={"source": str(repo)})))
    assert "could not be indexed" in last
    assert "&lt;b&gt;no such repository" in last and "<b>no such" not in last
    assert "failed" in client.get("/").text


def test_unknown_job_is_a_404_page(setup: tuple[TestClient, Path, Config, Path]) -> None:
    assert setup[0].get("/jobs/nope").status_code == 404


# Removing


def test_remove_asks_first_then_deletes_the_snapshot_and_its_report(
    setup: tuple[TestClient, Path, Config, Path],
) -> None:
    client, db_path, config, repo = setup
    report = index_repository(str(repo), config, db_path)
    sid = report.snapshot["id"]
    base = f"/s/{snapshot_slug(sid)}"
    assert client.get(f"{base}/").status_code == 200  # now in the app's memory

    ask = client.get(f"{base}/remove")
    assert ask.status_code == 200 and "is not touched" in ask.text
    with GraphStore(db_path) as store:
        assert store.get_snapshot(sid) is not None  # asking removes nothing

    gone = client.post(f"{base}/remove")
    assert (gone.status_code, gone.headers["location"]) == (303, "/")
    with GraphStore(db_path) as store:
        assert store.snapshots() == []
    assert not report_path(config, sid).exists()
    assert client.get(f"{base}/").status_code == 404
    assert (repo / "lib" / "util.py").is_file()  # the folder itself is left alone
    assert client.post(f"{base}/remove").status_code == 404


# Who may change things


def test_read_only_app_has_no_form_and_refuses_changes(
    setup: tuple[TestClient, Path, Config, Path],
) -> None:
    _, db_path, config, repo = setup
    sid = index_repository(str(repo), config, db_path).snapshot["id"]
    client = TestClient(create_app(db_path, config, read_only=True), follow_redirects=False)
    start = client.get("/")
    assert "Index a repository" not in start.text and "Remove" not in start.text
    base = f"/s/{snapshot_slug(sid)}"
    assert client.post("/index", data={"source": str(repo)}).status_code == 403
    assert client.get(f"{base}/remove").status_code == 403
    assert client.post(f"{base}/remove").status_code == 403
    assert client.get(f"{base}/").status_code == 200


def test_a_form_posted_from_another_website_is_refused(
    setup: tuple[TestClient, Path, Config, Path],
) -> None:
    client, db_path, _, repo = setup
    form = {"source": str(repo)}
    other = client.post("/index", data=form, headers={"origin": "https://evil.example"})
    assert other.status_code == 403
    cross = client.post("/index", data=form, headers={"sec-fetch-site": "cross-site"})
    assert cross.status_code == 403
    assert not db_path.exists()
    own = client.post("/index", data=form, headers={"origin": "http://testserver"})
    finish(client, job_id(own))
