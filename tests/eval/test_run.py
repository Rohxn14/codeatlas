"""Planning and running the SCIP indexers; the real indexers run only under `-m live`."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from eval.oracle import run

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "polyglot_app"


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def test_source_files_skip_dependencies_and_hidden_folders(tmp_path):
    write(tmp_path, {
        "a.py": "", "web/b.ts": "", "web/node_modules/x/c.js": "", ".venv/d.py": "",
        "README.md": "",
    })
    assert run.source_files(tmp_path) == ["a.py", "web/b.ts"]


def test_plan_runs_one_typescript_job_per_tsconfig(tmp_path):
    write(tmp_path, {"web/tsconfig.json": "{}", "web/node_modules/p/tsconfig.json": "{}"})
    jobs = run.plan_jobs(tmp_path, ["a.py", "web/b.ts"], "app", "abc", tmp_path / "w")
    assert [(j.tool, j.cwd) for j in jobs] == [
        ("scip-python", tmp_path), ("scip-typescript", tmp_path / "web"),
    ]
    assert "--project-version" in jobs[0].args  # scip-python crashes without one


def test_plan_infers_a_tsconfig_when_there_is_none(tmp_path):
    jobs = run.plan_jobs(tmp_path, ["b.js"], "app", "abc", tmp_path)
    assert [j.tool for j in jobs] == ["scip-typescript"]
    assert "--infer-tsconfig" in jobs[0].args


def test_missing_indexer_is_recorded_not_raised(tmp_path, monkeypatch):
    write(tmp_path, {"a.py": "def f():\n    pass\n"})
    monkeypatch.setattr(run, "tool_version", lambda tool: None)
    oracle = run.build_oracle(tmp_path, "app", None, None)
    assert oracle["edges"] == []
    assert oracle["errors"] == [
        f"scip-python is not installed; install with: {run.INSTALL_HINT}"
    ]


@pytest.mark.live
@pytest.mark.skipif(sys.platform == "win32", reason="the SCIP oracle is Linux only (D-10)")
@pytest.mark.skipif(shutil.which("scip-python") is None, reason="scip-python not installed")
def test_oracle_on_the_fixture(tmp_path):
    code = run.main([str(FIXTURE), "--nodes", str(FIXTURE / "expected_graph.json"),
                     "--out-dir", str(tmp_path)])
    assert code == 0
    (out,) = tmp_path.glob("oracle_polyglot_app_*.json")
    oracle = json.loads(out.read_text("utf-8"))
    pairs = {(e["src_key"], e["dst_key"]) for e in oracle["edges"]}
    assert ("backend/user_repo.py::UserRepo.save", "backend/repo.py::Repo.save") in pairs
    assert ("frontend/src/components/UserList.tsx::UserList",
            "frontend/src/components/UserCard.tsx::UserCard") in pairs


def test_windows_refuses_with_a_clear_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run.sys, "platform", "win32")

    def no_subprocess(*args, **kwargs):
        raise AssertionError("no indexer may start on Windows")

    monkeypatch.setattr(run.subprocess, "run", no_subprocess)
    assert run.main([str(tmp_path), "--out-dir", str(tmp_path / "out")]) == 2
    message = capsys.readouterr().err
    assert "only on Linux" in message and "#211" in message and "eval.oracle.score" in message


def test_indexer_that_will_not_start_is_an_error(tmp_path, monkeypatch):
    def cannot_start(*args, **kwargs):
        raise OSError("bad executable")

    monkeypatch.setattr(run.subprocess, "run", cannot_start)
    job = run.Job("scip-python", ("index",), tmp_path, tmp_path / "x.scip")
    assert "could not start" in run.run_job(job)


def test_unreadable_scip_output_is_recorded(tmp_path, monkeypatch):
    write(tmp_path, {"a.py": "def f():\n    pass\n"})
    monkeypatch.setattr(run, "tool_version", lambda tool: "1.0")

    def fake_job(job):
        job.output.write_bytes(b"\x0a\xff")  # a truncated protobuf
        return None

    monkeypatch.setattr(run, "run_job", fake_job)
    oracle = run.build_oracle(tmp_path, "app", None, None)
    assert any("unreadable output" in e for e in oracle["errors"])


def test_subfolder_is_named_by_its_tree_hash(make_repo):
    from conftest import git

    root = make_repo({"app/a.py": "x = 1\n", "other.txt": "y\n"})
    version, source = run.describe_source(root / "app")
    assert source == "app"
    assert version == git(root, "rev-parse", "HEAD:app")
    (root / "other.txt").write_text("changed\n", encoding="utf-8")
    git(root, "commit", "-qam", "unrelated")
    assert run.describe_source(root / "app")[0] == version  # unrelated commits do not rename it
