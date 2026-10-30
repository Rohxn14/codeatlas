"""Planning and running the SCIP indexers; the real indexers run only under `-m live`."""

import json
import shutil
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
