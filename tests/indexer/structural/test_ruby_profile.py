"""Ruby: the imports query, `require` mapping, reopened classes and the sample project."""

from __future__ import annotations

from codeatlas.indexer.structural.context import Context
from codeatlas.indexer.structural.ruby import RubyProfile
from tests.indexer.structural.helpers import parse
from tests.indexer.structural.test_structural_resolver import calls, kind_scores, resolve, scored

PROFILE = RubyProfile()


def reach(source: str, files: dict[str, str], where: str = "lib/app/main.rb") -> list:
    parsed = [parse(p, t) for p, t in {**files, where: source}.items()]
    ctx = Context.build(parsed, None)
    main = ctx.files[where]
    return [PROFILE.reach(ctx, main, imp) for imp in main.imports]


def test_imports_query_matches_require_calls_only() -> None:
    result = parse(
        "a.rb",
        'require "json"\nrequire_relative "../b"\nload "c.rb"\nlogger.require "no"\n'
        "require some_variable\nputs 'x'\n",
    )
    found = [(i.target, i.names[0][0], i.line) for i in result.imports]
    assert found == [("json", "require", 1), ("../b", "require_relative", 2), ("c.rb", "load", 3)]


def test_a_file_without_requires_has_no_imports() -> None:
    assert parse("a.rb", "class A\nend\n").imports == ()


def test_require_relative_is_relative_to_the_file() -> None:
    files = {"lib/app/util.rb": "def u; end\n", "lib/shared.rb": "def s; end\n"}
    near, up, missing = reach(
        'require_relative "util"\nrequire_relative "../shared.rb"\nrequire_relative "gone"\n', files
    )
    assert near.paths == ("lib/app/util.rb",) and near.names is None
    assert up.paths == ("lib/shared.rb",)
    assert missing.external == "gone"


def test_require_maps_to_lib_and_unknown_names_are_external() -> None:
    files = {"lib/app/util.rb": "def u; end\n", "gems/other/lib/app/util.rb": "def v; end\n"}
    mine, std = reach('require "app/util"\nrequire "json"\n', files, where="lib/app/main.rb")
    assert mine.paths == ("lib/app/util.rb",)  # the gem nearest to the requiring file
    assert (std.external, std.binding) == ("json", "JSON")


def test_load_uses_the_path_as_written() -> None:
    (found,) = reach('load "tasks/x.rb"\n', {"tasks/x.rb": "def x; end\n"})
    assert found.paths == ("tasks/x.rb",)


def test_reopened_classes_are_one_scope() -> None:
    files = {
        "a.rb": "class Foo\n  def one; end\nend\n",
        "b.rb": "class Foo\n  def two\n    one\n    puts 1\n  end\nend\n",
        "c.rb": "class Bar\n  def one; end\nend\n",
    }
    ctx = Context.build([parse(p, t) for p, t in files.items()], None)
    assert PROFILE.package_scope(ctx, ctx.files["b.rb"]) == ["a.rb"]
    edges = resolve(files, packages={})
    assert [(s, d) for s, d, _, r in calls(edges) if r.value == "import_scoped"] == [
        ("b.rb::Foo.two", "a.rb::Foo.one")
    ]


def test_class_method_call_looks_only_inside_that_class() -> None:
    files = {
        "a.rb": "class Foo\n  def self.make; end\nend\nclass Baz\n  def make; end\nend\n",
        "b.rb": 'require_relative "a"\nclass U\n  def go\n    Foo.make\n  end\nend\n',
    }
    edges = resolve(files, packages={})
    assert [d for _, d, c, _ in calls(edges) if c == 1.0 and d.endswith("make")] == [
        "a.rb::Foo.make"
    ]


def test_module_methods_are_found_by_the_module_name() -> None:
    files = {
        "a.rb": "module Util\n  def self.slug(s); s; end\nend\n"
        "module Other\n  def self.slug(s); s; end\nend\n",
        "b.rb": 'require_relative "a"\nclass U\n  def go\n    Util.slug(1)\n  end\nend\n',
    }
    got = [d for _, d, _, _ in calls(resolve(files, packages={})) if d.endswith("slug")]
    assert got == ["a.rb::Util.slug"]


def test_bare_word_is_a_call_only_when_another_statement_follows() -> None:
    result = parse("a.rb", "class A\n  def go\n    first\n    second\n    last\n  end\nend\n")
    assert [c.name for c in result.calls] == ["first", "second"]  # `last` may be a variable


def test_sample_project_scores_and_the_known_miss_is_the_last_bare_word() -> None:
    result = scored("ruby")
    assert kind_scores(result, "calls")["precision"] == 1.0
    assert kind_scores(result, "imports")["precision"] == 1.0
    assert kind_scores(result, "imports")["recall"] == 1.0
    # Two labelled calls end a method with a bare `name`, which the tags tier cannot tell
    # from a local variable, so they are missed (and nothing is invented instead).
    assert kind_scores(result, "calls")["fn"] == 2
