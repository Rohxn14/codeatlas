"""Typed receivers (T20, D-22): each type source, with exact edges, and the negatives."""

import shutil

import pytest
from ts_resolver_edges import SAMPLES, Edges

from codeatlas.indexer.languages.typescript.adapter import TypeScriptAdapter
from codeatlas.indexer.languages.typescript.resolver.types import (
    jsdoc_params,
    jsdoc_templates,
    parse_signature,
    type_name,
)
from codeatlas.indexer.pipeline import build_graph
from codeatlas.store import GraphStore

S = "src/service.ts::Service."
L = "src/legacy.js::"
TYPED = ("self_method", 0.9)


@pytest.fixture(scope="module")
def typed(tmp_path_factory: pytest.TempPathFactory) -> Edges:
    root = tmp_path_factory.mktemp("typed") / "typed"
    shutil.copytree(SAMPLES / "typed", root)
    store = GraphStore(":memory:")
    built = build_graph(str(root), store)
    try:
        return Edges(store.export_json(built.snapshot_id))
    finally:
        store.close()


def calls(edges: Edges, src: str) -> dict[str, tuple]:
    return {k: v[:2] for k, v in edges.out("calls", src).items()}


# --- reading signatures and JSDoc ----------------------------------------------------


def test_parameters_with_modifiers_defaults_and_destructuring() -> None:
    sig = parse_signature(
        "constructor(private readonly repo?: Repo<User> = x, { a }: Opts, ...rest: T[], "
        "cb: (x: number) => void = () => {}, plain)"
    )
    assert {k: (p.type_text, p.is_property) for k, p in sig.params.items()} == {
        "repo": ("Repo<User>", True),
        "rest": ("T[]", False),
        "cb": ("(x: number) => void", False),
        "plain": (None, False),
    }


def test_type_parameters_of_functions_and_arrows() -> None:
    assert parse_signature("async go<T, K extends keyof T = never>(t: T)").type_params == {
        "T", "K"
    }
    assert parse_signature("const f = <T,>(t: T): T =>").type_params == {"T"}
    assert parse_signature("const f = x =>").params == {}


def test_jsdoc_params_and_templates() -> None:
    doc = (
        "Saves.\n@template T, U\n@param {UserRepo} repo the repo\n@param {Cache=} [c=x]\n"
        "@returns {X}"
    )
    assert jsdoc_params(doc) == {"repo": "UserRepo", "c": "Cache="}
    assert jsdoc_templates(doc) == {"T", "U"}


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("UserRepo", "UserRepo"),
        ("ns.UserRepo", "ns.UserRepo"),
        ("Repo<User, Map<K, V>>", "Repo"),
        ("Repo | null", "Repo"),
        ("undefined | (Repo)", "Repo"),
        ("?Repo", "Repo"),
        ("Repo=", "Repo"),
        ("Repo | Other", None),
        ("Repo & Other", None),
        ("Repo[]", None),
        ("Promise<Repo>", None),
        ("any", None),
        ("unknown", None),
        ("string", None),
        ("typeof Repo", None),
        ("{ save(): void }", None),
        ("(x: Repo) => void", None),
        ("'literal'", None),
        ("T", None),
        ("", None),
    ],
)
def test_type_name(text: str, name: str | None) -> None:
    assert type_name(text, frozenset({"T"})) == name


# --- source 1: annotations in the signature ------------------------------------------


def test_annotated_parameter(typed: Edges) -> None:
    assert calls(typed, S + "viaParam") == {"src/repo.ts::UserRepo.save": TYPED}


def test_annotated_arrow_function(typed: Edges) -> None:
    assert calls(typed, "src/service.ts::typedArrow") == {"src/repo.ts::UserRepo.get": TYPED}


# --- source 2: parameter properties and class fields ---------------------------------


def test_constructor_parameter_property_through_an_import_alias(typed: Edges) -> None:
    assert calls(typed, S + "viaProperty") == {"src/repo.ts::UserRepo.save": TYPED}


def test_field_annotation_finds_the_method_on_a_base(typed: Edges) -> None:
    assert calls(typed, S + "viaBase") == {"src/repo.ts::BaseRepo.find": TYPED}


def test_field_initialised_with_new(typed: Edges) -> None:
    assert calls(typed, S + "viaNew") == {"src/repo.ts::Other.save": TYPED}


def test_optional_field_and_a_builtin_method_name(typed: Edges) -> None:
    # `get` is on the built-in stop-list, but the declared class has it.
    assert calls(typed, S + "viaOptional") == {"src/repo.ts::UserRepo.get": TYPED}


def test_namespace_qualified_type(typed: Edges) -> None:
    assert calls(typed, S + "viaNamespace") == {"src/repo.ts::UserRepo.save": TYPED}


def test_field_chain(typed: Edges) -> None:
    assert calls(typed, S + "viaChain") == {"src/repo.ts::UserRepo.save": TYPED}


# --- source 3: JSDoc, for JavaScript -------------------------------------------------


def test_jsdoc_constructor_param_and_the_same_name_convention(typed: Edges) -> None:
    assert calls(typed, L + "Legacy.byConvention") == {L + "Cache.get": TYPED}


def test_jsdoc_type_on_a_constructor_assignment(typed: Edges) -> None:
    assert calls(typed, L + "Legacy.byJsdocType") == {L + "Cache.put": TYPED}


def test_new_in_the_constructor(typed: Edges) -> None:
    assert calls(typed, L + "Legacy.byNew") == {L + "Cache.get": TYPED}


def test_jsdoc_optional_nullable_param(typed: Edges) -> None:
    assert calls(typed, L + "use") == {L + "Cache.put": TYPED}


# --- negatives: untyped receivers behave exactly as before ---------------------------

SCOPED_SAVE = {
    "src/repo.ts::UserRepo.save": ("import_scoped", 0.5),
    "src/repo.ts::Other.save": ("import_scoped", 0.5),
}


@pytest.mark.parametrize(
    "method",
    ["onArray", "onAny", "onUnion", "onInterface", "onTypeParam", "onClassTypeParam"],
)
def test_untyped_receivers_stay_import_scoped(typed: Edges, method: str) -> None:
    assert calls(typed, S + method) == SCOPED_SAVE


def test_untyped_inner_parameter_shadows_a_typed_outer_one(typed: Edges) -> None:
    assert calls(typed, S + "onShadow.inner") == SCOPED_SAVE


def test_jsdoc_template_and_object_stay_untyped(typed: Edges) -> None:
    scoped = {L + "Cache.put": ("import_scoped", 1.0)}
    assert calls(typed, L + "useGeneric") == scoped
    assert calls(typed, L + "useObject") == scoped


def test_class_with_a_library_base_and_no_such_method_gets_no_edge(typed: Edges) -> None:
    assert calls(typed, S + "onOutsideBase") == {}


def test_fields_are_recorded_on_the_class() -> None:
    source = (SAMPLES / "typed" / "src" / "service.ts").read_bytes()
    result = TypeScriptAdapter().parse("src/service.ts", source, "s")
    service = next(n for n in result.nodes if n.qualname == "Service")
    assert service.attrs["fields"] == {
        "extra": "Repo", "built": "Other", "maybe": "Repo | null", "model": "M", "wrap": "Wrapper"
    }
