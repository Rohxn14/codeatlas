"""Read a `.scip` index with the standard library alone.

A SCIP index is a protobuf message. Decoding it needs either the `protobuf` package
plus generated classes, or the `scip` command-line tool; neither is a CodeAtlas
dependency. The protobuf wire format is small (a field number, a wire type, then a
varint or a length-prefixed blob), and the oracle needs only a handful of fields, so
this module decodes those fields by hand against the published schema
(https://github.com/sourcegraph/scip/blob/main/scip.proto). Fields it does not need
are skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Wire types from the protobuf encoding spec.
_VARINT, _I64, _LEN, _I32 = 0, 1, 2, 5

# SymbolRole bit flags (scip.proto).
ROLE_DEFINITION = 0x1
ROLE_IMPORT = 0x2


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One mention of a symbol: 0-based (start_line, start_col, end_line, end_col)."""

    range: tuple[int, int, int, int]
    symbol: str
    roles: int
    enclosing_range: tuple[int, int, int, int] | None = None

    @property
    def is_definition(self) -> bool:
        return bool(self.roles & ROLE_DEFINITION)

    @property
    def is_import(self) -> bool:
        return bool(self.roles & ROLE_IMPORT)


@dataclass(frozen=True, slots=True)
class Document:
    """One source file of the index, with its occurrences in file order."""

    relative_path: str
    language: str
    occurrences: tuple[Occurrence, ...]


@dataclass(frozen=True, slots=True)
class Index:
    project_root: str
    tool: str
    documents: tuple[Document, ...]


def read_index(path: Path) -> Index:
    """Decode the `.scip` file at `path`."""
    return decode_index(path.read_bytes())


def decode_index(data: bytes) -> Index:
    project_root, tool = "", ""
    documents: list[Document] = []
    for number, value in _fields(data):
        if number == 1 and isinstance(value, bytes):  # Metadata
            project_root, tool = _metadata(value)
        elif number == 2 and isinstance(value, bytes):  # Document
            documents.append(_document(value))
    return Index(project_root, tool, tuple(documents))


def index_to_dict(index: Index) -> dict[str, object]:
    """A JSON-ready copy of a decoded index, for test fixtures and debugging."""
    return {
        "project_root": index.project_root,
        "tool": index.tool,
        "documents": [
            {
                "relative_path": d.relative_path,
                "language": d.language,
                "occurrences": [
                    {"range": list(o.range), "symbol": o.symbol, "roles": o.roles,
                     "enclosing_range": list(o.enclosing_range) if o.enclosing_range else None}
                    for o in d.occurrences
                ],
            }
            for d in index.documents
        ],
    }


def index_from_dict(data: dict) -> Index:
    """The inverse of `index_to_dict`."""
    documents = tuple(
        Document(
            d["relative_path"],
            d.get("language", ""),
            tuple(
                Occurrence(
                    tuple(o["range"]),
                    o["symbol"],
                    o.get("roles", 0),
                    tuple(o["enclosing_range"]) if o.get("enclosing_range") else None,
                )
                for o in d["occurrences"]
            ),
        )
        for d in data["documents"]
    )
    return Index(data.get("project_root", ""), data.get("tool", ""), documents)


def _metadata(data: bytes) -> tuple[str, str]:
    project_root, tool = "", ""
    for number, value in _fields(data):
        if number == 2 and isinstance(value, bytes):  # ToolInfo
            for sub, name in _fields(value):
                if sub == 1 and isinstance(name, bytes):
                    tool = name.decode("utf-8")
        elif number == 3 and isinstance(value, bytes):
            project_root = value.decode("utf-8")
    return project_root, tool


def _document(data: bytes) -> Document:
    path, language = "", ""
    occurrences: list[Occurrence] = []
    for number, value in _fields(data):
        if number == 1 and isinstance(value, bytes):
            path = value.decode("utf-8")
        elif number == 2 and isinstance(value, bytes):
            occurrences.append(_occurrence(value))
        elif number == 4 and isinstance(value, bytes):
            language = value.decode("utf-8")
    return Document(path, language, tuple(occurrences))


def _occurrence(data: bytes) -> Occurrence:
    range_: list[int] = []
    enclosing: list[int] = []
    symbol, roles = "", 0
    for number, value in _fields(data):
        if number == 1:
            range_.extend(_int32s(value))
        elif number == 2 and isinstance(value, bytes):
            symbol = value.decode("utf-8")
        elif number == 3 and isinstance(value, int):
            roles = value
        elif number == 7:
            enclosing.extend(_int32s(value))
    return Occurrence(_range(range_), symbol, roles, _range(enclosing) if enclosing else None)


def _range(values: list[int]) -> tuple[int, int, int, int]:
    """SCIP stores a single-line range as three numbers and a multi-line one as four."""
    if len(values) == 3:
        return (values[0], values[1], values[0], values[2])
    if len(values) == 4:
        return (values[0], values[1], values[2], values[3])
    raise ValueError(f"a SCIP range has 3 or 4 numbers, got {values}")


def _int32s(value: int | bytes) -> list[int]:
    """A repeated int32: packed into one blob, or one varint per field."""
    if isinstance(value, int):
        return [value]
    out: list[int] = []
    pos = 0
    while pos < len(value):
        number, pos = _varint(value, pos)
        out.append(number)
    return out


def _fields(data: bytes) -> Iterator[tuple[int, int | bytes]]:
    """Yield (field number, value) for each field of one message; varints come as int."""
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if wire == _VARINT:
            value, pos = _varint(data, pos)
            yield number, value
        elif wire == _LEN:
            size, pos = _varint(data, pos)
            yield number, data[pos : pos + size]
            pos += size
        elif wire == _I64:
            pos += 8
        elif wire == _I32:
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire} at byte {pos}")


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result, shift = 0, 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
