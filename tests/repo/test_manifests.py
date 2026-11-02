from pathlib import Path

import pytest
from conftest import DATA

from codeatlas.indexer.discover import language_for
from codeatlas.models import Edge, EdgeKind, FileRecord, Node, NodeKind, Resolution, Tier
from codeatlas.repo import ManifestAnalyzer, manifests
from codeatlas.repo.ecosystems import rust
from codeatlas.repo.paths import glob_matches, join

SAMPLES = DATA / "repo"
PARSED = {"python", "javascript", "typescript", "go", "java", "rust", "c_sharp", "php", "c"}


def records(root: Path) -> list[FileRecord]:
    """FileRecords for a folder, with the tier discovery would give (data files are text)."""
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            language = language_for(path.name)
            tier = Tier.STRUCTURAL if language in PARSED else Tier.TEXT
            rel = path.relative_to(root).as_posix()
            found.append(FileRecord(rel, language, tier, "", path.stat().st_size))
    return found


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def analyze(root: Path, repo: str = "sample") -> tuple[list[Node], list[Edge]]:
    return ManifestAnalyzer().analyze(root, records(root), f"{repo}@0123456789ab")


def by_name(nodes: list[Node]) -> dict[str, Node]:
    return {n.name: n for n in nodes}


def dependencies(nodes: list[Node], edges: list[Edge]) -> set[tuple[str, str, float]]:
    names = {n.id: n.name for n in nodes}
    return {
        (names[e.src_id], names[e.dst_id], e.confidence)
        for e in edges
        if e.kind is EdgeKind.DEPENDS_ON
    }


def owners(nodes: list[Node], edges: list[Edge]) -> dict[str, str]:
    """File path -> name of the package that CONTAINS it."""
    names = {n.id: n.name for n in nodes}
    found = {}
    for edge in edges:
        if edge.kind is EdgeKind.CONTAINS:
            path = edge.dst_id.partition("/")[2].removesuffix("::")
            assert path not in found, f"{path} contained twice"
            found[path] = names[edge.src_id]
    return found


# Per sample: packages (name -> ecosystem), internal dependencies, one file and its owner.
EXPECTED = {
    "npm": (
        {"@shop/api": "npm", "@shop/core": "npm", "npm": "none"},
        {("@shop/api", "@shop/core", 1.0)},
        ("packages/api/src/index.js", "@shop/api"),
    ),
    "pnpm": (
        {"pnpm-root": "npm", "web": "npm", "ui": "npm", "legacy": "npm"},
        {("web", "ui", 1.0), ("web", "legacy", 1.0)},
        ("libs/ui/index.ts", "ui"),
    ),
    "python": (
        {"acme": "pypi", "acme-core": "pypi", "acme-legacy": "pypi", "acme-tools": "pypi"},
        {("acme", "acme-core", 1.0), ("acme-legacy", "acme-core", 1.0)},
        ("libs/core/acme_core/__init__.py", "acme-core"),
    ),
    "go": (
        {"example.com/shop/api": "go", "example.com/shop/lib": "go", "go": "none"},
        {("example.com/shop/api", "example.com/shop/lib", 1.0)},
        ("api/handlers/handlers.go", "example.com/shop/api"),
    ),
    "rust": (
        {"app": "cargo", "core-lib": "cargo", "rust": "none"},
        {("app", "core-lib", 1.0)},
        ("crates/core_lib/tests/integration.rs", "core-lib"),
    ),
    "maven": (
        {"com.acme:parent": "maven", "com.acme:core": "maven", "com.acme:web": "maven"},
        {("com.acme:web", "com.acme:core", 1.0)},
        ("core/src/main/java/com/acme/core/Money.java", "com.acme:core"),
    ),
    "gradle": (
        {"shop": "gradle", ":app": "gradle", ":lib:util": "gradle", ":lib:http-client": "gradle"},
        {(":app", ":lib:util", 1.0), (":app", ":lib:http-client", 1.0)},  # path and accessor
        ("lib/util/src/main/java/Util.java", ":lib:util"),
    ),
    "dotnet": (
        {"Shop.Api": "nuget", "Shop.Core": "nuget", "Shop.Core.Tests": "nuget", "dotnet": "none"},
        {("Shop.Api", "Shop.Core", 1.0), ("Shop.Core.Tests", "Shop.Core", 1.0)},
        ("tests/Shop.Core.Tests/MoneyTests.cs", "Shop.Core.Tests"),
    ),
    "php": (
        {"acme/app": "composer", "Acme/Util": "composer"},
        {("acme/app", "Acme/Util", 1.0)},
        ("packages/util/src/Str.php", "Acme/Util"),
    ),
}


