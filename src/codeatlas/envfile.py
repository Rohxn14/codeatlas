"""Read CodeAtlas's own settings, above all the LLM keys, from a `.env` file.

The owner keeps keys in a gitignored `.env` in the project folder, as in his earlier
projects (D-45), rather than typing them into a terminal: Windows PowerShell saves every
typed line in a plain-text history file.

Three rules keep this narrow:

- Only names CodeAtlas uses are taken (the two keys and `CODEATLAS_*` settings). A `.env`
  in another project's folder may hold that project's secrets; they are left alone.
- A variable already set in the environment wins over the file.
- Only a real command line reads the file (`cli.main()` called without arguments). Tests
  call `main([...])`, so they never pick up the owner's keys.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

from dotenv import dotenv_values

KEY_NAMES = ("GROQ_API_KEY", "GEMINI_API_KEY")
SETTING_PREFIX = "CODEATLAS_"


def is_codeatlas_name(name: str) -> bool:
    """True for the names CodeAtlas reads: the LLM keys and its own settings."""
    return name in KEY_NAMES or name.startswith(SETTING_PREFIX)


def load_env_file(
    path: Path | None = None, environ: MutableMapping[str, str] | None = None
) -> list[str]:
    """Copy CodeAtlas's names from `path` (default `./.env`) into the environment.

    Returns the names that were set, never their values. A missing file sets nothing.
    """
    path = Path.cwd() / ".env" if path is None else path
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return []
    # utf-8-sig: Notepad may save the file with a byte-order mark. interpolate=False: a
    # key is taken exactly as written, even if it holds a "$".
    values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    loaded = []
    for name, value in values.items():
        if is_codeatlas_name(name) and value and not environ.get(name):
            environ[name] = value
            loaded.append(name)
    return sorted(loaded)
