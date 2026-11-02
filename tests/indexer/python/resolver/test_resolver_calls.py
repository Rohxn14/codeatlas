"""CALLS edges: one test per row of the brief's table, plus every raw case."""

from resolver_support import load_tree, of_kind, run_resolver


def calls(rows, source=None):
    return [r[1:] for r in of_kind(rows, "calls") if source is None or r[1] == source]


def test_direct_calls_in_every_form() -> None:
    rows = run_resolver(load_tree("shop"))
    app = "shop/app.py::"
    assert calls(rows, app + "via_name") == [
        (app + "via_name", "shop/core.py::make_order", "direct", 1.0, 14)]
    assert calls(rows, app + "via_module_attribute")[0][1:] == (
        "shop/core.py::make_order", "direct", 1.0, 18)
    assert calls(rows, app + "via_alias")[0][1:] == (
        "shop/util/money.py::fmt", "direct", 1.0, 22)
    assert calls(rows, app + "via_dotted_import")[0][1:] == (
        "shop/util/money.py::fmt", "direct", 1.0, 26)
    assert calls(rows, app + "via_submodule_import")[0][1:] == (
        "shop/util/money.py::fmt", "direct", 1.0, 30)


def test_constructor_goes_to_the_init_that_runs() -> None:
    rows = run_resolver(load_tree("shop"))
    assert calls(rows, "shop/app.py::constructor") == [
        ("shop/app.py::constructor", "shop/core.py::Order.__init__", "direct", 1.0, 34)]


def test_outside_calls_go_to_external_keys() -> None:
    rows = run_resolver(load_tree("shop"))
    app = "shop/app.py::"
    expect = {
        "stdlib_alias": ("::external:os.path.join", 38),
        "stdlib": ("::external:os.getcwd", 42),
        "third_party": ("::external:requests.get", 46),
        "builtin": ("::external:builtins.len", 50),
        "variable": ("::external:builtins.print", 54),
    }
    for name, (target, line) in expect.items():
        assert calls(rows, app + name) == [(app + name, target, "direct", 1.0, line)]


def test_inherited_init_and_no_edge_for_a_class_without_one() -> None:
    files = {
        "m.py": (
            "class Base:\n    def __init__(self): pass\n\n"
            "class Child(Base):\n    pass\n\n"
            "class Plain:\n    pass\n\n"
            "def make():\n    Child()\n    Plain()\n"
        ),
    }
    rows = run_resolver(files)
    assert calls(rows, "m.py::make") == [("m.py::make", "m.py::Base.__init__", "direct", 1.0, 11)]


def test_self_cls_and_super_use_the_bases() -> None:
    files = {
        "a.py": (
            "class Base:\n"
            "    def run(self): pass\n"
            "    def make(cls): pass\n"
            "    def other(self): pass\n"
            "\n"
            "class Child(Base):\n"
            "    def run(self):\n"
            "        super().run()\n"
            "        self.other()\n"
            "        self.run2()\n"
            "    @classmethod\n"
            "    def build(cls):\n"
            "        cls.make()\n"
        ),
    }
    rows = run_resolver(files)
    assert calls(rows, "a.py::Child.run") == [
        ("a.py::Child.run", "::external:builtins.super", "direct", 1.0, 8),
        ("a.py::Child.run", "a.py::Base.other", "self_method", 0.9, 9),
        ("a.py::Child.run", "a.py::Base.run", "self_method", 0.9, 8),
        # self.run2() exists nowhere: it stays raw and is not guessed
    ]
    assert calls(rows, "a.py::Child.build") == [
        ("a.py::Child.build", "::external:builtins.classmethod", "direct", 1.0, 11),  # D-11
        ("a.py::Child.build", "a.py::Base.make", "self_method", 0.9, 13),
    ]


def test_a_base_in_another_file_and_an_unresolvable_base() -> None:
    files = {
        "base.py": "class Base:\n    def hello(self): pass\n",
        "kid.py": (
            "from base import Base\nfrom lib import Mixin\n\n"
            "class Kid(Base):\n    def go(self):\n        self.hello()\n\n"
            "class Mixed(Mixin):\n    def go(self):\n        self.hello()\n"
        ),
    }
    rows = run_resolver(files)
    assert calls(rows, "kid.py::Kid.go") == [
        ("kid.py::Kid.go", "base.py::Base.hello", "self_method", 0.9, 6)]
    assert calls(rows, "kid.py::Mixed.go") == []  # may live in the library's Mixin


def test_typed_receivers_use_self_method_confidence() -> None:
    files = {
        "repo.py": "class Repo:\n    def save(self): pass\n",
        "svc.py": (
            "from repo import Repo\n\n"
            "def make() -> Repo:\n    return Repo()\n\n"
            "class Svc:\n"
            "    def __init__(self, repo: Repo, other=None):\n        self.repo = repo\n"
            "    def a(self):\n        self.repo.save()\n"
            "    def b(self, r: 'Repo | None'):\n        r.save()\n"
            "    def c(self):\n        make().save()\n        Repo().save()\n"
        ),
    }
    rows = run_resolver(files)
    for method, line in (("a", 10), ("b", 12)):
        assert calls(rows, f"svc.py::Svc.{method}") == [
            (f"svc.py::Svc.{method}", "repo.py::Repo.save", "self_method", 0.9, line)]
    assert calls(rows, "svc.py::Svc.c")[0] == (
        "svc.py::Svc.c", "repo.py::Repo.save", "self_method", 0.9, 14)


