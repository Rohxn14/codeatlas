"""build_graph: containment, problems on module nodes, plugins, externals, edge checks."""

from collections.abc import Callable
from pathlib import Path

import pytest

from codeatlas.indexer.pipeline import build_graph, plugins
from codeatlas.models import Edge, EdgeKind, NodeKind, Resolution, make_key, make_node_id
from codeatlas.store import GraphStore

FILES = {
    "app/service.py": (
        "def logged(f):\n"
        "    def wrapper(*a):\n"
        "        return f(*a)\n"
        "    return wrapper\n"
        "\n"
        "class Service:\n"
        "    def save(self):\n"
        "        helper()\n"
    ),
    "app/broken.py": "def ok():\n    pass\n\ndef broken(:\n",
    "web/users.test.ts": "describe('Users', () => { it('loads', () => { load(); }); });\n",
    "main.go": "package main\n\nfunc main() {}\n",
    "README.md": "# demo\n",
}


class FakeResolver:
    """Resolves every call named `helper` to an external, and one call to nowhere."""

    languages = frozenset({"python"})

    def resolve(self, results, index):
        edges = []
        for result in results:
            for call in result.calls:
                src = make_node_id(result.nodes[0].snapshot_id, call.caller_key)
                sid = result.nodes[0].snapshot_id
                if call.name == "helper":
                    edges.append(Edge(src, make_node_id(sid, "::external:lib.helper"),
                                      EdgeKind.CALLS, 1.0, Resolution.DIRECT, call.line))
                    edges.append(Edge(src, make_node_id(sid, "nowhere.py::x"),
                                      EdgeKind.CALLS, 1.0, Resolution.DIRECT, call.line))
        return edges


class RaisingResolver:
    languages = frozenset({"go"})

    def resolve(self, results, index):
        raise RuntimeError("resolver bug")


@pytest.fixture
def repo(make_repo: Callable[..., Path]) -> Path:
    return make_repo(FILES, name="demo")


def build(repo: Path, **kwargs):
    store = GraphStore(":memory:")
    return store, build_graph(str(repo), store, **kwargs)


def contains(store: GraphStore, sid: str) -> set[tuple[str, str]]:
    keys = {n.id: n.key for n in store.nodes(sid)}
    return {(keys[e.src_id], keys[e.dst_id]) for e in store.edges(sid)
            if e.kind is EdgeKind.CONTAINS}


def test_every_file_has_a_module_node_and_containment_follows_the_rules(repo: Path) -> None:
    store, built = build(repo)
    sid = built.snapshot_id
    modules = {n.path for n in store.nodes(sid) if n.kind is NodeKind.MODULE}
    assert modules == set(FILES)
    found = contains(store, sid)
    assert ("app/service.py::logged", "app/service.py::logged.wrapper") in found  # D-14
    assert ("app/service.py::Service", "app/service.py::Service.save") in found
    assert ("app/service.py::", "app/service.py::Service") in found
    assert ("web/users.test.ts::", "web/users.test.ts::Users > loads") in found


def test_parse_errors_are_recorded_on_the_module_node(repo: Path) -> None:
    store, built = build(repo)
    module = store.node(make_node_id(built.snapshot_id, make_key("app/broken.py", "")))
    assert module is not None and module.attrs["errors"]  # D-13


def test_module_nodes_know_their_package(repo: Path) -> None:
    store, built = build(repo)
    module = store.node(make_node_id(built.snapshot_id, make_key("app/service.py", "")))
    assert module is not None and "package:" in str(module.attrs["package_key"])


def test_resolver_edges_externals_and_dropped_edges(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugins, "RESOLVERS", {
        "fake": f"{__name__}:FakeResolver",
        "raising": f"{__name__}:RaisingResolver",
        "missing": "no.such.module:Resolver",
    })
    store, built = build(repo)
    sid = built.snapshot_id
    external = store.node(make_node_id(sid, "::external:lib.helper"))
    assert external is not None, built.problems
    assert external.kind is NodeKind.EXTERNAL
    assert (external.name, external.language) == ("helper", "python")
    assert built.edges_dropped["unknown target"] == 1
    assert any("resolver raising failed" in p for p in built.problems)
    assert any("resolver missing not loaded" in p for p in built.problems)
    assert "typescript" in built.languages_without_resolver
    assert built.resolved_calls == 1  # `helper` now has a CALLS edge


def test_indexing_the_same_commit_twice(repo: Path) -> None:
    store, built = build(repo)
    with pytest.raises(ValueError, match="already indexed"):
        build_graph(str(repo), store)
    again = build_graph(str(repo), store, replace_existing=True)
    assert again.nodes_written == built.nodes_written


class RootResolver:
    """Records the root it was given and reports one problem of its own."""

    languages = frozenset({"go"})
    seen_root = None

    def set_repo_root(self, root):
        RootResolver.seen_root = root

    def resolve(self, results, index):
        self.problems = ["go.mod unreadable"]
        return []


def test_resolvers_get_the_repo_root_and_their_problems_are_kept(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugins, "RESOLVERS", {"root": f"{__name__}:RootResolver"})
    _, built = build(repo)
    assert RootResolver.seen_root == repo.resolve()
    assert "resolver root: go.mod unreadable" in built.problems
