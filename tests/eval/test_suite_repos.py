"""repos.yaml is valid, and the validator rejects the mistakes it exists to catch."""

from pathlib import Path

import pytest

from eval.suite.repos import REQUIRED_LANGUAGES, load_repos


def write(path: Path, entries: str) -> Path:
    path.write_text("repos:\n" + entries, encoding="utf-8")
    return path


ENTRY = """  - name: {name}
    url: https://github.com/o/{name}
    sha: {sha}
    languages: [python]
    size: {size}
    why: a reason
"""


def test_shipped_list_is_valid_and_wide():
    specs = load_repos()
    assert 40 <= len(specs) <= 50
    assert len({s.name for s in specs}) == len(specs)
    assert "click" in {s.name for s in specs}
    covered = {lang for s in specs for lang in s.languages}
    assert covered >= REQUIRED_LANGUAGES
    assert 3 <= sum(1 for s in specs if s.size in ("large", "very large")) <= 12


def test_valid_entry_loads(tmp_path):
    path = write(tmp_path / "r.yaml", ENTRY.format(name="a", sha="a" * 40, size="small"))
    assert [s.name for s in load_repos(path)] == ["a"]


@pytest.mark.parametrize(
    ("sha", "size", "message"),
    [("abc", "small", "40"), ("a" * 40, "huge", "size")],
)
def test_bad_sha_or_size_is_named(tmp_path, sha, size, message):
    path = write(tmp_path / "r.yaml", ENTRY.format(name="a", sha=sha, size=size))
    with pytest.raises(ValueError, match=message):
        load_repos(path)


def test_duplicate_names_are_rejected(tmp_path):
    entry = ENTRY.format(name="a", sha="a" * 40, size="small")
    with pytest.raises(ValueError, match="duplicate"):
        load_repos(write(tmp_path / "r.yaml", entry + entry))
