"""SessionStart hook: install CodeAtlas with dev extras in cloud sessions.

Runs on every session start and resume, so it must be fast and must never fail the
session: it exits at once outside the cloud (`CLAUDE_CODE_REMOTE` is not `true`),
skips the install when `pyproject.toml` has not changed since the last success, and
always exits 0, reporting problems on stderr instead.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / ".codeatlas" / "install.sha256"


def pyproject_hash(root: Path = ROOT) -> str:
    return hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()


def needs_install(stamp: Path, current: str) -> bool:
    return not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != current


def install(root: Path = ROOT) -> bool:
    """pip install -e .[dev]; retry once for a system Python that refuses (PEP 668)."""
    command = [sys.executable, "-m", "pip", "install", "--quiet", "-e", ".[dev]"]
    for extra in ([], ["--break-system-packages"]):
        done = subprocess.run([*command, *extra], cwd=root, capture_output=True, text=True)
        if done.returncode == 0:
            return True
        if "externally-managed-environment" not in done.stderr:
            break
    print(f"install_pkgs: pip failed:\n{done.stderr.strip()}", file=sys.stderr)
    return False


def main() -> int:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    try:
        current = pyproject_hash()
        if not needs_install(STAMP, current):
            return 0
        if install():
            STAMP.parent.mkdir(parents=True, exist_ok=True)
            STAMP.write_text(current + "\n", encoding="utf-8")
    except Exception as exc:  # the hook must never block a session
        print(f"install_pkgs: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
