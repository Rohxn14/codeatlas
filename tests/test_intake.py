from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from codeatlas.config import Config
from codeatlas.indexer import intake
from codeatlas.indexer.discover import discover
from codeatlas.indexer.intake import (
    IntakeError,
    RepoSource,
    clone_or_reuse,
    head_sha,
    open_source,
    parse_repo_url,
)
from codeatlas.models import Tier


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/pallets/click", RepoSource("pallets", "click")),
        ("https://github.com/pallets/click/", RepoSource("pallets", "click")),
        ("https://github.com/pallets/click.git", RepoSource("pallets", "click")),
        ("https://www.github.com/pallets/click", RepoSource("pallets", "click")),
        ("https://github.com/pallets/click@8.1.7", RepoSource("pallets", "click", "8.1.7")),
        (
            "https://github.com/owner/repo@feature/new-thing",
            RepoSource("owner", "repo", "feature/new-thing"),
        ),
        ("https://gitlab.com/owner/repo", RepoSource("owner", "repo", host="gitlab.com")),
        ("https://bitbucket.org/owner/repo.git", RepoSource("owner", "repo", host="bitbucket.org")),
        ("https://Codeberg.org/owner/repo@v1", RepoSource("owner", "repo", "v1", "codeberg.org")),
    ],
)
def test_parse_valid_urls(url: str, expected: RepoSource) -> None:
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/owner/repo",
        "https://gitlab.com/group/subgroup/repo",
        "https://github.com.evil.example/owner/repo",
        "https://user@github.com/owner/repo",
        "http://github.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/repo@--upload-pack=evil",
        "https://github.com/owner/repo@a..b",
        "https://github.com/owner/repo?tab=readme",
    ],
)
def test_parse_rejects_bad_urls(url: str) -> None:
    with pytest.raises(IntakeError):
        parse_repo_url(url)


def test_clone_folder_name() -> None:
    assert RepoSource("pallets", "click").dirname == "pallets__click"


def test_other_hosts_get_their_own_clone_url_and_folder() -> None:
    source = parse_repo_url("https://gitlab.com/owner/repo")
    assert source.clone_url == "https://gitlab.com/owner/repo.git"
    assert source.dirname == "gitlab.com__owner__repo"


