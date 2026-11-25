"""The query commands: `search`, `ask`, `impact`, `tests`, `mcp` and `view --impact`."""

import io
import json
import re
import webbrowser
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import git

from codeatlas import cli
from codeatlas.cli import evidence_line, main
from codeatlas.impact import Evidence, Hop
from codeatlas.llm import LLMClient, LLMResponse

FILES = {
    "shop/repo.py": "class Repo:\n    def save(self, item):\n        return item\n",
    "shop/service.py": (
        "from shop.repo import Repo\n"
        "\n"
        "def create(item):\n"
        "    return Repo().save(item)\n"
    ),
    "tests/test_service.py": (
        "from shop.service import create\n"
        "\n"
        "def test_create():\n"
        "    assert create(1) == 1\n"
    ),
    "tests/test_other.py": "def test_nothing():\n    assert True\n",
}
SAVE_DIFF = (
    "diff --git a/shop/repo.py b/shop/repo.py\n"
    "--- a/shop/repo.py\n"
    "+++ b/shop/repo.py\n"
    "@@ -3 +3 @@\n"
    "-        return item\n"
    "+        return dict(item)\n"
)


@pytest.fixture
def indexed(make_repo: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A two-commit repository, indexed at its second commit; returns (repo, db, toml)."""
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    repo = make_repo(FILES, name="shopdemo")
    (repo / "shop/repo.py").write_text(FILES["shop/repo.py"].replace(
        "return item", "return dict(item)"), encoding="utf-8")
    git(repo, "commit", "-q", "-am", "save copies the item")
    toml = tmp_path / "ct.toml"
    toml.write_text(f'[paths]\ndata_dir = "{(tmp_path / "data").as_posix()}"\n',
                    encoding="utf-8")
    db = tmp_path / "data" / "codeatlas.db"
    assert main(["index", "--no-embed", str(repo), "--config", str(toml)]) == 0
    return repo, db, toml


def run(capsys: pytest.CaptureFixture[str], toml: Path, *args: str) -> tuple[int, str, str]:
    code = main([*args, "--config", str(toml)])
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys: pytest.CaptureFixture[str], toml: Path, *args: str) -> dict:
    code, out, err = run(capsys, toml, *args, "--json")
    assert code == 0, err
    return json.loads(out)


def test_search_text_and_json(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, out, _ = run(capsys, toml, "search", "save", "-k", "3")
    assert code == 0
    first = out.splitlines()[0]
    assert re.match(r"\s+1\s+\d\.\d{4}\s+function\s+shop/repo.py::Repo.save\s+"
                    r"shop/repo.py:2", first)
    assert "note: no embeddings for this snapshot: BM25 only" in out
    data = run_json(capsys, toml, "search", "save", "--no-expand")
    assert data["hits"][0]["key"] == "shop/repo.py::Repo.save"
    assert all(hit["sources"] != ["graph"] for hit in data["hits"])


def test_impact_from_files(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, out, _ = run(capsys, toml, "impact", "--files", "shop\\repo.py", "--top", "2")
    assert code == 0
    assert "1 changed files" in out and "shop/repo.py::Repo.save" in out
    assert "top 2 shown" in out
    assert re.search(r"^\s+1\s+\d\.\d{3}\s+\w+\s+\S+$", out, re.M)
    assert re.search(r"^\s+(graph|import|tests|cochange) \d\.\d{3}: ", out, re.M)


def test_impact_from_stdin_diff_json(indexed, capsys, monkeypatch) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    monkeypatch.setattr(
        "sys.stdin", io.TextIOWrapper(io.BytesIO(SAVE_DIFF.encode("utf-8")), encoding="utf-8"))
    data = run_json(capsys, toml, "impact", "--diff", "-", "--depth", "2", "--decay", "0.5")
    assert data["changed"] == ["shop/repo.py::Repo.save"]
    keys = [t["key"] for t in data["targets"]]
    assert "shop/service.py::create" in keys
    create = next(t for t in data["targets"] if t["key"] == "shop/service.py::create")
    assert create["score"] <= 0.5  # one hop at decay 0.5
    assert create["evidence"][0].startswith("graph ")


def test_impact_from_diff_file_and_git_agree(indexed, capsys, tmp_path) -> None:
    repo, _, toml = indexed
    capsys.readouterr()
    diff = tmp_path / "change.diff"
    diff.write_text(git(repo, "diff", "HEAD~1") + "\n", encoding="utf-8")
    from_file = run_json(capsys, toml, "impact", "--diff", str(diff))
    from_git = run_json(capsys, toml, "impact", "--git", "HEAD~1")
    assert "shop/repo.py::Repo.save" in from_git["changed"]  # git adds context lines
    assert from_git["changed"] == from_file["changed"]
    assert from_git["targets"] == from_file["targets"]


def test_git_failure_is_a_clear_error(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, _, err = run(capsys, toml, "impact", "--git", "no-such-rev")
    assert code == 2 and "git diff no-such-rev failed" in err


def test_tests_command_ranks_and_reports_skipped_share(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, out, _ = run(capsys, toml, "tests", "--git", "HEAD~1")
    assert code == 0
    assert "tests/test_service.py::test_create" in out
    assert "1 of 2; skipped share 50%" in out
    data = run_json(capsys, toml, "tests", "--files", "shop/repo.py")
    assert data["test_files"] == 2 and data["skipped_share"] == 0.5
    assert data["selected_files"] == ["tests/test_service.py"]
    assert data["tests"][0]["evidence"]


def test_unknown_file_still_exits_zero_with_a_warning(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    data = run_json(capsys, toml, "impact", "--files", "missing.py")
    assert data["targets"] == [] and data["warnings"]


def test_change_input_is_required(indexed, capsys) -> None:
    _, _, toml = indexed
    with pytest.raises(SystemExit) as stop:
        main(["impact", "--config", str(toml)])
    assert stop.value.code == 2


def test_ask_without_a_key_exits_2(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, out, err = run(capsys, toml, "ask", "what calls save?")
    assert code == 2 and out == ""
    assert "GROQ_API_KEY" in err and "GEMINI_API_KEY" in err and len(err.splitlines()) == 1


class OneAnswer:
    """A provider that answers once, citing one real line and one line past the file."""

    name, model = "scripted", "scripted-1"

    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, messages, tools, temperature, max_tokens) -> LLMResponse:
        return LLMResponse(self.text, (), self.name, self.model, 10, 5)


def _fake_client(snapshot_id: str) -> LLMClient:
    text = (f"`create` calls `Repo.save` ({snapshot_id}:shop/service.py:4), "
            f"see also {snapshot_id}:shop/repo.py:99.")
    return LLMClient([OneAnswer(text)], cache_mode="off")


def test_ask_prints_answer_citations_and_trajectory(indexed, capsys, monkeypatch) -> None:
    _, db, toml = indexed
    capsys.readouterr()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    snapshot_id = cli.latest_snapshot_id(db)
    fake = classmethod(lambda cls, *_a: _fake_client(snapshot_id))
    monkeypatch.setattr(LLMClient, "from_config", fake)
    code, out, _ = run(capsys, toml, "ask", "what does create call?")
    assert code == 0
    assert out.startswith("`create` calls")
    assert f"ok      {snapshot_id}:shop/service.py:4" in out
    assert f"INVALID {snapshot_id}:shop/repo.py:99" in out
    assert re.search(r"^Trajectory: \S+\.jsonl$", out, re.M)
    data = run_json(capsys, toml, "ask", "what does create call?")
    assert [c["valid"] for c in data["citations"]] == [True, False]
    assert data["steps"] == 1


def test_mcp_serves_the_toolset(indexed, capsys, monkeypatch) -> None:
    _, db, toml = indexed
    seen = {}

    async def fake_serve(tools) -> None:
        seen["names"] = [spec.name for spec in tools.specs]

    monkeypatch.setattr("codeatlas.agent.mcp_server.serve_stdio", fake_serve)
    code, _, err = run(capsys, toml, "mcp")
    assert code == 0 and "impact" in seen["names"]
    assert cli.latest_snapshot_id(db) in err


def test_view_impact_embeds_changed_and_targets(indexed, capsys, monkeypatch, tmp_path) -> None:
    _, _, toml = indexed
    monkeypatch.setattr(webbrowser, "open", lambda *_a, **_k: True)
    diff = tmp_path / "change.diff"
    diff.write_text(SAVE_DIFF, encoding="utf-8")
    out = tmp_path / "page.html"
    code, _, _ = run(capsys, toml, "view", "--impact", str(diff), "--out", str(out), "--no-open")
    assert code == 0
    html = out.read_text(encoding="utf-8")
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    assert match
    block = json.loads(match.group(1))["impact"]
    assert block["changed"] == ["shop/repo.py::Repo.save"]
    assert "shop/service.py::create" in [t["key"] for t in block["targets"]]
    assert 'id="impactbox"' in html


def test_no_database_is_a_clear_error(tmp_path, capsys) -> None:
    code = main(["search", "x", "--db", str(tmp_path / "none.db")])
    assert code == 2 and "no database" in capsys.readouterr().err


def test_evidence_line_formats_hops_and_detail() -> None:
    hops = (Hop("a.py::f"), Hop("b.py::g", "calls", 0.9))
    assert evidence_line(Evidence("graph", 0.72, hops)) == (
        "graph 0.720: a.py::f <-calls 0.9- b.py::g")
    assert evidence_line(Evidence("cochange", 0.4, (), "changed together 4 times")) == (
        "cochange 0.400: changed together 4 times")


def test_git_refuses_a_checkout_that_moved_past_the_snapshot(indexed, capsys) -> None:
    repo, _, toml = indexed
    (repo / "shop/service.py").write_text("def create(item):\n    return item\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "third commit")
    capsys.readouterr()
    code, out, err = run(capsys, toml, "impact", "--git", "HEAD~1")
    assert code == 2 and out == ""
    assert "codeatlas index --force" in err and "snapshot is" in err


def test_text_that_is_not_a_diff_is_an_error(indexed, capsys, monkeypatch) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"garbage\n")))
    code, out, err = run(capsys, toml, "impact", "--diff", "-")
    assert code == 2 and out == ""
    assert "codeatlas: no file headers found in the diff" in err


def test_empty_git_diff_says_no_changes(indexed, capsys) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    code, out, _ = run(capsys, toml, "impact", "--git", "HEAD")
    assert code == 0 and "no changes" in out


def test_stdin_diff_is_read_as_utf8_whatever_the_console_encoding(indexed, capsys,
                                                                  monkeypatch) -> None:
    _, _, toml = indexed
    capsys.readouterr()
    diff = SAVE_DIFF.replace("dict(item)", "dict(item)  # é\u0081") + "\n"
    raw = diff.encode("utf-8")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252"))
    data = run_json(capsys, toml, "impact", "--diff", "-")
    assert data["changed"] == ["shop/repo.py::Repo.save"]


def test_llm_clients_use_the_config_option(indexed, capsys, monkeypatch) -> None:
    _, _, toml = indexed
    seen = []
    from codeatlas.llm import embeddings

    def fake(cls, config=None):
        seen.append(config)
        return embeddings.EmbeddingClient(embedder=lambda batch: [[1.0]] * len(batch))

    monkeypatch.setattr(embeddings.EmbeddingClient, "from_config", classmethod(fake))
    capsys.readouterr()
    assert run(capsys, toml, "search", "save")[0] == 0
    assert seen and seen[0] is not None


def test_index_prepares_search_by_meaning_unless_told_not_to(
    make_repo, tmp_path, capsys, monkeypatch,
) -> None:
    from codeatlas.llm import embeddings

    def fake(cls, config=None):
        return embeddings.EmbeddingClient("fake-model", embedder=lambda batch: [[1.0]] * len(batch))

    monkeypatch.setattr(embeddings.EmbeddingClient, "from_config", classmethod(fake))
    repo = make_repo(FILES, name="shopdemo")
    toml = tmp_path / "ct.toml"
    toml.write_text(f'[paths]\ndata_dir = "{(tmp_path / "data").as_posix()}"\n', encoding="utf-8")
    code, out, err = run(capsys, toml, "index", str(repo))
    assert code == 0 and "preparing search by meaning" in err
    assert re.search(r"^Embeddings: \d+ symbols with fake-model in ", out, re.M)
    code, out, err = run(capsys, toml, "index", str(repo), "--force", "--no-embed")
    assert code == 0 and "preparing search by meaning" not in err
    assert "Embeddings: none built; search uses text only" in out


def test_index_says_when_the_embedding_model_could_not_run(
    make_repo, tmp_path, capsys, monkeypatch,
) -> None:
    from codeatlas.llm import embeddings

    def offline(batch):
        raise OSError("no network")

    monkeypatch.setattr(
        embeddings.EmbeddingClient, "from_config",
        classmethod(lambda cls, config=None: cls("fake-model", embedder=offline)))
    repo = make_repo(FILES, name="shopdemo")
    toml = tmp_path / "ct.toml"
    toml.write_text(f'[paths]\ndata_dir = "{(tmp_path / "data").as_posix()}"\n', encoding="utf-8")
    code, out, _ = run(capsys, toml, "index", str(repo))
    assert code == 0 and "Embeddings: not built (OSError: no network)" in out