@pytest.mark.parametrize("sample", sorted(EXPECTED))
def test_packages_dependencies_and_containment(sample: str) -> None:
    packages, deps, (path, owner) = EXPECTED[sample]
    nodes, edges = analyze(SAMPLES / sample, sample)
    assert {n.name: n.attrs["ecosystem"] for n in nodes} == packages
    assert all(n.kind is NodeKind.PACKAGE for n in nodes)
    assert dependencies(nodes, edges) == deps
    contained = owners(nodes, edges)
    assert contained[path] == owner
    # Every file belongs to exactly one package.
    assert set(contained) == {r.path for r in records(SAMPLES / sample)}
    for edge in edges:
        assert edge.resolution is Resolution.STRUCTURAL
    for node in nodes:
        assert "warnings" not in node.attrs, node.attrs["warnings"]


def test_package_key_id_and_attrs() -> None:
    nodes, _ = analyze(SAMPLES / "npm", "shop")
    api = by_name(nodes)["@shop/api"]
    assert api.key == "packages/api/package.json::package:@shop/api"
    assert api.id == "shop@0123456789ab/packages/api/package.json::package:@shop/api"
    assert api.qualname == "package:@shop/api"
    assert api.path == "packages/api/package.json"
    assert api.language == "javascript"
    assert api.attrs == {
        "ecosystem": "npm",
        "manifest": "packages/api/package.json",
        "root": "packages/api",
        "entry_points": ["packages/api/src/index.js"],
        "role": "package",
        "version": "1.2.0",
        "workspace": "package.json",
    }


def test_contains_edges_point_at_module_ids() -> None:
    nodes, edges = analyze(SAMPLES / "rust", "r")
    crate = by_name(nodes)["core-lib"]
    assert Edge(
        crate.id, "r@0123456789ab/crates/core_lib/src/lib.rs::", EdgeKind.CONTAINS, 1.0,
        Resolution.STRUCTURAL,
    ) in edges


def test_no_manifest_gives_one_implicit_package() -> None:
    nodes, edges = analyze(SAMPLES / "none", "plain")
    assert len(nodes) == 1
    package = nodes[0]
    assert (package.name, package.key, package.language) == ("plain", "::package:plain", "c")
    assert package.attrs["implicit"] is True
    assert package.attrs["ecosystem"] == "none"
    assert set(owners(nodes, edges)) == {"README.md", "main.c", "lib/util.c"}


def test_empty_repository_still_has_its_package(tmp_path: Path) -> None:
    nodes, edges = ManifestAnalyzer().analyze(tmp_path, [], "empty@0123456789ab")
    assert [n.name for n in nodes] == ["empty"] and edges == []


def test_workspace_membership_and_excludes() -> None:
    nodes, _ = analyze(SAMPLES / "pnpm")
    packages = by_name(nodes)
    assert packages["web"].attrs["workspace"] == "pnpm-workspace.yaml"
    assert packages["ui"].attrs["workspace"] == "pnpm-workspace.yaml"
    assert "workspace" not in packages["legacy"].attrs  # `!libs/legacy`
    python = by_name(analyze(SAMPLES / "python")[0])
    assert python["acme"].attrs["workspace_members"] == ["libs/*"]
    assert python["acme-core"].attrs["workspace"] == "pyproject.toml"
    assert "workspace" not in python["acme-tools"].attrs


