"""An answer's Markdown as HTML, with its citations as links.

An answer is untrusted: the model wrote it after reading a repository anyone may have
written. So raw HTML, links, images and automatic links are all off, which leaves
paragraphs, lists, tables, emphasis and code. Only a citation that was checked against the
map becomes a link, and this module writes that link itself.
"""

from __future__ import annotations

import re
from html import escape
from urllib.parse import quote

from markdown_it import MarkdownIt
from markupsafe import Markup

from codeatlas.agent.loop import Answer, CitationCheck

# A citation is swapped for a mark Markdown leaves alone (two private-use characters around
# a number), and the mark for its link after rendering.
_OPEN, _CLOSE = chr(0xE000), chr(0xE001)
_MARK = re.compile(f"{_OPEN}(\\d+){_CLOSE}")
# gpt-oss puts its citations in these brackets; around a link they are noise.
_BRACKETS = re.compile(f"{chr(0x3010)}((?:{_OPEN}\\d+{_CLOSE}[\\s,;]*)+){chr(0x3011)}")
_RANGE_END = re.compile(f"[-{chr(0x2011)}{chr(0x2013)}](\\d+)$")


def _renderer() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    return md.disable(["link", "image", "autolink", "html_block", "html_inline", "reference"])


def render_answer(answer: Answer, base: str) -> Markup:
    """The answer as safe HTML. `base` is the address of the snapshot's pages."""
    text = answer.text.replace(_OPEN, "").replace(_CLOSE, "")
    by_text = {c.text: i for i, c in enumerate(answer.citations)}
    if by_text:
        # Longest first, so a citation that is the start of a longer one never cuts it.
        pattern = "|".join(re.escape(t) for t in sorted(by_text, key=len, reverse=True))
        text = re.sub(pattern, lambda m: f"{_OPEN}{by_text[m.group(0)]}{_CLOSE}", text)
        text = _BRACKETS.sub(r" \1", text)
    html = _renderer().render(text)
    for found in answer.unfound_quotes:
        where = ", ".join(p.rsplit("/", 1)[-1] for p in found.paths)
        why = escape(f"{', '.join(found.missing)}: not in {where}, cited beside it")
        # As markdown-it writes it: quotes are escaped inside code.
        code = escape(found.text, quote=False).replace('"', "&quot;")
        html = html.replace(f"<code>{code}</code>",
                            f'<code class="unfound" title="{why}">{code}</code>')
    return Markup(_MARK.sub(lambda m: _citation(answer.citations, int(m.group(1)), base), html))


def _citation(citations: list[CitationCheck], index: int, base: str) -> str:
    if index >= len(citations):
        return ""
    c = citations[index]
    if not c.valid:
        return (f'<span class="cite invalid" title="{escape(c.reason)}">{escape(c.text)} '
                f"(not a real place: {escape(c.reason)})</span>")
    end = _RANGE_END.search(c.text)
    label = f"{c.path.rsplit('/', 1)[-1]}:{c.line}" + (f"-{end.group(1)}" if end else "")
    href = f"{base}/file?path={quote(c.path)}#L{c.line}"
    title = escape(f"{c.path}:{c.line}")
    return f'<a class="cite" href="{escape(href)}" title="{title}">{escape(label)}</a>'
