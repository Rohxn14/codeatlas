from pathlib import Path

import pytest
from test_manifests import SAMPLES, records, write_tree

from codeatlas.models import EdgeKind, Resolution
from codeatlas.repo import TestConventionsAnalyzer
from codeatlas.repo.test_conventions import classify

SNAPSHOT = "s@0123456789ab"


def pairs(root: Path) -> tuple[set[tuple[str, str, float]], dict[str, object]]:
    """(test path, source path, confidence) for each TESTS edge, and the analyzer report."""
    analyzer = TestConventionsAnalyzer()
    nodes, edges = analyzer.analyze(root, records(root), SNAPSHOT)
    assert nodes == []
    found = set()
    for edge in edges:
        assert (edge.kind, edge.resolution) == (EdgeKind.TESTS, Resolution.CONVENTION)
        found.add((_path(edge.src_id), _path(edge.dst_id), round(edge.confidence, 3)))
    return found, analyzer.report


def _path(node_id: str) -> str:
    return node_id.removeprefix(SNAPSHOT + "/").removesuffix("::")


def tree(tmp_path: Path, paths: list[str], extra: dict[str, str] | None = None) -> Path:
    return write_tree(tmp_path, {**dict.fromkeys(paths, ""), **(extra or {})})


@pytest.mark.parametrize(
    ("path", "language", "subject"),
    [
        ("tests/test_user.py", "python", "user"),
        ("pkg/user_test.py", "python", "user"),
        ("tests/conftest.py", "python", None),  # support file
        ("src/user.ts", "typescript", False),
        ("src/user.test.ts", "typescript", "user"),
        ("src/user.service.spec.tsx", "tsx", "user.service"),
        ("src/__tests__/user.js", "javascript", "user"),
        ("pkg/user_test.go", "go", "user"),
        ("testdata/fixture.go", "go", False),
        ("src/test/java/a/UserServiceTest.java", "java", "UserService"),
        ("src/test/java/a/UserServiceTests.java", "java", "UserService"),
        ("src/test/java/a/UserServiceIT.java", "java", "UserService"),
        ("src/main/java/a/GIT.java", "java", False),
        ("src/test/kotlin/a/Helpers.kt", "kotlin", None),
        ("Shop.Tests/MoneyTests.cs", "c_sharp", "Money"),
        ("Shop.Tests/Fixtures.cs", "c_sharp", None),
        ("spec/models/user_spec.rb", "ruby", "user"),
        ("test/user_test.rb", "ruby", "user"),
        ("tests/Unit/UserTest.php", "php", "User"),
        ("crates/x/tests/integration.rs", "rust", "lib"),
        ("src/lib.rs", "rust", False),
        ("tests/test_parser.c", "c", "parser"),
        ("src/parser_unittest.cc", "cpp", "parser"),
        ("docs/test_plan.md", "markdown", False),
    ],
)
def test_classify(path: str, language: str, subject: str | None | bool) -> None:
    found = classify(path, language)
    if subject is False:
        assert found is None
    else:
        assert found is not None
        assert found.subject == subject


