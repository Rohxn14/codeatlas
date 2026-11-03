
from ts_samples import parse_sample

from codeatlas.models import Node, NodeKind, ParseResult, RawCall, Span


def _by_key(result: ParseResult) -> dict[str, Node]:
    return {node.key: node for node in result.nodes}


def test_classes_and_interfaces() -> None:
    nodes = _by_key(parse_sample("shapes.ts"))
    assert [(n.kind, n.qualname) for n in nodes.values()] == [
        (NodeKind.MODULE, ""),
        (NodeKind.INTERFACE, "Shape"),
        (NodeKind.INTERFACE, "Named"),
        (NodeKind.CLASS, "Square"),
        (NodeKind.FUNCTION, "Square.constructor"),
        (NodeKind.FUNCTION, "Square.area"),
        (NodeKind.FUNCTION, "Square.save"),
        (NodeKind.FUNCTION, "Square.label#98f3"),
        (NodeKind.FUNCTION, "Square.label#1f9e"),
        (NodeKind.CLASS, "Hidden"),
    ]  # the type alias `Point` is skipped in v1
    square = nodes["web/shapes.ts::Square"]
    assert square.span == Span(15, 39, 7, 1)
    assert square.signature == "class Square extends Base<Shape> implements Shape, Named"
    assert square.docstring == "A square that knows its own area."
    assert square.attrs == {
        "bases": ["Base<Shape>", "Shape", "Named"],
        "decorators": ["Serializable()"],
        "exported": True,
    }
    assert nodes["web/shapes.ts::Named"].attrs == {"bases": ["Shape"], "exported": False}
    assert nodes["web/shapes.ts::Hidden"].attrs["exported"] is False


def test_methods() -> None:
    nodes = _by_key(parse_sample("shapes.ts"))
    area = nodes["web/shapes.ts::Square.area"]
    assert area.owner_key == "web/shapes.ts::Square"
    assert area.signature == "area(): number"
    assert area.docstring == "The area, in square units."
    assert area.attrs == {"decorators": ["Memo()"], "is_async": False, "exported": True}
    save = nodes["web/shapes.ts::Square.save"]
    assert save.signature == "async save(store: Store): Promise<void>"
    assert save.attrs["is_async"] is True
    getter = nodes["web/shapes.ts::Square.label#98f3"]
    assert (getter.name, getter.signature) == ("label", "get label()")


def test_functions() -> None:
    result = parse_sample("functions.ts")
    rows = [
        (n.qualname, n.signature, n.attrs["is_async"], n.attrs["exported"])
        for n in result.nodes[1:]
    ]
    assert rows == [
        ("add", "const add = (a: number, b: number): number =>", False, True),
        ("fetchAll", "const fetchAll = async () =>", True, True),
        ("local", "const local = function (x: string)", False, False),
        ("outer", "function outer()", False, True),
        ("outer.inner", "function inner()", False, False),
        ("api.getUser", "getUser(id: string)", False, True),
        ("api.remove", "remove: async (id: string) =>", True, True),
        ("default", "export default () =>", False, True),
    ]  # methods of the unexported `internal` object are not functions
    assert all(n.owner_key is None for n in result.nodes)
    assert result.nodes[2].span == Span(3, 6, 7, 2)  # from `const`, after `export `


def test_anonymous_callbacks_belong_to_the_named_function() -> None:
    f = "web/functions.ts::"
    assert parse_sample("functions.ts").calls == (
        RawCall(f"{f}fetchAll", "load", "load", None, 4),
        RawCall(f"{f}fetchAll", "rows.map", "map", "rows", 5),
        RawCall(f"{f}fetchAll", "format", "format", None, 5),
        RawCall(f"{f}local", "x.trim", "trim", "x", 9),
        RawCall(f"{f}outer.inner", "helper", "helper", None, 14),
        RawCall(f"{f}outer", "inner", "inner", None, 16),
        RawCall(f"{f}api.getUser", "request", "request", None, 21),
        RawCall(f"{f}api.remove", "request", "request", None, 23),
        RawCall(f"{f}default", "local", "local", None, 31),
    )


def test_react_component_renders_children_as_calls() -> None:
    result = parse_sample("UserPage.tsx")
    page = "web/UserPage.tsx::UserPage"
    assert [(n.kind, n.key) for n in result.nodes[1:]] == [(NodeKind.FUNCTION, page)]
    assert result.calls == (
        RawCall(page, "useUser", "useUser", None, 5),
        RawCall(page, "UserCard", "UserCard", None, 8),
        RawCall(page, "Avatar.Small", "Small", "Avatar", 9),
    )  # <section> and <span> are HTML tags, not components


