"""SessionStart hook: install CodeAtlas with dev extras in a Claude Code cloud session.

Runs only when CLAUDE_CODE_REMOTE is "true", so local sessions on the owner's machine are
untouched. Skips the install when pyproject.toml is unchanged since the last success, and
always exits 0 so a failed install never blocks the session from starting.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / ".codeatlas" / "install.sha256"


def main() -> int:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    digest = hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()
    if STAMP.is_file() and STAMP.read_text(encoding="utf-8").strip() == digest:
        print("codeatlas: dependencies up to date")
        return 0
    if _pip_install() or _pip_install("--break-system-packages"):
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(digest, encoding="utf-8")
        print("codeatlas: installed with dev extras")
    else:
        print("codeatlas: install failed; run `pip install -e .[dev]` by hand", file=sys.stderr)
    return 0


def _pip_install(*extra: str) -> bool:
    """Editable install; the retry flag covers system Pythons that refuse plain pip."""
    command = [sys.executable, "-m", "pip", "install", "--quiet", *extra, "-e", ".[dev]"]
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # the hook must never fail the session
        print(f"codeatlas: install hook error: {exc!r}", file=sys.stderr)
        sys.exit(0)
