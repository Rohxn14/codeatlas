"""An answer's Markdown as HTML: readable, and unable to carry anything of the model's own."""

import pytest

from codeatlas.agent.loop import Answer, CitationCheck
from codeatlas.web.markdown import render_answer

SID = "r@0123456789ab"
NB_HYPHEN, OPEN, CLOSE = chr(0x2011), chr(0x3010), chr(0x3011)


def render(text: str, *citations: CitationCheck) -> str:
    return str(render_answer(Answer(text, citations=list(citations)), "/s/r"))


def test_lists_tables_emphasis_and_code_are_formatted() -> None:
    html = render("## Title\n\n1. **one**\n2. `two`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                  "```\nx < 1\n```")
    for piece in ("<h2>Title</h2>", "<ol>", "<strong>one</strong>", "<code>two</code>",
                  "<table>", "<td>2</td>", "x &lt; 1"):
        assert piece in html


@pytest.mark.parametrize("text", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[click](https://evil.example)",
    "[click](javascript:alert(1))",
    "![x](https://evil.example/track.png)",
    "<https://evil.example>",
    "[a]: https://evil.example\n\n[a]",
    "a <b onmouseover=alert(1)>b</b>",
])
def test_nothing_of_the_models_becomes_a_tag_a_link_or_an_image(text: str) -> None:
    # A repository can hold text written to steer the model, so its answer is untrusted.
    html = render(text)
    assert "<script" not in html and "<img" not in html and "<a " not in html and "<b " not in html
    assert "href" not in html and "src=x" not in html.replace("&lt;img src=x", "")


def test_a_checked_citation_becomes_a_short_link() -> None:
    cite = f"{SID}:src/a b/clean_er.py:588"
    html = render(f"It validates ({cite}).", CitationCheck(cite, "src/a b/clean_er.py", 588, True))
    assert '<a class="cite" href="/s/r/file?path=src/a%20b/clean_er.py#L588"' in html
    assert ">clean_er.py:588</a>" in html and SID not in html  # underscores are not emphasis


def test_a_range_and_the_models_brackets() -> None:
    cite = f"{SID}:a.py:588{NB_HYPHEN}600"
    html = render(f"Here{OPEN}{cite}{CLOSE}.", CitationCheck(cite, "a.py", 588, True))
    assert ">a.py:588-600</a>" in html and OPEN not in html and CLOSE not in html


def test_the_longer_citation_is_not_cut_at_the_shorter_one() -> None:
    long, short = f"{SID}:a.py:12", f"{SID}:a.py:1"
    html = render(f"see {long} and {short}, also in `{short}`.",
                  CitationCheck(short, "a.py", 1, True), CitationCheck(long, "a.py", 12, True))
    assert html.count(">a.py:12</a>") == 1 and html.count(">a.py:1</a>") == 2


def test_a_citation_of_no_real_place_is_marked_and_escaped() -> None:
    cite = f"{SID}:gone.py:4"
    html = render(f"At {cite}.", CitationCheck(cite, "gone.py", 4, False, "<no> such file"))
    assert 'class="cite invalid"' in html and "not a real place: &lt;no&gt; such file" in html
    assert "<a " not in html


def test_the_marks_cannot_be_forged_by_the_answer() -> None:
    forged = f"{chr(0xE000)}0{chr(0xE001)}"
    cite = f"{SID}:a.py:1"
    html = render(f"{forged} then {cite}", CitationCheck(cite, "a.py", 1, True))
    assert html.count("<a ") == 1


def test_quoted_code_that_is_not_in_the_file_is_marked() -> None:
    from codeatlas.agent.quotes import QuoteCheck

    text = 'It runs `go("x < 1")` and `stay()`.'
    answer = Answer(text, quotes=[QuoteCheck('go("x < 1")', ("src/a.py",), ("go",)),
                                  QuoteCheck("stay()", ("src/a.py",), ())])
    html = str(render_answer(answer, "/s/r"))
    assert html.count('class="unfound"') == 1 and "go: not in a.py, cited beside it" in html
    assert "<code>stay()</code>" in html
