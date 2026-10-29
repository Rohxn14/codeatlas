from pathlib import Path

import pytest

from codeatlas.config import Config, Limits, load_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "codeatlas.toml")
    assert config == Config()
    assert config.limits == Limits(20_000, 1_000_000, 300.0, 2_000)
    assert config.repos_dir == Path(".codeatlas") / "repos"


def test_reads_limits_and_ignores_other_sections(tmp_path: Path) -> None:
    path = tmp_path / "codeatlas.toml"
    path.write_text(
        '[limits]\nmax_files = 10\nmax_seconds = 5\n\n[paths]\nworkdir = "w"\n\n[llm]\nx = 1\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.limits.max_files == 10
    assert config.limits.max_seconds == 5.0
    assert config.limits.max_file_bytes == 1_000_000
    assert config.repos_dir == Path("w") / "repos"


@pytest.mark.parametrize("body", ["max_files = 0", "max_files = 'many'", "max_filez = 3"])
def test_rejects_bad_limits(tmp_path: Path, body: str) -> None:
    path = tmp_path / "codeatlas.toml"
    path.write_text(f"[limits]\n{body}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_example_file_matches_defaults() -> None:
    example = Path(__file__).parent.parent / "codeatlas.toml"
    assert load_config(example) == Config()
