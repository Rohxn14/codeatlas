"""Mutant selection, the text mutations, result parsing and the Windows refusal."""

import ast

import pytest

from codeatlas.indexer.pipeline import build_graph
from codeatlas.store import GraphStore
from eval.mutants import __main__ as mutants_main
from eval.mutants.mutate import mutate_python, mutate_typescript
from eval.mutants.run import failing_ids, load_benchmarks
from eval.mutants.select import candidate_functions, pick

PY = b'''import os


class Box:
    def put(self, item):
        """Store."""
        self.item = item
        return item


def plain(x):
    y = x + 1
    return y


def oneliner(x): return x
'''

TS = b"""export function a(x: number): number {
  const s = "}";  // a } in a string and a comment
  return x + s.length;
}

export const arrow = (x: number) => x + 1;

export class K {
  m(opts: { a: number }): { b: number } {
    return { b: opts.a };
  }
}
"""


def test_python_body_is_replaced():
    result = mutate_python(PY, "plain", 11, 13)
    assert result.text is not None
    text = result.text.decode()
    assert 'def plain(x):\n    raise RuntimeError("mutant")\n' in text
    ast.parse(text)  # still valid Python
    assert "y = x + 1" not in text
    assert "def oneliner" in text  # nothing else changed


def test_python_method_keeps_its_indent_and_drops_the_docstring_too():
    result = mutate_python(PY, "put", 5, 8)
    assert result.text is not None
    assert '    def put(self, item):\n        raise RuntimeError("mutant")\n\n\ndef plain' in (
        result.text.decode()
    )


def test_python_one_line_body_is_skipped_with_a_reason():
    result = mutate_python(PY, "oneliner", 16, 16)
    assert result.text is None
    assert "same line" in result.reason


def test_typescript_throw_goes_after_the_body_brace():
    result = mutate_typescript(TS, 1, 4, 1)
    assert result.text is not None
    assert result.text.decode().startswith(
        'export function a(x: number): number { throw new Error("mutant");\n'
    )


def test_typescript_method_with_object_types_finds_the_right_brace():
    result = mutate_typescript(TS, 9, 11, 3)
    assert result.text is not None
    assert '{ b: number } { throw new Error("mutant");' in result.text.decode()


def test_typescript_expression_bodied_arrow_is_skipped():
    result = mutate_typescript(TS, 6, 6, 41)
    assert result.text is None
    assert "no block body" in result.reason


def graph_of(make_repo):
    root = make_repo(
        {
            "lib.py": "\n".join(f"def f{i}():\n    return {i}\n" for i in range(12)),
            "main.py": "from lib import *\n\n"
            + "\n".join(f"def g{i}():\n    return f{i}()\n" for i in range(12)),
            "test_lib.py": "def test_f0():\n    assert True\n",
        }
    )
    store = GraphStore(":memory:")
    result = build_graph(str(root), store)
    return store, result.snapshot_id


def test_selection_is_deterministic_and_skips_tests(make_repo):
    store, snapshot = graph_of(make_repo)
    pool = candidate_functions(store, snapshot)
    assert pool.basis == "raw-call-names"
    keys = [n.key for n in pool.functions]
    assert keys == sorted(keys)
    assert not any("test_" in k for k in keys)
    assert all(k.startswith("lib.py::f") for k in keys)  # only called functions
    first = [n.key for n in pick(pool.functions, 5, seed=7)]
    assert first == [n.key for n in pick(pool.functions, 5, seed=7)]
    assert len(set(first)) == 5
    assert first != [n.key for n in pick(pool.functions, 5, seed=8)]
    assert len(pick(pool.functions, 99, seed=1)) == len(pool.functions)


def test_failing_ids_from_pytest_and_vitest_output():
    pytest_out = "FAILED tests/test_a.py::test_x - assert 1 == 2\nERROR tests/test_b.py\n3 failed"
    assert failing_ids("pytest", pytest_out) == ["tests/test_a.py::test_x", "tests/test_b.py"]
    vitest_out = (
        'noise {"testResults": [{"name": "/s/tests/a.test.ts", "status": "failed", '
        '"assertionResults": [{"status": "failed", "fullName": "A works"}, '
        '{"status": "passed", "fullName": "A ok"}]}]}'
    )
    assert failing_ids("vitest", vitest_out) == ["a.test.ts::A works"]


def test_benchmarks_file_pins_the_fixture_and_a_python_repo():
    benches = {b.name: b for b in load_benchmarks()}
    assert benches["polyglot_app"].commands["python"].run == "pytest backend"
    assert benches["polyglot_app"].commands["typescript"].run == "npx vitest run"
    assert len(benches["itsdangerous"].sha or "") == 40


def test_windows_refuses_and_says_why(monkeypatch, capsys):
    monkeypatch.setattr(mutants_main.sys, "platform", "win32")
    assert mutants_main.main(["polyglot_app"]) == 2
    assert "cloud VM or a container" in capsys.readouterr().out


@pytest.mark.live
def test_fixture_python_mutants_are_caught():
    """Runs the fixture's real tests: needs its requirements installed."""
    from pathlib import Path

    from eval.mutants.run import run_benchmark

    bench = {b.name: b for b in load_benchmarks()}["polyglot_app"]
    root = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "polyglot_app"
    truth = run_benchmark(bench, root, count=3)
    assert truth["mutants_caught"] >= 1