def test_ecosystem_specific_attrs() -> None:
    go = by_name(analyze(SAMPLES / "go")[0])["example.com/shop/api"]
    assert go.attrs["module_path"] == "example.com/shop/api"
    assert go.attrs["entry_points"] == ["api", "api/cmd/tool"]
    assert go.attrs["workspace"] == "go.work"
    php = by_name(analyze(SAMPLES / "php")[0])
    assert php["acme/app"].attrs["autoload_psr4"] == {"App\\": ["src"], "App\\Tests\\": ["tests"]}
    assert php["acme/app"].attrs["entry_points"] == ["bin/console"]
    assert php["Acme/Util"].attrs["autoload_psr4"] == {
        "Acme\\Util\\": ["packages/util/src", "packages/util/lib"]
    }
    python = by_name(analyze(SAMPLES / "python")[0])
    assert python["acme"].attrs["entry_points"] == ["acme = acme.cli:main"]
    assert python["acme-legacy"].attrs["version"] == "0.1"
    rust_nodes = by_name(analyze(SAMPLES / "rust")[0])
    assert rust_nodes["app"].attrs["entry_points"] == ["crates/app/src/main.rs"]
    assert "library" not in rust_nodes["app"].attrs
    assert rust_nodes["core-lib"].attrs["library"] == "crates/core_lib/src/lib.rs"
    maven = by_name(analyze(SAMPLES / "maven")[0])["com.acme:core"]
    assert (maven.attrs["version"], maven.attrs["group_id"]) == ("1.0.0", "com.acme")
    gradle = by_name(analyze(SAMPLES / "gradle")[0])
    assert gradle[":app"].attrs["entry_points"] == ["shop.AppKt"]
    assert gradle[":lib:util"].attrs["version"] == "2.0.0"
    assert gradle["shop"].attrs["gradle_path"] == ":"
    dotnet = by_name(analyze(SAMPLES / "dotnet")[0])
    assert dotnet["Shop.Api"].attrs["entry_points"] == ["src/Shop.Api/Shop.Api.csproj"]
    assert dotnet["Shop.Api"].attrs["workspace"] == "Shop.sln"
    assert "workspace" not in dotnet["Shop.Core.Tests"].attrs


def test_malformed_manifests_become_warnings_not_exceptions() -> None:
    nodes, edges = analyze(SAMPLES / "broken", "broken")
    packages = by_name(nodes)
    assert set(packages) == {"broken", "rusty", "jvm", "py"}
    root_warnings = packages["broken"].attrs["warnings"]
    assert any(w.startswith("package.json: cannot parse") for w in root_warnings)
    # pnpm-workspace.yaml is not a package; its warning lands on the package holding it.
    assert any(w.startswith("pnpm-workspace.yaml: cannot parse") for w in root_warnings)
    assert packages["rusty"].attrs["warnings"][0].startswith("rusty/Cargo.toml: cannot parse")
    assert packages["jvm"].attrs["warnings"][0].startswith("jvm/pom.xml: cannot parse")
    assert packages["py"].attrs["warnings"][0].startswith("py/pyproject.toml: cannot parse")
    assert owners(nodes, edges)["py/mod.py"] == "py"


def test_a_parser_bug_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(view: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(rust, "find", explode)
    nodes, _ = analyze(SAMPLES / "rust", "r")
    assert {n.name for n in nodes} == {"r"}  # crates lost, but said so
    assert nodes[0].attrs["warnings"] == ["rust manifests: analysis failed: boom"]


def test_same_root_files_go_to_the_ecosystem_of_their_language(tmp_path: Path) -> None:
    write_tree(tmp_path, {
        "package.json": '{"name": "web"}',
        "pyproject.toml": '[project]\nname = "api"\n',
        "app.py": "",
        "app.js": "",
        "README.md": "",
    })
    contained = owners(*analyze(tmp_path))
    assert contained["app.py"] == "api"
    assert contained["app.js"] == "web"
    assert contained["README.md"] == "web"  # no match: first ecosystem in order


def test_deepest_package_root_wins_and_uncovered_files_get_the_implicit_package(
    tmp_path: Path,
) -> None:
    write_tree(tmp_path, {
        "web/package.json": '{"name": "web"}',
        "web/plugins/x/package.json": '{"name": "x"}',
        "web/plugins/x/index.js": "",
        "web/index.js": "",
        "scripts/deploy.sh": "",
    })
    contained = owners(*analyze(tmp_path, "mono"))
    assert contained["web/plugins/x/index.js"] == "x"
    assert contained["web/index.js"] == "web"
    assert contained["scripts/deploy.sh"] == "mono"


def test_a_shared_name_splits_dependency_confidence(tmp_path: Path) -> None:
    write_tree(tmp_path, {
        "examples/a/package.json": '{"name": "demo"}',
        "examples/b/package.json": '{"name": "demo"}',
        "app/package.json": '{"name": "app", "dependencies": {"demo": "*"}}',
    })
    nodes, edges = analyze(tmp_path)
    depends = [e for e in edges if e.kind is EdgeKind.DEPENDS_ON]
    assert len(depends) == 2
    assert {e.confidence for e in depends} == {0.5}
    assert all(e.attrs == {"via": "name", "candidates": 2} for e in depends)


def test_unnamed_package_json_is_named_after_its_folder(tmp_path: Path) -> None:
    write_tree(tmp_path, {"site/package.json": '{"dependencies": {"react": "^18"}}'})
    package = by_name(analyze(tmp_path)[0])["site"]
    assert package.attrs["warnings"] == ["site/package.json: no name; named after its folder"]


def test_setup_py_is_read_not_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    write_tree(tmp_path, {
        "setup.py": f"open({str(marker)!r}, 'w').write('x')\nsetup(name='safe')\n",
        "dynamic/setup.py": "setup(name=compute_name())\n",
    })
    packages = by_name(analyze(tmp_path)[0])
    assert "safe" in packages
    assert not marker.exists()
    assert packages["dynamic"].attrs["warnings"] == [
        "dynamic: no literal package name; named after its folder"
    ]


def test_tool_only_python_config_is_not_a_package(tmp_path: Path) -> None:
    write_tree(tmp_path, {"pyproject.toml": "[tool.ruff]\nline-length = 100\n", "a.py": ""})
    nodes, _ = analyze(tmp_path, "tools")
    assert [(n.name, n.attrs["ecosystem"]) for n in nodes] == [("tools", "none")]


def test_find_packages_owner_map() -> None:
    root = SAMPLES / "go"
    layout = manifests.find_packages(root, records(root), "go")
    assert layout.owner["lib/lib_test.go"].name == "example.com/shop/lib"


@pytest.mark.parametrize(
    ("base", "relative", "expected"),
    [
        ("", "./lib", "lib"),
        ("src/App", "..\\Core\\Core.csproj", "src/Core/Core.csproj"),
        ("a/b", "../../c/", "c"),
        ("a", "../../escape", None),
        ("a", ".", "a"),
    ],
)
def test_join(base: str, relative: str, expected: str | None) -> None:
    assert join(base, relative) == expected


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("packages/*", "packages/api", True),
        ("packages/*", "packages/api/nested", False),
        ("packages/**", "packages/api/nested", True),
        ("./crates/*", "crates/x", True),
        ("apps/web", "apps/web", True),
        ("**/pkg", "a/b/pkg", True),
        ("**/pkg", "pkg", True),
        ("lib?", "lib1", True),
    ],
)
def test_glob_matches(pattern: str, path: str, matches: bool) -> None:
    assert glob_matches(pattern, path) is matches


