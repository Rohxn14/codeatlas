from pathlib import Path

import pytest

from codeatlas.config import Config, Deadline, config_from_dict, load_config


def test_defaults_when_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config == Config()
    assert (config.max_files, config.max_file_bytes, config.max_seconds) == (20_000, 1_000_000, 300)
    assert config.max_history_commits == 2_000


def test_reads_toml(tmp_path: Path) -> None:
    path = tmp_path / "codeatlas.toml"
    path.write_text("[limits]\nmax_files = 5\n[history]\nmax_history_commits = 10\n")
    config = load_config(path)
    assert config.max_files == 5
    assert config.max_history_commits == 10
    assert config.max_file_bytes == 1_000_000


def test_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        config_from_dict({"limits": {"max_files": "many"}})
    with pytest.raises(ValueError):
        config_from_dict({"limits": {"max_seconds": 0}})


def test_example_config_matches_defaults() -> None:
    example = Path(__file__).parents[1] / "codeatlas.toml"
    assert load_config(example) == Config()


def test_deadline() -> None:
    assert not Deadline(60).expired()
    assert Deadline(0).expired()
