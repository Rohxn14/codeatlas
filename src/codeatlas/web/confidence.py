"""How the app shows an edge's confidence: three levels, used the same way on every page.

The number on an edge is unchanged (docs/contract.md, section 5). A level only decides
how it is drawn: a solid line for certain, a dashed line for likely, a dotted line for a
guess (decision D-33).
"""

from __future__ import annotations

CERTAIN = "certain"
LIKELY = "likely"
GUESS = "guess"
LEVELS = (CERTAIN, LIKELY, GUESS)

# 0.9 is the lowest "typical confidence" of the resolutions that follow a rule of the
# language (`self.method()`, an exact route). 0.5 means one of two candidates at best.
CERTAIN_FROM = 0.9
LIKELY_FROM = 0.5

MEANING = {
    CERTAIN: "found by a rule of the language, such as a resolved import or self.method()",
    LIKELY: "one of a few candidates, or matched by a pattern or a naming convention",
    GUESS: "matched by name only, among several candidates",
}


def level(confidence: float) -> str:
    """The level a confidence is drawn at."""
    if confidence >= CERTAIN_FROM:
        return CERTAIN
    if confidence >= LIKELY_FROM:
        return LIKELY
    return GUESS
