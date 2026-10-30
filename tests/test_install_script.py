import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "install_pkgs.py"
spec = importlib.util.spec_from_file_location("install_pkgs", SCRIPT)
assert spec and spec.loader
install_pkgs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_pkgs)


def test_exits_zero_outside_the_cloud() -> None:
    env = {**os.environ, "CLAUDE_CODE_REMOTE": "false"}
    done = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, check=False)
    assert done.returncode == 0
    assert done.stdout == b""


def test_needs_install_follows_the_stamp(tmp_path: Path) -> None:
    stamp = tmp_path / "install.sha256"
    assert install_pkgs.needs_install(stamp, "abc")
    stamp.write_text("abc\n", encoding="utf-8")
    assert not install_pkgs.needs_install(stamp, "abc")
    assert install_pkgs.needs_install(stamp, "def")


def test_skips_install_when_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stamp = tmp_path / "install.sha256"
    stamp.write_text(install_pkgs.pyproject_hash() + "\n", encoding="utf-8")
    monkeypatch.setattr(install_pkgs, "STAMP", stamp)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")

    def fail() -> bool:
        raise AssertionError("install should be skipped")

    monkeypatch.setattr(install_pkgs, "install", fail)
    assert install_pkgs.main() == 0


def test_failure_still_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install_pkgs, "STAMP", tmp_path / "install.sha256")
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setattr(install_pkgs, "install", lambda: False)
    assert install_pkgs.main() == 0
    assert not (tmp_path / "install.sha256").exists()
