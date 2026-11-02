"""The polyglot fixture's labels agree with its source; its own suites pass under `-m live`."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from eval.oracle.graph import load_graph

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "polyglot_app"
GRAPH = load_graph(FIXTURE / "expected_graph.json")


def source_line(path: str, line: int) -> str:
    return (FIXTURE / path).read_text("utf-8").splitlines()[line - 1]


def name(key: str) -> str:
    """Last part of the qualname: a method name, or a test case's own title."""
    qual = key.split("::", 1)[1]
    return qual.rsplit(" > ", 1)[1] if " > " in qual else qual.split(".")[-1]


def callee_name(key: str) -> str:
    """What a call line shows: the name, or the class for a constructor (`__init__`)."""
    parts = key.split("::", 1)[1].split(".")
    return parts[-2] if parts[-1] == "__init__" else name(key)


def test_every_edge_endpoint_is_a_node_and_every_file_exists():
    for edge in GRAPH.edges:
        assert edge.src_key in GRAPH.nodes, edge
        assert edge.dst_key in GRAPH.nodes, edge
    for node in GRAPH.nodes.values():
        assert (FIXTURE / node.path).is_file(), node.path


def test_symbol_spans_start_at_their_definition():
    for node in GRAPH.nodes.values():
        if node.kind in ("module", "route"):
            continue
        first = source_line(node.path, node.start_line)
        head = first + source_line(node.path, node.start_line + 1)  # decorators come first
        assert name(node.key) in head, (node.key, first)
        assert node.start_line <= node.end_line


def test_call_lines_mention_the_callee():
    for edge in GRAPH.edges:
        if edge.kind in ("calls", "tests") and edge.line is not None:
            dst = GRAPH.nodes[edge.dst_key]
            if dst.kind == "module":
                continue
            src = GRAPH.nodes[edge.src_key]
            assert callee_name(edge.dst_key) in source_line(src.path, edge.line), edge
            assert src.start_line <= edge.line <= src.end_line, edge


def test_unresolvable_calls_point_at_their_text():
    assert len(GRAPH.unresolvable) == 3
    for item in GRAPH.unresolvable:
        node = GRAPH.nodes[item.src_key]
        assert item.callee_text in source_line(node.path, item.line)


@pytest.mark.live
def test_backend_suite_passes():
    pytest.importorskip("fastapi")
    done = subprocess.run([sys.executable, "-m", "pytest", "backend", "-q", "-p",
                           "no:cacheprovider"], cwd=FIXTURE, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.live
@pytest.mark.skipif(shutil.which("npx") is None, reason="node is not installed")
def test_frontend_suite_passes():
    frontend = FIXTURE / "frontend"
    if not (frontend / "node_modules").is_dir():
        pytest.skip("run `npm ci` in the fixture's frontend folder first")
    done = subprocess.run(["npx", "vitest", "run"], cwd=frontend, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout + done.stderr
