"""Typed receivers (T20, D-22): each type source, with exact edges, and the negatives."""

import shutil

import pytest
from ts_resolver_edges import SAMPLES, Edges

from codeatlas.indexer.languages.typescript.adapter import (
    JavaScriptAdapter,
    TypeScriptAdapter,
)
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


# --- review fixes: rebound names, default exports, interface bases, `this` ----------

R = "src/rebind.ts::"
HALF = ("import_scoped", 0.5)
BOTH_SAVE = {"src/m.ts::Repo.save": HALF, "src/m.ts::Item.save": HALF}
BOTH_LOAD = {"src/m.ts::Repo.load": HALF, "src/m.ts::Item.load": HALF}


def test_callback_parameter_hides_the_typed_parameter(typed: Edges) -> None:
    # rows.forEach((repo) => repo.save()): the inner `repo` is any row, not the Repo.
    assert calls(typed, R + "sync") == BOTH_SAVE


def test_annotated_any_callback_parameter_hides_it_too(typed: Edges) -> None:
    assert calls(typed, R + "loose") == BOTH_LOAD


def test_block_local_hides_the_typed_parameter(typed: Edges) -> None:
    assert calls(typed, R + "block") == BOTH_SAVE


def test_callback_using_the_outer_parameter_stays_typed(typed: Edges) -> None:
    assert calls(typed, R + "kept") == {"src/m.ts::Repo.load": TYPED}


def test_rebound_names_are_recorded_on_the_function() -> None:
    source = (SAMPLES / "typed" / "src" / "rebind.ts").read_bytes()
    nodes = {n.name: n for n in TypeScriptAdapter().parse("src/rebind.ts", source, "s").nodes}
    assert nodes["sync"].attrs["rebound"] == ["repo"]
    assert nodes["kept"].attrs["rebound"] == ["row"]


def test_default_import_of_a_named_default_class(typed: Edges) -> None:
    assert typed.out("imports", "src/use.ts::") == {"src/def.ts::Store": ("structural", 1.0, 1)}
    assert calls(typed, "src/use.ts::f") == {"src/def.ts::Store.put": TYPED}


def test_repository_interface_is_not_an_outside_base(typed: Edges) -> None:
    # `save` is an arrow field, not a method node: fall through instead of "no edge".
    assert calls(typed, "src/arrowy.ts::useArrowy") == BOTH_SAVE


def test_this_inside_a_function_expression_is_untyped(typed: Edges) -> None:
    assert calls(typed, L + "Legacy.inFunction") == {L + "Cache.put": ("import_scoped", 1.0)}
    assert calls(typed, L + "Legacy.inArrow") == {L + "Cache.put": TYPED}


def test_constructor_fields_stop_at_function_expressions() -> None:
    source = (SAMPLES / "typed" / "src" / "legacy.js").read_bytes()
    nodes = JavaScriptAdapter().parse("src/legacy.js", source, "s").nodes
    legacy = next(n for n in nodes if n.qualname == "Legacy")
    assert legacy.attrs["fields"] == {"other": "Cache", "made": "Cache"}  # no `late`
