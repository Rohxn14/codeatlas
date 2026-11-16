"""Cutting documentation files into sections at their headings."""

from codeatlas.indexer.generic.sections import TOP_TITLE, Section, split_sections

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
