import hashlib

import pytest
from conftest import DATA

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.registry import Registry
from codeatlas.models import NodeKind, ParseResult, Tier

SNAPSHOT = "demo@0123456789ab"
GENERIC = DATA / "generic"


def parse(language: str, rel: str) -> ParseResult:
    adapter = Registry().adapter_for(language)
    return adapter.parse(rel, (GENERIC / rel).read_bytes(), SNAPSHOT)


def by_qualname(result: ParseResult) -> dict[str, object]:
    return {n.qualname: n for n in result.nodes}


def calls(result: ParseResult) -> set[tuple[str, str, str, str | None]]:
    return {(c.caller_key, c.callee_text, c.name, c.receiver) for c in result.calls}


def assert_module_first(result: ParseResult, rel: str) -> None:
    module = result.nodes[0]
    assert module.kind is NodeKind.MODULE
    assert module.key == f"{rel}::"
    assert module.id == f"{SNAPSHOT}/{rel}::"
    assert sum(1 for n in result.nodes if n.kind is NodeKind.MODULE) == 1


def test_adapter_satisfies_protocol() -> None:
    adapter = Registry().adapter_for("go")
    assert isinstance(adapter, LanguageAdapter)
    assert adapter.tier is Tier.STRUCTURAL
    assert ".go" in adapter.extensions


def test_go() -> None:
    result = parse("go", "server.go")
    assert result.tier is Tier.STRUCTURAL and result.errors == ()
    assert_module_first(result, "server.go")
    nodes = by_qualname(result)
    kinds = {q: n.kind for q, n in nodes.items() if q}
    assert kinds == {
        "Store": NodeKind.INTERFACE,
        "Server": NodeKind.CLASS,
        "NewServer": NodeKind.FUNCTION,
        "Server.Handle": NodeKind.FUNCTION,
        "main": NodeKind.FUNCTION,
    }
    handle = nodes["Server.Handle"]
    assert handle.owner_key == "server.go::Server"
    assert handle.name == "Handle"
    assert handle.signature == "func (s *Server) Handle(name string) error"
    assert handle.docstring == "Handle saves one user and logs it."
    assert (handle.span.start_line, handle.span.end_line) == (21, 24)
    assert nodes["NewServer"].owner_key is None
    assert calls(result) == {
        ("server.go::Server.Handle", "fmt.Println", "Println", "fmt"),
        ("server.go::Server.Handle", "s.store.Save", "Save", "s.store"),
        ("server.go::main", "NewServer", "NewServer", None),
        ("server.go::main", "srv.Handle", "Handle", "srv"),
    }
    assert {c.line for c in result.calls if c.name == "Println"} == {22}


def test_java() -> None:
    result = parse("java", "UserService.java")
    assert result.errors == ()
    assert_module_first(result, "UserService.java")
    nodes = by_qualname(result)
    assert nodes["UserService"].kind is NodeKind.CLASS
    assert nodes["UserService"].docstring == "Saves users through a repository."
    assert nodes["UserRepository"].kind is NodeKind.INTERFACE
    assert nodes["UserService.save"].owner_key == "UserService.java::UserService"
    assert nodes["UserService.validate"].owner_key == "UserService.java::UserService"
    assert nodes["UserService.Audit"].kind is NodeKind.CLASS
    assert nodes["UserService.Audit.record"].owner_key == "UserService.java::UserService.Audit"
    assert nodes["UserRepository.save"].owner_key == "UserService.java::UserRepository"
    assert calls(result) == {
        ("UserService.java::UserService.save", "validate", "validate", None),
        ("UserService.java::UserService.save", "this.repo.save", "save", "this.repo"),
        (
            "UserService.java::UserService.validate",
            "Objects.requireNonNull",
            "requireNonNull",
            "Objects",
        ),
        (
            "UserService.java::UserService.Audit.record",
            "System.out.println",
            "println",
            "System.out",
        ),
    }