def test_clone_then_reuse_then_reclone(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    origin = make_repo({"app.py": "def main():\n    pass\n"})
    dest = tmp_path / "repos" / "owner__repo"
    sha, reused = clone_or_reuse(origin.as_uri(), dest)
    assert not reused
    assert sha == head_sha(origin) == head_sha(dest)
    assert (dest / "app.py").is_file()

    again, reused = clone_or_reuse(origin.as_uri(), dest)
    assert (again, reused) == (sha, True)

    (origin / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    git(origin, "commit", "-q", "-am", "change")
    newer, reused = clone_or_reuse(origin.as_uri(), dest)
    assert not reused
    assert newer == head_sha(origin) != sha
    assert "return 1" in (dest / "app.py").read_text(encoding="utf-8")


def test_clone_keeps_history(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    origin = make_repo({"a.txt": "1\n"})
    (origin / "a.txt").write_text("2\n", encoding="utf-8")
    git(origin, "commit", "-q", "-am", "second")
    dest = tmp_path / "clone"
    clone_or_reuse(origin.as_uri(), dest)
    assert git(dest, "rev-list", "--count", "HEAD") == "2"


def test_clone_allows_long_paths(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    """Stored in the clone's config, so a later checkout there can write long paths too."""
    origin = make_repo({"a.txt": "1\n"})
    dest = tmp_path / "clone"
    clone_or_reuse(origin.as_uri(), dest)
    assert git(dest, "config", "--get", "core.longpaths") == "true"


def _flaky_rename(monkeypatch: pytest.MonkeyPatch, failures: int) -> list[str]:
    """Make the next `failures` renames raise PermissionError, as a held file does on Windows."""
    real_rename = Path.rename
    calls: list[str] = []

    def rename(self: Path, target: Path) -> Path:
        calls.append(self.name)
        if len(calls) <= failures:
            raise PermissionError(5, "Access is denied")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(intake.time, "sleep", lambda _seconds: None)
    return calls


def test_swap_retries_while_a_file_is_held_open(
    make_repo: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = make_repo({"a.txt": "1\n"})
    calls = _flaky_rename(monkeypatch, failures=2)
    sha, _ = clone_or_reuse(origin.as_uri(), tmp_path / "clone")
    assert sha == head_sha(origin)
    assert len(calls) == 3  # two refusals, then the rename that worked


def test_swap_gives_up_and_cleans_up_when_the_file_stays_held(
    make_repo: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = make_repo({"a.txt": "1\n"})
    _flaky_rename(monkeypatch, failures=1000)
    with pytest.raises(PermissionError):
        clone_or_reuse(origin.as_uri(), tmp_path / "repos" / "clone")
    assert list((tmp_path / "repos").iterdir()) == []  # the temporary clone was removed


def test_clone_at_tag(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    origin = make_repo({"a.txt": "1\n"})
    git(origin, "tag", "-a", "v1", "-m", "release")
    tagged = head_sha(origin)
    (origin / "a.txt").write_text("2\n", encoding="utf-8")
    git(origin, "commit", "-q", "-am", "after tag")
    sha, _ = clone_or_reuse(origin.as_uri(), tmp_path / "clone", "v1")
    assert sha == tagged
    _, reused = clone_or_reuse(origin.as_uri(), tmp_path / "clone", "v1")
    assert reused


def test_failed_reclone_keeps_the_old_clone(
    make_repo: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = make_repo({"app.py": "v = 1\n"})
    dest = tmp_path / "repos" / "owner__repo"
    first, _ = clone_or_reuse(origin.as_uri(), dest)
    (origin / "app.py").write_text("v = 2\n", encoding="utf-8")
    git(origin, "commit", "-q", "-am", "change")

    def broken_clone(*_args: object) -> str:
        raise IntakeError("network down")

    monkeypatch.setattr(intake, "_clone_into", broken_clone)
    with pytest.raises(IntakeError, match="network down"):
        clone_or_reuse(origin.as_uri(), dest)
    assert head_sha(dest) == first
    assert (dest / "app.py").read_text(encoding="utf-8") == "v = 1\n"
    assert [p.name for p in dest.parent.iterdir()] == ["owner__repo"]  # no temp left over


def test_refuses_to_replace_a_folder_it_did_not_create(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    origin = make_repo({"a.txt": "1\n"})
    dest = tmp_path / "repos" / "owner__repo"
    dest.mkdir(parents=True)
    (dest / "precious.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(IntakeError, match="not created by CodeAtlas"):
        clone_or_reuse(origin.as_uri(), dest)
    assert (dest / "precious.txt").read_text(encoding="utf-8") == "keep me"


def test_refuses_an_unmarked_git_repository(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    origin = make_repo({"a.txt": "1\n"})
    other = make_repo({"b.txt": "2\n"}, name="someone_elses")
    with pytest.raises(IntakeError, match="not created by CodeAtlas"):
        clone_or_reuse(origin.as_uri(), other)
    assert (other / "b.txt").is_file()


def test_an_empty_folder_is_replaced(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    origin = make_repo({"a.txt": "1\n"})
    dest = tmp_path / "empty"
    dest.mkdir()
    sha, reused = clone_or_reuse(origin.as_uri(), dest)
    assert (sha, reused) == (head_sha(origin), False)
    assert (dest / "a.txt").is_file()


def test_clone_marker_is_invisible_to_discovery(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    dest = tmp_path / "clone"
    clone_or_reuse(origin.as_uri(), dest)
    assert (dest / ".git" / "codeatlas-clone").is_file()
    found = discover(dest, Config(), lambda _language: Tier.STRUCTURAL)
    assert [f.path for f in found.files] == ["a.py"]


def test_unknown_ref_fails(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    origin = make_repo({"a.txt": "1\n"})
    with pytest.raises(IntakeError, match="not found"):
        clone_or_reuse(origin.as_uri(), tmp_path / "clone", "no-such-branch")


def test_open_local_path(make_repo: Callable[..., Path]) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    result = open_source(str(origin), Config())
    assert result.root == origin.resolve()
    assert result.repo == "origin"
    assert result.commit_sha == head_sha(origin)


def test_relative_path_is_stored_absolute(
    make_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queries run from other folders (an MCP server, `--git`) must still find the checkout.

    The source as typed (`.`) would point at whatever folder the query runs in.
    """
    origin = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(origin)
    result = open_source(".", Config())
    assert Path(result.source).is_absolute()
    assert Path(result.source) == origin.resolve()


def test_open_folder_outside_git(tmp_path: Path) -> None:
    result = open_source(str(tmp_path), Config())
    assert result.commit_sha is None


def test_untracked_folder_inside_a_repository_gets_no_sha(
    make_repo: Callable[..., Path],
) -> None:
    outer = make_repo({"README.md": "the outer repository has a commit\n"})
    project = outer / "project"
    project.mkdir()
    (project / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    result = open_source(str(project), Config())
    assert result.commit_sha is None  # the outer HEAD does not describe this folder


def test_open_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(IntakeError):
        open_source(str(tmp_path / "missing"), Config())


def test_open_rejects_non_github_url() -> None:
    with pytest.raises(IntakeError):
        open_source("https://example.com/owner/repo", Config())


def test_file_limit_stops_discovery(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    config = replace(Config(), max_files=3)
    found = discover(tmp_path, config, lambda _language: Tier.STRUCTURAL)
    assert len(found.files) == 3
    assert found.limits_hit == ("max_files",)


def test_no_limit_hit_at_exact_count(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    found = discover(tmp_path, replace(Config(), max_files=3), lambda _l: Tier.STRUCTURAL)
    assert len(found.files) == 3
    assert found.limits_hit == ()