def test_import_scoped_when_the_receiver_type_is_unknown() -> None:
    files = {
        "models.py": "class User:\n    def rename(self): pass\n",
        "other.py": "class Thing:\n    def rename(self): pass\n",
        "use.py": "from models import User\n\ndef f(x):\n    x.rename()\n",
    }
    rows = run_resolver(files)
    # `other.py` also defines `rename`, but `use.py` never imports it.
    assert calls(rows, "use.py::f") == [
        ("use.py::f", "models.py::User.rename", "import_scoped", 1.0, 4)]


def test_import_scoped_splits_confidence() -> None:
    files = {
        "a.py": "class A:\n    def go(self): pass\n",
        "b.py": "class B:\n    def go(self): pass\n",
        "use.py": "import a\nimport b\n\ndef f(x):\n    x.go()\n",
    }
    rows = run_resolver(files)
    assert calls(rows, "use.py::f") == [
        ("use.py::f", "a.py::A.go", "import_scoped", 0.5, 5),
        ("use.py::f", "b.py::B.go", "import_scoped", 0.5, 5),
    ]


def test_name_guess_with_three_candidates_is_capped_at_a_third_or_less() -> None:
    rows = run_resolver(load_tree("guess"))
    saves = calls(rows, "guess/caller.py::persist")
    assert len(saves) == 3
    assert {r[2] for r in saves} == {"name_guess"}
    assert {r[3] for r in saves} == {0.3}  # 1/3 = 0.333, capped at 0.3
    assert {r[1] for r in saves} == {
        "guess/one.py::A.save", "guess/two.py::B.save", "guess/three.py::C.save"}
    # One candidate: 1/1 would be 1.0, but a guess never exceeds 0.3.
    assert calls(rows, "guess/caller.py::paint") == [
        ("guess/caller.py::paint", "guess/one.py::A.render", "name_guess", 0.3, 6)]


def test_too_many_candidates_or_a_container_method_name_is_not_guessed() -> None:
    many = {f"m{i}.py": f"class C{i}:\n    def ship(self): pass\n" for i in range(6)}
    many["use.py"] = "def f(x):\n    x.ship()\n    x.get()\n"
    many["d.py"] = "class D:\n    def get(self): pass\n"
    assert calls(run_resolver(many), "use.py::f") == []


def test_the_caller_is_not_its_own_candidate() -> None:
    files = {"r.py": "class Repo:\n    def get(self, k):\n        return self.items.get(k)\n"}
    assert calls(run_resolver(files)) == []


def test_calls_that_must_stay_raw() -> None:
    files = {
        "h.py": (
            "HANDLERS = {}\n\n"
            "def handle(): pass\n\n"
            "def dispatch(name, callback):\n"
            "    HANDLERS[name]()\n"
            "    callback()\n"
            "    getattr(HANDLERS, name)()\n\n"
            "def logged(func):\n"
            "    def wrapper(*args):\n"
            "        return func(*args)\n"
            "    return wrapper\n\n"
            "handle()\n"
        ),
    }
    rows = run_resolver(files)
    assert calls(rows, "h.py::dispatch") == [
        ("h.py::dispatch", "::external:builtins.getattr", "direct", 1.0, 8)]
    assert calls(rows, "h.py::logged.wrapper") == []  # func is a parameter of logged
    assert all(r[1] != "h.py::" for r in calls(rows))  # module-level call: no edge


def test_nested_function_and_decorator() -> None:
    files = {
        "d.py": (
            "def logged(f):\n    return f\n\n"
            "class S:\n"
            "    @logged\n"
            "    def make(self):\n        def inner(): pass\n        inner()\n"
        ),
    }
    rows = run_resolver(files)
    assert calls(rows, "d.py::S.make") == [
        ("d.py::S.make", "d.py::S.make.inner", "direct", 1.0, 8),
        ("d.py::S.make", "d.py::logged", "direct", 1.0, 5),
    ]


def test_one_edge_per_pair_at_the_first_line() -> None:
    files = {"x.py": "def a(): pass\n\ndef b():\n    a()\n    a()\n"}
    assert calls(run_resolver(files), "x.py::b") == [("x.py::b", "x.py::a", "direct", 1.0, 4)]


def test_overloads_and_redefinitions_are_one_definition() -> None:
    files = {
        "o.py": (
            "from typing import overload\n\n"
            "class G:\n"
            "    @overload\n    def command(self, a: int) -> int: ...\n"
            "    @overload\n    def command(self, a: str) -> str: ...\n"
            "    def command(self, a): pass\n\n"
            "def helper(): pass\n"
            "if True:\n    def helper(): pass\n\n"
            "def use(x):\n    helper()\n    x.command(1)\n"
        ),
    }
    rows = [r for r in calls(run_resolver(files), "o.py::use") if "external" not in r[1]]
    assert len(rows) == 2
    assert {(r[2], r[3]) for r in rows} == {("direct", 1.0), ("import_scoped", 1.0)}