def test_rust() -> None:
    result = parse("rust", "shapes.rs")
    assert result.errors == ()
    assert_module_first(result, "shapes.rs")
    nodes = by_qualname(result)
    assert nodes["Point"].kind is NodeKind.CLASS
    assert nodes["Point"].docstring == "A point in the plane."
    assert nodes["Shape"].kind is NodeKind.INTERFACE
    # Methods in an `impl` block belong to the implemented type.
    assert nodes["Point.new"].owner_key == "shapes.rs::Point"
    assert nodes["Point.distance"].owner_key == "shapes.rs::Point"
    assert nodes["Shape.describe"].owner_key == "shapes.rs::Shape"
    assert nodes["origin_distance"].owner_key is None
    found = calls(result)
    assert ("shapes.rs::origin_distance", "Point::new", "new", "Point") in found
    assert ("shapes.rs::origin_distance", "p.distance", "distance", "p") in found
    assert ("shapes.rs::Point.distance", "(dx*dx+dy*dy).sqrt", "sqrt", "(dx*dx+dy*dy)") in found


def test_broken_file_reports_errors_without_raising() -> None:
    result = parse("go", "broken/broken.go")
    assert result.errors
    assert all("line" in e for e in result.errors)
    assert_module_first(result, "broken/broken.go")
    assert "ok" in by_qualname(result)


@pytest.mark.parametrize(
    "source",
    [b"", b"\xff\xfe\x00garbage", b"func (", b"}}}}{{{{", "package x // é".encode()],
)
def test_never_raises_on_odd_input(source: bytes) -> None:
    result = Registry().adapter_for("go").parse("odd.go", source, SNAPSHOT)
    assert result.nodes[0].kind is NodeKind.MODULE


def short_hash(signature: str) -> str:
    return hashlib.sha1(signature.encode(), usedforsecurity=False).hexdigest()[:4]


def java_methods(source: bytes) -> dict[str, str | None]:
    result = Registry().adapter_for("java").parse("A.java", source, SNAPSHOT)
    return {n.qualname: n.signature for n in result.nodes if n.kind is NodeKind.FUNCTION}


def test_overloads_get_a_signature_hash_suffix() -> None:
    methods = java_methods(b"class A { void save(int a) {} void save(String b) {} void run() {} }")
    assert methods == {
        f"A.save#{short_hash('void save(int a)')}": "void save(int a)",
        f"A.save#{short_hash('void save(String b)')}": "void save(String b)",
        "A.run": "void run()",
    }


def test_overload_keys_do_not_depend_on_order() -> None:
    forward = java_methods(b"class A { void save(int a) {} void save(String b) {} }")
    backward = java_methods(b"class A { void save(String b) {} void save(int a) {} }")
    assert set(forward) == set(backward)


def test_identical_signatures_fall_back_to_ordinals() -> None:
    source = b"impl A { fn fmt(&self) {} }\nimpl A { fn fmt(&self) {} }\nstruct A;\n"
    result = Registry().adapter_for("rust").parse("a.rs", source, SNAPSHOT)
    digest = short_hash("fn fmt(&self)")
    keys = {n.qualname for n in result.nodes if n.kind is NodeKind.FUNCTION}
    assert keys == {f"A.fmt#{digest}", f"A.fmt#{digest}-2"}


def test_ruby_locals_are_not_calls() -> None:
    result = parse("ruby", "greeter.rb")
    assert result.errors == ()
    nodes = by_qualname(result)
    assert nodes["Greeter"].kind is NodeKind.CLASS
    assert nodes["Greeter.greet"].owner_key == "greeter.rb::Greeter"
    names = {c.name for c in result.calls}
    assert {"build", "puts", "info"} <= names
    for local in ("count", "message", "times", "name"):
        assert local not in names, f"local variable {local!r} reported as a call"
    assert ("greeter.rb::Greeter.greet", "log.info", "info", "log") in calls(result)


def test_text_adapter_emits_only_module_with_reason() -> None:
    adapter = Registry().adapter_for("markdown")
    assert adapter.tier is Tier.TEXT
    result = adapter.parse("README.md", b"# hi\nthere\n", SNAPSHOT)
    assert len(result.nodes) == 1
    module = result.nodes[0]
    assert module.kind is NodeKind.MODULE and module.span.end_line == 2
    assert "markdown" in str(module.attrs["tier_reason"])
