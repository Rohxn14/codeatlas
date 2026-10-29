import pytest
from helpers import DATA

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.generic import TagsAdapter, TextAdapter
from codeatlas.indexer.generic.grammars import GRAMMARS
from codeatlas.models import NodeKind, ParseResult, RawCall, Tier

SNAPSHOT = "demo@0123456789ab"


def _parse(language: str, rel: str) -> ParseResult:
    adapter = TagsAdapter(GRAMMARS[language])
    return adapter.parse(rel, (DATA / rel).read_bytes(), SNAPSHOT)


def _defs(result: ParseResult) -> dict[str, tuple[NodeKind, str | None]]:
    return {n.qualname: (n.kind, n.owner_key) for n in result.nodes[1:]}


def _calls(result: ParseResult) -> list[tuple[str, str, str, str | None]]:
    return [(c.caller_key, c.callee_text, c.name, c.receiver) for c in result.calls]


def _assert_module_first(result: ParseResult, rel: str) -> None:
    module = result.nodes[0]
    assert module.kind is NodeKind.MODULE
    assert module.key == f"{rel}::"
    assert module.qualname == ""
    assert module.id == f"{SNAPSHOT}/{rel}::"
    assert sum(n.kind is NodeKind.MODULE for n in result.nodes) == 1


def test_go() -> None:
    rel = "generic/server.go"
    result = _parse("go", rel)
    _assert_module_first(result, rel)
    assert result.errors == ()
    assert result.tier is Tier.STRUCTURAL
    assert _defs(result) == {
        "Store": (NodeKind.INTERFACE, None),
        "Server": (NodeKind.CLASS, None),
        "NewServer": (NodeKind.FUNCTION, None),
        "Server.Start": (NodeKind.FUNCTION, f"{rel}::Server"),
        "helper": (NodeKind.FUNCTION, None),
    }
    assert _calls(result) == [
        (f"{rel}::Server.Start", "fmt.Println", "Println", "fmt"),
        (f"{rel}::Server.Start", "s.store.Save", "Save", "s.store"),
        (f"{rel}::helper", "NewServer", "NewServer", None),
    ]
    start = next(n for n in result.nodes if n.qualname == "Server.Start")
    assert (start.span.start_line, start.span.end_line) == (18, 21)
    assert start.signature == "func (s *Server) Start() error"
    assert start.attrs == {"receiver": "Server"}


def test_java() -> None:
    rel = "generic/UserService.java"
    result = _parse("java", rel)
    _assert_module_first(result, rel)
    assert _defs(result) == {
        "Repository": (NodeKind.INTERFACE, None),
        "Repository.save": (NodeKind.FUNCTION, f"{rel}::Repository"),
        "UserService": (NodeKind.CLASS, None),
        "UserService.register": (NodeKind.FUNCTION, f"{rel}::UserService"),
        "UserService.validate": (NodeKind.FUNCTION, f"{rel}::UserService"),
    }
    assert _calls(result) == [
        (f"{rel}::UserService.register", "validate", "validate", None),
        (f"{rel}::UserService.register", "this.repo.save", "save", "this.repo"),
        (f"{rel}::UserService.validate", "System.out.println", "println", "System.out"),
        (f"{rel}::UserService.validate", "name.trim", "trim", "name"),
    ]
    assert result.calls[0].line == 15


def test_rust() -> None:
    rel = "generic/shapes.rs"
    result = _parse("rust", rel)
    _assert_module_first(result, rel)
    assert _defs(result) == {
        "Shape": (NodeKind.INTERFACE, None),
        "Shape.describe": (NodeKind.FUNCTION, f"{rel}::Shape"),
        "Circle": (NodeKind.CLASS, None),
        "Circle.new": (NodeKind.FUNCTION, f"{rel}::Circle"),
        "Circle.area": (NodeKind.FUNCTION, f"{rel}::Circle"),
        "square": (NodeKind.FUNCTION, None),
        "main": (NodeKind.FUNCTION, None),
    }
    assert _calls(result) == [
        (f"{rel}::Shape.describe", "format", "format", None),
        (f"{rel}::Circle.area", "square", "square", None),
        (f"{rel}::main", "Circle::new", "new", "Circle"),
        (f"{rel}::main", "println", "println", None),
    ]