def test_one_bad_manifest_costs_only_itself(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {
        "good/composer.json": '{"name": "acme/good", "autoload": {"psr-4": {"Good\\\\": "src/"}}}',
        "good/src/A.php": "<?php\n",
        "bad/composer.json": '{"name": "acme/bad", "autoload": {"psr-4": {"App\\\\": 5}}}',
        "bad/src/B.php": "<?php\n",
    })
    nodes, edges = analyze(root)
    packages = by_name([n for n in nodes if n.kind is NodeKind.PACKAGE])
    assert {"acme/good", "acme/bad"} <= set(packages)
    assert owners(nodes, edges)["bad/src/B.php"] == "acme/bad"
    assert packages["acme/bad"].attrs["autoload_psr4"] == {}  # the bad value is skipped


def test_a_parser_bug_still_yields_the_manifests_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codeatlas.repo.ecosystems import php

    def broken(view, manifest, found):
        found.packages.append(None)  # half-done work is discarded
        raise RuntimeError("parser bug")

    monkeypatch.setattr(php, "_composer", broken)
    root = write_tree(tmp_path, {"lib/composer.json": "{}", "lib/x.php": "<?php\n"})
    nodes, _ = analyze(root)
    (lib,) = [n for n in nodes if n.kind is NodeKind.PACKAGE and n.name == "lib"]
    assert any("parser bug" in w for w in lib.attrs["warnings"])


def test_path_dependency_wins_over_the_same_name(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {
        "app/package.json": '{"name": "app", "dependencies": {"lib": "file:../lib"}}',
        "lib/package.json": '{"name": "lib"}',
    })
    _, edges = analyze(root)
    (depends,) = [e for e in edges if e.kind is EdgeKind.DEPENDS_ON]
    assert depends.attrs == {"via": "path"}


def test_package_roles(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {
        "composer.json": '{"name": "acme/app", "require": {"monolog/monolog": "^3"}}',
        "vendor/monolog/monolog/composer.json": '{"name": "monolog/monolog"}',
        "tests/data/demo/package.json": '{"name": "demo"}',
        "src/A.php": "<?php\n",
    })
    nodes, edges = analyze(root)
    roles = {n.name: n.attrs["role"] for n in nodes if n.kind is NodeKind.PACKAGE}
    assert roles == {"acme/app": "package", "monolog/monolog": "vendored", "demo": "fixture"}
    assert [e for e in edges if e.kind is EdgeKind.DEPENDS_ON] == []  # none into vendor/
