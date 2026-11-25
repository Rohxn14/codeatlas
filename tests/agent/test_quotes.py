"""Quoted code must be in the file cited beside it, or at least exist somewhere (D-63)."""

import hashlib
import subprocess

import pytest

from codeatlas.agent.loop import ask, check_citations, citation_pattern
from codeatlas.agent.quotes import check_quotes
from codeatlas.agent.snapshot_files import snapshot_bytes
from codeatlas.agent.tools import ToolSet

from .support import FILES, SNAP, make_client, reply


@pytest.fixture
def hashed(store, source_dir):
    """The fixture snapshot with real hashes, so its files can be read as indexed."""
    with store._conn:  # the fixture stored "x" for every hash
        for path in FILES:
            digest = hashlib.sha256((source_dir / path).read_bytes()).hexdigest()
            store._conn.execute("UPDATE files SET sha256 = ? WHERE path = ?", (digest, path))
    return store


def unfound(store, text: str) -> list[tuple[str, tuple[str, ...]]]:
    tools = ToolSet(store, SNAP)
    checks = check_quotes(text, check_citations(text, tools), tools, citation_pattern(SNAP))
    return [(q.text, q.missing) for q in checks if q.missing]


def test_invented_code_is_flagged_though_its_citation_is_valid(hashed):
    # Nov 25: five rows like this one, every citation valid.
    text = f"| `contracts.validate(race, contracts.RACE)` | {SNAP}:app/service.py:4 |"
    assert unfound(hashed, text) == [
        ("contracts.validate(race, contracts.RACE)", ("contracts", "validate", "race", "RACE"))]


@pytest.mark.parametrize("text", [
    "`return Repo().save(user)` at {s}:app/service.py:4",          # as written
    "`Repo().save( user )` at {s}:app/service.py:4",               # spacing
    "`create(user)` calls `Repo.save` ({s}:app/service.py:4)",     # names in the file
    "`rename` is not in {s}:app/repo.py:2, it is elsewhere",       # a name on the map
    "`app/service.py` and `app/` near {s}:app/repo.py:2",          # files and folders
    "`search_symbols` found {s}:app/repo.py:2",                    # a tool's name
    "`nothing_like_this` with no citation on its line",            # not judged
    "a plain `word` at {s}:app/repo.py:2",                         # not code
])
def test_what_is_not_flagged(hashed, text):
    assert unfound(hashed, text.format(s=SNAP)) == []


def test_a_file_that_cannot_be_read_as_indexed_is_not_judged(store):
    # The fixture's hashes are "x": the file on disk is not the indexed one.
    assert unfound(store, f"`made_up_name()` at {SNAP}:app/repo.py:2") == []


def test_the_answer_carries_its_quotes_and_the_trajectory_lists_the_unfound(hashed, tmp_path):
    text = f"`create(user)` and `made_up_name()` at {SNAP}:app/service.py:3"
    client, _ = make_client(reply(text))
    answer = ask("q", hashed, SNAP, client, data_dir=tmp_path)
    assert len(answer.quotes) == 2
    assert [q.text for q in answer.unfound_quotes] == ["made_up_name()"]
    trajectory = answer.trajectory_path.read_text(encoding="utf-8")
    assert '"unfound_quotes": ["made_up_name()"]' in trajectory


def test_a_file_is_read_as_it_was_indexed(tmp_path):
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
            cwd=tmp_path, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    git("init", "-q")
    (tmp_path / "a.py").write_bytes(b"old = 1\n")
    git("add", "a.py")
    git("commit", "-q", "-m", "one")
    sha, old = git("rev-parse", "HEAD"), hashlib.sha256(b"old = 1\n").hexdigest()
    assert snapshot_bytes(tmp_path, sha, "a.py", old) == b"old = 1\n"
    (tmp_path / "a.py").write_bytes(b"new = 1\nold = 1\n")  # the checkout moves on
    assert snapshot_bytes(tmp_path, sha, "a.py", old) == b"old = 1\n"
    crlf = hashlib.sha256(b"old = 1\r\n").hexdigest()  # indexed from a Windows checkout
    assert snapshot_bytes(tmp_path, sha, "a.py", crlf) == b"old = 1\r\n"
    assert snapshot_bytes(tmp_path, sha, "a.py", "0" * 64) is None
    assert snapshot_bytes(tmp_path, sha, "../outside.py", old) is None
    assert snapshot_bytes(tmp_path, sha, ".env", old) is None
    assert snapshot_bytes(None, sha, "a.py", old) is None
