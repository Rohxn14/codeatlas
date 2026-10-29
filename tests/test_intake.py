from pathlib import Path

import pytest
from helpers import git, write

from codeatlas.indexer.intake import (
    GitHubRef,
    clone_or_reuse,
    content_sha,
    head_sha,
    intake,
    is_url,
    parse_github_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/pallets/click", GitHubRef("pallets", "click")),
        ("https://github.com/pallets/click/", GitHubRef("pallets", "click")),
        ("https://github.com/pallets/click.git", GitHubRef("pallets", "click")),
        ("https://github.com/pallets/click@8.1.7", GitHubRef("pallets", "click", "8.1.7")),
        ("https://github.com/a-b/c.d_e@feature/x", GitHubRef("a-b", "c.d_e", "feature/x")),
    ],
)
def test_parse_valid_urls(url: str, expected: GitHubRef) -> None:
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/pallets/click",
        "https://github.com.evil.com/pallets/click",
        "http://github.com/pallets/click",
        "https://github.com/pallets",
        "https://github.com/pallets/click/tree/main",
        "https://github.com/pallets/click@--upload-pack=x",
        "https://github.com/pallets/..",
    ],
)
def test_parse_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_ref_properties() -> None:
    ref = parse_github_url("https://github.com/pallets/click")
    assert ref.clone_url == "https://github.com/pallets/click.git"
    assert ref.folder_name == "pallets__click"


def test_is_url() -> None:
    assert is_url("https://github.com/a/b")
    assert not is_url("C:/Users/me/repo")
    assert not is_url("tests/data")


def test_clone_then_reuse_then_update(make_repo, tmp_path: Path) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    dest = tmp_path / "repos" / "owner__origin"

    sha, reused = clone_or_reuse(origin.as_uri(), dest)
    assert not reused
    assert sha == head_sha(origin)
    assert (dest / "a.py").read_text() == "x = 1\n"

    assert clone_or_reuse(origin.as_uri(), dest) == (sha, True)

    write(origin, "b.py", "y = 2\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "second")
    new_sha, reused = clone_or_reuse(origin.as_uri(), dest)
    assert not reused
    assert new_sha == head_sha(origin) != sha
    assert (dest / "b.py").is_file()


def test_clone_keeps_full_history(make_repo, tmp_path: Path) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    write(origin, "a.py", "x = 2\n")
    git(origin, "commit", "-q", "-am", "second")
    dest = tmp_path / "clone"
    clone_or_reuse(origin.as_uri(), dest)
    assert len(git(dest, "log", "--oneline").splitlines()) == 2


def test_clone_at_ref(make_repo, tmp_path: Path) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    git(origin, "tag", "v1")
    first = head_sha(origin)
    write(origin, "a.py", "x = 2\n")
    git(origin, "commit", "-q", "-am", "second")
    sha, _ = clone_or_reuse(origin.as_uri(), tmp_path / "clone", "v1")
    assert sha == first


def test_clone_refuses_non_empty_non_git_folder(make_repo, tmp_path: Path) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    dest = tmp_path / "busy"
    write(dest, "keep.txt", "mine")
    with pytest.raises(RuntimeError, match="not a git clone"):
        clone_or_reuse(origin.as_uri(), dest)


def test_intake_local_path(make_repo) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    checkout = intake(str(origin), Path("unused"))
    assert checkout.root == origin.resolve()
    assert checkout.repo == "origin"
    assert checkout.commit_sha == head_sha(origin)


def test_intake_local_path_outside_git(tmp_path: Path) -> None:
    write(tmp_path / "plain", "a.txt", "hi")
    checkout = intake(str(tmp_path / "plain"), Path("unused"))
    assert checkout.commit_sha is None


def test_intake_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        intake(str(tmp_path / "nope"), Path("unused"))


def test_intake_rejects_other_hosts(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        intake("https://example.com/a/b", tmp_path)


def test_content_sha_is_order_independent() -> None:
    a = content_sha([("a.py", "1"), ("b.py", "2")])
    assert a == content_sha([("b.py", "2"), ("a.py", "1")])
    assert a != content_sha([("a.py", "1"), ("b.py", "3")])
