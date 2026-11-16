"""Cutting documentation files into sections at their headings."""

from pathlib import Path

from codeatlas.indexer.generic.adapter import MAX_SECTION_CHARS, section_nodes
from codeatlas.indexer.generic.sections import TOP_TITLE, Section, split_sections
from codeatlas.indexer.pipeline.build import build_graph
from codeatlas.models import EdgeKind, NodeKind
from codeatlas.store import GraphStore

MARKDOWN = """Intro line.

# Demo

About the demo.

## Install

```bash
# not a heading
pip install demo
```

## Use
Run it.
"""


def test_markdown_is_cut_at_each_heading() -> None:
    sections = split_sections(MARKDOWN, "markdown")
    assert [(s.title, s.level, s.start_line, s.end_line) for s in sections] == [
        (TOP_TITLE, 0, 1, 2),
        ("Demo", 1, 3, 6),
        ("Install", 2, 7, 13),
        ("Use", 2, 14, 15),
    ]
    assert sections[0].text == "Intro line."
    assert sections[1].text == "About the demo."
    assert "# not a heading" in sections[2].text  # a comment in a code block stays text
    assert sections[3].text == "Run it."


def test_no_line_belongs_to_two_sections() -> None:
    sections = split_sections(MARKDOWN, "markdown")
    for before, after in zip(sections, sections[1:], strict=False):
        assert before.end_line + 1 == after.start_line
    assert sections[-1].end_line == len(MARKDOWN.splitlines())


def test_a_file_without_headings_is_one_section() -> None:
    assert split_sections("just\ntext\n", "markdown") == [Section(TOP_TITLE, 0, 1, 2, "just\ntext")]
    assert split_sections("", "markdown") == []
    assert split_sections("\n\n# Only\n", "markdown") == [Section("Only", 1, 3, 3, "")]


def test_markdown_underlined_headings_and_closing_hashes() -> None:
    text = "Title\n=====\n\nbody\n\nSub\n---\nmore\n\n### Third ###\n\n- item\n---\n"
    found = [(s.title, s.level, s.start_line) for s in split_sections(text, "markdown")]
    # The `---` under the list item is a rule, not a heading.
    assert found == [("Title", 1, 1), ("Sub", 2, 6), ("Third", 3, 10)]


def test_rst_levels_follow_the_order_the_underlines_appear() -> None:
    text = ("=====\nGuide\n=====\n\nintro\n\nInstall\n-------\n\nsteps\n\n"
            "Linux\n~~~~~\n\napt\n\nUse\n---\n\nrun\n")
    sections = split_sections(text, "rst")
    assert [(s.title, s.level, s.start_line) for s in sections] == [
        ("Guide", 1, 1), ("Install", 2, 7), ("Linux", 3, 12), ("Use", 2, 17),
    ]
    assert sections[1].text == "steps"


def test_rst_ignores_a_short_underline_and_a_table_border() -> None:
    text = "A long title here\n---\n\n=====  =====\nA      B\n=====  =====\n"
    assert [s.title for s in split_sections(text, "rst")] == [TOP_TITLE]


# Sections as nodes


def test_section_nodes_have_stable_keys_and_number_a_repeated_heading() -> None:
    text = "intro\n\n# Use\na\n\n## Use\nb\n\n# v1.2 notes\n"
    nodes = section_nodes("docs/guide.md", "markdown", text, "demo@abc")
    assert [n.key for n in nodes] == [
        f"docs/guide.md::section:{TOP_TITLE}",
        "docs/guide.md::section:Use",
        "docs/guide.md::section:Use#2",
        "docs/guide.md::section:v1.2 notes",
    ]
    assert all(n.kind is NodeKind.SECTION and n.path == "docs/guide.md" for n in nodes)
    assert [n.attrs["level"] for n in nodes] == [0, 1, 2, 1]
    assert [n.docstring for n in nodes] == ["intro", "a", "b", None]
    assert (nodes[1].span.start_line, nodes[1].span.end_line) == (3, 5)


def test_a_long_section_is_cut_and_says_so() -> None:
    text = "# Big\n" + "word " * 2000
    (node,) = section_nodes("a.md", "markdown", text, "demo@abc")
    assert len(node.docstring or "") == MAX_SECTION_CHARS
    assert node.attrs["truncated"] is True
    (small,) = section_nodes("a.md", "markdown", "# Small\ntext\n", "demo@abc")
    assert "truncated" not in small.attrs


def test_an_indexed_readme_is_found_by_its_text(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Demo\n\n## v1\nold\n\n## v1.2 Install\nUse the zeppelin installer.\n",
        encoding="utf-8")
    (tmp_path / "notes.rst").write_text("Notes\n=====\n\nAbout walruses.\n", encoding="utf-8")
    store = GraphStore(":memory:")
    built = build_graph(str(tmp_path), store)
    sid = built.snapshot_id

    (hit, _), *_ = store.search_text(sid, "zeppelin", docs=True)
    assert (hit.kind, hit.name, hit.path) == (NodeKind.SECTION, "v1.2 Install", "README.md")
    (rst, _), *_ = store.search_text(sid, "walruses", docs=True)
    assert (rst.kind, rst.name, rst.path) == (NodeKind.SECTION, "Notes", "notes.rst")
    # Code and documentation are two searches: neither list holds the other's nodes.
    assert store.search_text(sid, "zeppelin") == []
    assert store.search_text(sid, "run", docs=True) == []
    assert [n.name for n, _ in store.search_text(sid, "run")] == ["run"]

    # Every section hangs off its file, also one whose heading holds a dot.
    readme = store.module_for_path(sid, "README.md")
    assert readme is not None
    inside = {e.dst_id for e in store.edges_from(readme.id, (EdgeKind.CONTAINS,))}
    sections = [n for n in store.nodes_in_file(sid, "README.md") if n.kind is NodeKind.SECTION]
    assert len(sections) == 3 and inside == {n.id for n in sections}
    # A documentation file has nothing to resolve, so it is not a language missing a resolver.
    assert built.languages_without_resolver == []
