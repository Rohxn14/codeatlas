"""Parse a sample from tests/data/typescript with the adapter its extension selects.

A plain module, not a conftest: the top-level tests import `conftest` by name, and a
second conftest on the path would shadow it.
"""

from pathlib import Path

from codeatlas.indexer.languages.typescript.adapter import (
    JavaScriptAdapter,
    TsxAdapter,
    TypeScriptAdapter,
)
from codeatlas.models import ParseResult

SAMPLES = Path(__file__).parents[2] / "data" / "typescript"
SNAPSHOT = "web@0123456789ab"
_ADAPTERS = {".ts": TypeScriptAdapter(), ".tsx": TsxAdapter()}
_JAVASCRIPT = JavaScriptAdapter()


def parse_sample(name: str) -> ParseResult:
    adapter = _ADAPTERS.get(Path(name).suffix, _JAVASCRIPT)
    return adapter.parse(f"web/{name}", (SAMPLES / name).read_bytes(), SNAPSHOT)
