"""What a follow-up question remembers: the last few questions and answers of its chat (D-64).

"And who calls it?" means nothing on its own, and a language model knows only what a request
carries. So a question is sent with the exchanges before it, the way the owner's claim
verifier does: the last three (its `history[-6:]`, six messages), shown as context to
understand the question, never as evidence. The answer must still come from tool results.

Answers are cut. On the 32 recorded answers (Nov 26) the median is 1,180 characters but the
longest is 6,200, and every step of a question re-sends the history: three long answers
would add about 4,600 tokens to each request, more than half of Groq's 8,000 a minute.
Cut at 1,200 characters, over half the answers stay whole and three cost at most about 950.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_EXCHANGES = 3
MAX_ANSWER_CHARS = 1_200
CUT_MARK = " [...]"
HISTORY_INTRO = ("Earlier in this conversation, oldest first. Use it only to understand what "
                 "the question refers to. It is not evidence: every claim must still come "
                 "from a tool result.")
QUESTION_NOW = "The question now:"


@dataclass(frozen=True, slots=True)
class Exchange:
    """One question of a chat, and its answer (None while it is made, or when it failed)."""

    question: str
    answer: str | None


def recent_exchanges(chat: Sequence[Exchange], limit: int = MAX_EXCHANGES,
                     max_chars: int = MAX_ANSWER_CHARS) -> list[Exchange]:
    """The last `limit` answered exchanges of `chat` (oldest first), answers cut to `max_chars`.

    An exchange with no answer is left out and does not use up a place: a failed question
    has nothing to remember. `limit` 0 remembers nothing (`chat[-0:]` would be all of it).
    """
    answered = [e for e in chat if e.answer]
    kept = answered[-limit:] if limit > 0 else []
    return [Exchange(e.question, _cut(e.answer or "", max_chars)) for e in kept]


def _cut(text: str, max_chars: int) -> str:
    """`text`, or its start and CUT_MARK, never longer than `max_chars`."""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(CUT_MARK))].rstrip() + CUT_MARK


def with_history(content: str, exchanges: Sequence[Exchange]) -> str:
    """The user message: the earlier exchanges, then the question (with its leads)."""
    if not exchanges:
        return content
    lines = [HISTORY_INTRO, ""]
    for number, exchange in enumerate(exchanges, start=1):
        lines += [f"Question {number}: {exchange.question}", f"Answer {number}: {exchange.answer}",
                  ""]
    return "\n".join([*lines, f"{QUESTION_NOW} {content}"])