# One case per row of the brief's table: files, then the expected (test, source) pairs.
ROWS = {
    "python": (
        ["pkg/tests/test_user.py", "pkg/user.py", "other/user.py", "pkg/pyproject.toml"],
        {("pkg/tests/test_user.py", "pkg/user.py")},
        {"pkg/pyproject.toml": '[project]\nname = "pkg"\n'},
    ),
    "typescript": (
        ["web/src/api.ts", "web/src/api.test.ts", "web/src/__tests__/client.tsx",
         "web/src/client.tsx"],
        {("web/src/api.test.ts", "web/src/api.ts"),
         ("web/src/__tests__/client.tsx", "web/src/client.tsx")},
        {},
    ),
    "go": (
        ["svc/user.go", "svc/user_test.go", "other/user.go", "lonely/thing_test.go"],
        {("svc/user_test.go", "svc/user.go")},
        {},
    ),
    "java": (
        ["core/src/main/java/com/acme/Money.java", "core/src/test/java/com/acme/MoneyTest.java",
         "web/src/main/java/com/other/Money.java"],
        {("core/src/test/java/com/acme/MoneyTest.java", "core/src/main/java/com/acme/Money.java")},
        {},
    ),
    "csharp": (
        ["src/Shop/Services/Cart.cs", "src/Other/Services/Cart.cs", "src/Other/Cart.cs",
         "tests/Shop.Tests/Services/CartTests.cs"],
        {("tests/Shop.Tests/Services/CartTests.cs", "src/Shop/Services/Cart.cs")},
        {},
    ),
    "ruby": (
        ["app/models/user.rb", "app/views/user.rb", "spec/models/user_spec.rb"],
        {("spec/models/user_spec.rb", "app/models/user.rb")},
        {},
    ),
    "php": (
        ["src/Models/User.php", "src/Http/User.php", "tests/Unit/Models/UserTest.php"],
        {("tests/Unit/Models/UserTest.php", "src/Models/User.php")},
        {},
    ),
    "rust": (
        ["crates/a/src/lib.rs", "crates/a/tests/smoke.rs", "crates/b/src/main.rs",
         "crates/b/tests/cli.rs"],
        {("crates/a/tests/smoke.rs", "crates/a/src/lib.rs"),
         ("crates/b/tests/cli.rs", "crates/b/src/main.rs")},
        {},
    ),
    "c": (
        ["src/parser.c", "include/parser.h", "tests/test_parser.c"],
        {("tests/test_parser.c", "src/parser.c")},  # a source file beats its header
        {},
    ),
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_pairing_per_language(row: str, tmp_path: Path) -> None:
    paths, expected, extra = ROWS[row]
    found, _ = pairs(tree(tmp_path, paths, extra))
    assert {(t, s) for t, s, _ in found} == expected
    assert {c for _, _, c in found} == {0.8}


def test_same_package_beats_a_nearer_folder(tmp_path: Path) -> None:
    # a/lib/z/util.py is one folder step closer to the test, but in another package.
    root = tree(
        tmp_path,
        ["a/tests/test_util.py", "a/src/x/y/util.py", "a/lib/z/util.py"],
        {"a/pyproject.toml": '[project]\nname = "a"\n',
         "a/lib/z/pyproject.toml": '[project]\nname = "z"\n'},
    )
    found, _ = pairs(root)
    assert found == {("a/tests/test_util.py", "a/src/x/y/util.py", 0.8)}
    (root / "a/lib/z/pyproject.toml").unlink()  # same package now: the nearer one wins
    found, _ = pairs(root)
    assert found == {("a/tests/test_util.py", "a/lib/z/util.py", 0.8)}


def test_code_beats_a_nearer_type_stub(tmp_path: Path) -> None:
    found, _ = pairs(tree(tmp_path, ["tests/test_api.py", "api.pyi", "pkg/sub/api.py"]))
    assert found == {("tests/test_api.py", "pkg/sub/api.py", 0.8)}


def test_rust_crate_without_src_lib_uses_its_declared_targets(tmp_path: Path) -> None:
    bin_only = '[package]\nname = "rg"\n\n[[bin]]\nname = "rg"\npath = "crates/core/main.rs"\n'
    custom_lib = '[package]\nname = "x"\n\n[lib]\npath = "lib.rs"\n'
    root = tree(
        tmp_path,
        ["tests/cli.rs", "crates/core/main.rs", "x/lib.rs", "x/tests/t.rs"],
        {"Cargo.toml": bin_only, "x/Cargo.toml": custom_lib},
    )
    found, _ = pairs(root)
    assert found == {
        ("tests/cli.rs", "crates/core/main.rs", 0.8),
        ("x/tests/t.rs", "x/lib.rs", 0.8),
    }


def test_equally_good_candidates_split_confidence(tmp_path: Path) -> None:
    found, report = pairs(tree(tmp_path, ["tests/test_utils.py", "a/utils.py", "b/utils.py"]))
    assert found == {
        ("tests/test_utils.py", "a/utils.py", 0.4),
        ("tests/test_utils.py", "b/utils.py", 0.4),
    }
    assert report["ambiguous"] == 1


def test_ambiguous_edges_record_candidate_count(tmp_path: Path) -> None:
    root = tree(tmp_path, ["tests/test_utils.py", "a/utils.py", "b/utils.py", "c/utils.py"])
    _, edges = TestConventionsAnalyzer().analyze(root, records(root), SNAPSHOT)
    assert [e.attrs for e in edges] == [{"candidates": 3}] * 3
    assert {round(e.confidence, 4) for e in edges} == {round(0.8 / 3, 4)}


def test_unpaired_tests_are_reported_not_errors(tmp_path: Path) -> None:
    found, report = pairs(tree(tmp_path, [
        "tests/test_missing.py", "tests/conftest.py", "tests/test_app.py", "app.py",
    ]))
    assert found == {("tests/test_app.py", "app.py", 0.8)}
    assert report == {
        "test_files": 3,
        "paired": 1,
        "ambiguous": 0,
        "unpaired": ["tests/conftest.py", "tests/test_missing.py"],
    }


def test_tests_never_pair_with_other_tests(tmp_path: Path) -> None:
    found, _ = pairs(tree(tmp_path, ["tests/test_a.py", "other/tests/a.py"]))
    assert found == set()


def test_sample_monorepos_pair_their_tests() -> None:
    found, _ = pairs(SAMPLES / "maven")
    assert found == {(
        "core/src/test/java/com/acme/core/MoneyTest.java",
        "core/src/main/java/com/acme/core/Money.java",
        0.8,
    )}
    found, _ = pairs(SAMPLES / "dotnet")
    assert found == {("tests/Shop.Core.Tests/MoneyTests.cs", "src/Shop.Core/Money.cs", 0.8)}
    found, _ = pairs(SAMPLES / "rust")
    assert found == {("crates/core_lib/tests/integration.rs", "crates/core_lib/src/lib.rs", 0.8)}
    found, _ = pairs(SAMPLES / "go")
    assert found == {("lib/lib_test.go", "lib/lib.go", 0.8)}
    found, _ = pairs(SAMPLES / "php")
    assert found == {("tests/UserTest.php", "src/User.php", 0.8)}
