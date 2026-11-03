"""C#: the imports query, how `using` maps to files, and the sample project."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.csharp import CSharpProfile
from codeatlas.models import Resolution
from tests.indexer.structural.helpers import parse
from tests.indexer.structural.test_structural_resolver import calls, kind_scores, resolve, scored

PROFILE = CSharpProfile()
MODELS = "namespace Shop.Models;\npublic class User { public void Run() {} }\n"
UTIL = "namespace Shop.Util { public static class Money { public static void Show() {} } }\n"


def reach(source: str, files: dict[str, str]) -> list:
    parsed = [parse(path, text) for path, text in {**files, "app/Main.cs": source}.items()]
    ctx = Context.build(parsed, None)
    main = ctx.files["app/Main.cs"]
    return [PROFILE.reach(ctx, main, imp) for imp in main.imports]


def test_imports_query_covers_every_using_shape_and_the_namespace() -> None:
    result = parse(
        "A.cs",
        "using System;\nusing static Shop.Util.Money;\nusing J = System.Text.Json;\n"
        "namespace Shop.App { using System.IO; class A {} }\n",
    )
    found = [(i.target, i.alias, i.line) for i in result.imports]
    assert found == [
        ("System", None, 1),
        ("Shop.Util.Money", None, 2),
        ("System.Text.Json", "J", 3),
        ("System.IO", None, 4),
    ]
    assert result.nodes[0].attrs["package"] == "Shop.App"


def test_file_scoped_namespace_and_a_file_without_imports() -> None:
    assert parse("A.cs", MODELS).nodes[0].attrs["package"] == "Shop.Models"
    bare = parse("B.cs", "class B {}\n")
    assert bare.imports == () and "package" not in bare.nodes[0].attrs


def test_using_a_namespace_reaches_its_files() -> None:
    (found,) = reach("using Shop.Models;\nclass M {}\n", {"m/User.cs": MODELS})
    assert found.paths == ("m/User.cs",) and found.wildcard and found.external is None


def test_using_static_reaches_only_the_members_of_one_class() -> None:
    (found,) = reach("using static Shop.Util.Money;\nclass M {}\n", {"u/Money.cs": UTIL})
    assert found.paths == ("u/Money.cs",) and found.class_name == "Money"
    assert found.names is None  # members are usable without a qualifier


def test_alias_names_a_class_or_a_namespace() -> None:
    (cls,) = reach("using X = Shop.Models.User;\nclass M {}\n", {"m/User.cs": MODELS})
    assert (cls.binding, cls.class_name, cls.paths) == ("X", "User", ("m/User.cs",))
    (ns,) = reach("using Y = Shop.Models;\nclass M {}\n", {"m/User.cs": MODELS})
    assert (ns.binding, ns.class_name) == ("Y", None)


def test_unknown_namespaces_are_external() -> None:
    (plain, alias) = reach("using System.IO;\nusing J = System.Text.Json.JsonSerializer;\n", {})
    assert plain.external == "System.IO"
    assert (alias.external, alias.binding) == ("System.Text.Json.JsonSerializer", "J")


def test_package_scope_is_the_namespace_not_the_folder() -> None:
    files = {"a/One.cs": MODELS, "z/Two.cs": "namespace Shop.Models;\nclass Two {}\n",
             "a/Other.cs": "namespace Shop.Other;\nclass Other {}\n"}
    ctx = Context.build([parse(p, t) for p, t in files.items()], None)
    assert PROFILE.package_scope(ctx, ctx.files["a/One.cs"]) == ["z/Two.cs"]


def test_class_name_receiver_picks_that_classs_method_without_a_using() -> None:
    edges = resolve(
        {
            "a/One.cs": "namespace N;\nclass One { void Go() { Two.Run(); } void Run() {} }\n",
            "a/Two.cs": "namespace N;\nclass Two { void Run() {} }\n",
        },
        packages={},
    )
    assert [(d, c, r) for _, d, c, r in calls(edges)] == [
        ("a/Two.cs::Two.Run", 1.0, Resolution.IMPORT_SCOPED)
    ]


def untyped_receiver_edges(count: int) -> list:
    classes = "".join(f"class C{i} {{ void Run() {{}} }}\n" for i in range(count))
    return resolve(
        {
            "a/Defs.cs": "namespace N;\n" + classes,
            "b/Use.cs": "using N;\nclass U { void G(object x) { x.Run(); } }\n",
        },
        packages={},
    )


def test_untyped_receiver_resolves_up_to_five_candidates_then_gives_up() -> None:
    assert len(calls(untyped_receiver_edges(5))) == 5  # shared confidence 1/5
    assert calls(untyped_receiver_edges(6)) == []  # past the cut-off, nothing is claimed


def test_sample_project_matches_hand_labels_except_one_ambiguous_receiver() -> None:
    result = scored("csharp")
    assert kind_scores(result, "calls")["recall"] == 1.0
    assert kind_scores(result, "imports")["recall"] == 1.0
    # `user.Describe()` has an untyped receiver and both User and Product define Describe,
    # both reachable through `using Shop.Models`. The wrong half is one CALLS edge and the
    # IMPORTS edge to the file holding it.
    assert kind_scores(result, "calls")["fp"] == 1
    assert kind_scores(result, "imports")["fp"] == 1
