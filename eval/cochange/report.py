"""Markdown table for the co-change benchmark."""

from __future__ import annotations

COLUMNS = ("queries", "precision@5", "recall@5", "precision@10", "recall@10", "no_prediction_share")


def _cell(value: object) -> str:
    return "n/a" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))


def table(results: list[dict[str, object]], date: str) -> str:
    """One row per (repository, predictor), then one per language of the changed file."""
    lines = [
        f"# Co-change benchmark, {date}",
        "",
        "| repo | predictor | language | " + " | ".join(COLUMNS) + " |",
        "|" + " --- |" * (3 + len(COLUMNS)),
    ]
    for result in results:
        if result.get("error"):
            lines.append(f"| {result['name']} | (failed: {result['error']}) |"
                         + " |" * (1 + len(COLUMNS)))
        for score in result["scores"]:  # type: ignore[attr-defined]
            groups = [("all", score["overall"])]
            groups += [(lang, s) for lang, s in score["by_language"].items()]
            for language, summary in groups:
                cells = " | ".join(_cell(summary[c]) for c in COLUMNS)
                lines.append(f"| {result['name']} | {score['predictor']} | {language} | {cells} |")
    return "\n".join(lines) + "\n"