def test_method_outside_its_class_file_has_no_owner_key() -> None:
    """A Go method whose struct lives in another file keeps its receiver but no owner key."""
    source = b"package p\n\nfunc (s *Server) Stop() {}\n"
    result = TagsAdapter(GRAMMARS["go"]).parse("stop.go", source, SNAPSHOT)
    stop = result.nodes[1]
    assert stop.qualname == "Server.Stop"
    assert stop.owner_key is None
    assert stop.attrs == {"receiver": "Server"}


def test_repeated_names_get_unique_keys() -> None:
    source = b"class A {\n  void f(int x) {}\n  void f(String s) {}\n}\n"
    result = TagsAdapter(GRAMMARS["java"]).parse("A.java", source, SNAPSHOT)
    assert [n.qualname for n in result.nodes[1:]] == ["A", "A.f", "A.f#2"]
    assert len({n.key for n in result.nodes}) == len(result.nodes)


def test_nested_functions_and_top_level_calls() -> None:
    source = b"def outer():\n    def inner():\n        work()\n    inner()\n\nsetup()\n"
    result = TagsAdapter(GRAMMARS["python"]).parse("m.py", source, SNAPSHOT)
    assert [n.qualname for n in result.nodes[1:]] == ["outer", "outer.inner"]
    assert result.nodes[2].owner_key is None  # nested function, not a method
    assert result.calls == (
        RawCall("m.py::outer.inner", "work", "work", None, 3),
        RawCall("m.py::outer", "inner", "inner", None, 4),
        RawCall("m.py::", "setup", "setup", None, 6),
    )


def test_broken_file_records_errors_without_raising() -> None:
    rel = "broken/broken.go"
    result = _parse("go", rel)
    _assert_module_first(result, rel)
    assert result.errors
    assert any("line 7" in e for e in result.errors)
    assert "ok" in {n.name for n in result.nodes}  # the valid part is still extracted


@pytest.mark.parametrize("source", [b"", b"\x00\xff\xfe garbage {{{", "π = 1\n".encode()])
def test_odd_input_never_raises(source: bytes) -> None:
    result = TagsAdapter(GRAMMARS["rust"]).parse("x.rs", source, SNAPSHOT)
    assert result.nodes[0].kind is NodeKind.MODULE


def test_extraction_failure_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = TagsAdapter(GRAMMARS["go"])

    def boom(*args: object) -> None:
        raise RuntimeError("bad capture")

    monkeypatch.setattr(adapter, "_extract", boom)
    result = adapter.parse("a.go", b"package a\n", SNAPSHOT)
    assert [n.kind for n in result.nodes] == [NodeKind.MODULE]
    assert result.errors == ("extraction failed: RuntimeError('bad capture')",)


@pytest.mark.parametrize("language", sorted(GRAMMARS))
def test_every_grammar_loads_and_parses(language: str) -> None:
    adapter = TagsAdapter(GRAMMARS[language], (".x",))
    assert isinstance(adapter, LanguageAdapter)
    assert adapter.language == language
    result = adapter.parse("f.x", b"\n", SNAPSHOT)
    assert result.nodes[0].kind is NodeKind.MODULE


def test_unsupported_predicates_are_disabled() -> None:
    """Ruby's bare-identifier call pattern needs `#is-not? local`; without it, no fake calls."""
    source = b"def f\n  x = 1\n  g(x)\nend\n"
    result = TagsAdapter(GRAMMARS["ruby"]).parse("a.rb", source, SNAPSHOT)
    assert [c.name for c in result.calls] == ["g"]


def test_text_adapter() -> None:
    adapter = TextAdapter("markdown", (".md",))
    assert isinstance(adapter, LanguageAdapter)
    result = adapter.parse("docs/a.md", b"# a\n\nb\n", SNAPSHOT)
    assert result.tier is Tier.TEXT
    assert [n.kind for n in result.nodes] == [NodeKind.MODULE]
    assert result.nodes[0].span.end_line == 3
    assert result.errors == ()


def test_text_adapter_records_reason() -> None:
    result = TextAdapter("go", reason="grammar missing").parse("a.go", b"", SNAPSHOT)
    assert result.errors == ("grammar missing",)
    assert result.nodes[0].span.end_line == 1


def test_data_files_exist() -> None:
    assert sorted(p.name for p in (DATA / "generic").iterdir()) == [
        "UserService.java",
        "server.go",
        "shapes.rs",
    ]