def test_nested_describe_blocks() -> None:
    result = parse_sample("users.test.ts")
    tests = [(n.kind, n.name, n.qualname, n.attrs["test_id"]) for n in result.nodes[1:]]
    assert tests == [
        (NodeKind.TEST, "fetches a user", "UserApi > fetches a user", "UserApi > fetches a user"),
        (
            NodeKind.TEST,
            "rejects a missing user",
            "UserApi > errors > rejects a missing user",
            "UserApi > errors > rejects a missing user",
        ),
        (NodeKind.TEST, "retries", "UserApi > errors > retries", "UserApi > errors > retries"),
        (NodeKind.TEST, "top level", "top level", "top level"),
    ]
    assert result.nodes[1].span == Span(6, 9, 2, 4)


def test_calls_inside_a_test_belong_to_it() -> None:
    t = "web/users.test.ts::"
    fetches = f"{t}UserApi > fetches a user"
    missing = f"{t}UserApi > errors > rejects a missing user"
    assert parse_sample("users.test.ts").calls == (
        RawCall(t, "describe", "describe", None, 3),
        RawCall(t, "beforeEach", "beforeEach", None, 4),
        RawCall(t, "reset", "reset", None, 4),
        RawCall(t, "it", "it", None, 6),
        RawCall(fetches, "getUser", "getUser", None, 7),
        RawCall(fetches, "expect(...).toBe", "toBe", "expect(...)", 8),
        RawCall(fetches, "expect", "expect", None, 8),
        RawCall(t, "describe", "describe", None, 11),
        RawCall(t, "test", "test", None, 12),
        RawCall(missing, "expect(...).rejects.toThrow", "toThrow", "expect(...).rejects", 13),
        RawCall(missing, "expect", "expect", None, 13),
        RawCall(missing, "getUser", "getUser", None, 13),
        RawCall(t, "it.skip", "skip", "it", 16),
        RawCall(f"{t}UserApi > errors > retries", "retry", "retry", None, 17),
        RawCall(t, "test", "test", None, 22),
    )


def test_it_outside_a_test_file_is_an_ordinary_call() -> None:
    from codeatlas.indexer.languages.typescript.adapter import TypeScriptAdapter

    result = TypeScriptAdapter().parse("src/a.ts", b'it("x", () => go());\n', "s@1")
    assert [n.kind for n in result.nodes] == [NodeKind.MODULE]
    assert [c.caller_key for c in result.calls] == ["src/a.ts::", "src/a.ts::"]


def test_repeated_test_names_get_distinct_keys() -> None:
    from codeatlas.indexer.languages.typescript.adapter import JavaScriptAdapter

    source = b'describe("A", () => { it("works", () => {}); it("works", () => {}); });\n'
    result = JavaScriptAdapter().parse("__tests__/a.js", source, "s@1")
    keys = [n.key for n in result.nodes[1:]]
    assert len(set(keys)) == 2
    assert keys[0].startswith("__tests__/a.js::A > works#")
    assert keys[1] == keys[0] + "-2"
    assert {n.attrs["test_id"] for n in result.nodes[1:]} == {"A > works"}


def test_non_utf8_bytes_do_not_lose_the_file() -> None:
    from codeatlas.indexer.languages.typescript.adapter import TypeScriptAdapter

    result = TypeScriptAdapter().parse(
        "a.ts", b'class A extends B<"caf\xe9"> { run() {} }\n', "s@0"
    )
    assert [n.qualname for n in result.nodes[1:]] == ["A", "A.run"]


def test_class_expressions_become_classes() -> None:
    from codeatlas.indexer.languages.typescript.adapter import JavaScriptAdapter

    result = JavaScriptAdapter().parse("a.js", b"""module.exports = class Repo extends Base {
  save() { helper(); }
};
const Svc = class {
  run() {}
};
""", "s@0")
    kinds = [(n.qualname, n.kind.value) for n in result.nodes[1:]]
    assert kinds == [("Repo", "class"), ("Repo.save", "function"),
                     ("Svc", "class"), ("Svc.run", "function")]
    assert [(c.caller_key, c.name) for c in result.calls] == [("a.js::Repo.save", "helper")]


def test_files_in_test_folders_are_test_files() -> None:
    from codeatlas.indexer.languages.typescript.symbols import is_test_file

    assert is_test_file("test/app.router.js")  # mocha's layout (express, lodash)
    assert is_test_file("packages/a/tests/util.ts") and is_test_file("spec/x.js")
    assert is_test_file("src/user.test.ts") and is_test_file("src/__tests__/a.js")
    assert not is_test_file("src/testing.ts") and not is_test_file("src/contest/a.ts")
