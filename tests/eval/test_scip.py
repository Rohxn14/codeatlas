"""The hand-written SCIP decoder and symbol parser."""

from eval.oracle.convert import Descriptor, parse_descriptors, qualname, symbol_kind
from eval.oracle.scip import decode_index, index_from_dict, index_to_dict


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    return varint(number << 3 | 2) + varint(len(value)) + value


def packed(*numbers: int) -> bytes:
    return b"".join(varint(n) for n in numbers)


def test_decodes_documents_occurrences_and_both_range_forms():
    definition = (
        field(1, packed(4, 8, 4, 11))  # three-number range: one line
        + field(2, b"scip-python python app 0 m/f().")
        + field(3, 1)
        + field(7, packed(4, 4, 9, 20))
    )
    reference = field(1, packed(300, 2, 301, 5)) + field(2, b"local 1") + field(3, 8)
    document = field(1, b"src/m.py") + field(2, definition) + field(2, reference)
    document += field(4, b"python") + field(99, b"ignored")
    metadata = field(2, field(1, b"scip-python")) + field(3, b"file:///repo")
    index = decode_index(field(1, metadata) + field(2, document))

    assert index.project_root == "file:///repo"
    assert index.tool == "scip-python"
    (doc,) = index.documents
    assert (doc.relative_path, doc.language) == ("src/m.py", "python")
    first, second = doc.occurrences
    assert first.range == (4, 8, 4, 11)
    assert first.enclosing_range == (4, 4, 9, 20)
    assert first.is_definition and not second.is_definition
    assert second.range == (300, 2, 301, 5)  # multi-byte varints
    assert second.enclosing_range is None


def test_unpacked_repeated_ints_are_accepted():
    occurrence = b"".join(field(1, n) for n in (1, 2, 3)) + field(2, b"local 0")
    index = decode_index(field(2, field(1, b"a.py") + field(2, occurrence)))
    assert index.documents[0].occurrences[0].range == (1, 2, 1, 3)


def test_dict_round_trip():
    occurrence = field(1, packed(0, 0, 3)) + field(2, b"local 0") + field(7, packed(0, 0, 2, 1))
    index = decode_index(field(2, field(1, b"a.py") + field(2, occurrence)))
    assert index_from_dict(index_to_dict(index)) == index


def test_python_method_symbol():
    symbol = "scip-python python polyglot_app 0 `backend.services`/UserService#create_user()."
    descriptors = parse_descriptors(symbol)
    assert descriptors == [
        Descriptor("backend.services", "namespace"),
        Descriptor("UserService", "type"),
        Descriptor("create_user", "method"),
    ]
    assert qualname(descriptors) == "UserService.create_user"
    assert symbol_kind(descriptors) == "function"


def test_typescript_symbols_drop_the_file_namespaces():
    descriptors = parse_descriptors(
        "scip-typescript npm polyglot-web 0.1.0 src/api/`client.ts`/UserApi#getUser()."
    )
    assert qualname(descriptors) == "UserApi.getUser"
    nested = parse_descriptors("scip-python python app 0 `m`/logged().wrapper().")
    assert qualname(nested) == "logged.wrapper"


def test_symbol_kinds_and_rejects():
    assert symbol_kind(parse_descriptors("scip-python python app 0 `m`/User#")) == "class"
    assert symbol_kind(parse_descriptors("scip-python python app 0 `m`/f().(x)")) is None
    assert symbol_kind(parse_descriptors("scip-python python app 0 `m`/CONST.")) is None
    assert parse_descriptors("local 12") is None
    assert parse_descriptors("not a symbol") is None


def test_escaped_spaces_and_backticks():
    descriptors = parse_descriptors("scheme npm my  pkg 1.0 `a``b`/run(+1).")
    assert descriptors == [Descriptor("a`b", "namespace"), Descriptor("run", "method")]
