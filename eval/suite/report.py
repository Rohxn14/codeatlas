"""The markdown scoreboard: one row per repository, then totals."""

from __future__ import annotations

from collections import Counter

HEADER = (
    "| repo | size | status | s | MB | files | deep / struct / text | top languages | "
    "parse-err files | skipped | nodes | edges | raw calls | unresolved | limits | problems |"
)


def scoreboard(rows: list[dict[str, object]], date: str) -> str:
    """Markdown for the rows; failed repositories show their error instead of numbers."""
    lines = [f"# Acceptance suite, {date}", "", HEADER, "|" + " --- |" * (HEADER.count("|") - 1)]
    for row in rows:
        lines.append(_row(row))
    lines += ["", *_totals(rows)]
    return "\n".join(lines) + "\n"


def _row(row: dict[str, object]) -> str:
    name = f"[{row['name']}]({row['url']})"
    if row.get("status") != "completed":
        error = str(row.get("error", "")).replace("|", "\\|").replace("\n", " ")
        stage = row.get("stage", "?")
        blanks = " |" * 12
        return f"| {name} | {row['size']} | **error ({stage})** |{blanks} {error} |"
    tiers = row["files_by_tier"]
    assert isinstance(tiers, dict)
    languages = row["files_by_language"]
    assert isinstance(languages, dict)
    top = ", ".join(f"{k} {v}" for k, v in list(languages.items())[:4])
    skipped = sum(row["skipped_by_reason"].values())  # type: ignore[union-attr]
    unresolved = row["unresolved_share"]
    problems = row["problems"]
    assert isinstance(problems, list)
    return (
        f"| {name} | {row['size']} | ok | {row['seconds']} | {row['peak_memory_mb'] or 'n/a'} "
        f"| {row['files']} | {tiers.get('deep', 0)} / {tiers.get('structural', 0)} "
        f"/ {tiers.get('text', 0)} "
        f"| {top} | {row['files_with_parse_errors']} | {skipped} "
        f"| {sum(row['nodes_by_kind'].values())} | {sum(row['edges_by_kind'].values())} "  # type: ignore[union-attr]
        f"| {row['raw_calls']} | {'n/a' if unresolved is None else f'{unresolved:.0%}'} "
        f"| {', '.join(row['limits_hit']) or '-'} | {len(problems)} |"  # type: ignore[arg-type]
    )


def _totals(rows: list[dict[str, object]]) -> list[str]:
    ok = [r for r in rows if r.get("status") == "completed"]
    tiers: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    raw = resolved = errors = 0
    for r in ok:
        tiers.update(r["files_by_tier"])  # type: ignore[arg-type]
        languages.update(r["files_by_language"])  # type: ignore[arg-type]
        raw += int(r["raw_calls"])  # type: ignore[call-overload]
        resolved += int(r["resolved_calls"])  # type: ignore[call-overload]
        errors += int(r["files_with_parse_errors"])  # type: ignore[call-overload]
    share = f"{1 - resolved / raw:.0%}" if raw else "n/a"
    return [
        "## Totals",
        "",
        f"- repositories: {len(rows)} run, {len(ok)} completed, {len(rows) - len(ok)} failed",
        f"- files: {sum(tiers.values())} (deep {tiers['deep']}, "
        f"structural {tiers['structural']}, text {tiers['text']})",
        f"- languages seen: {len(languages)}",
        f"- files with parse errors: {errors}",
        f"- raw calls: {raw}, unresolved share {share}",
        f"- repositories that hit a limit: {sum(1 for r in ok if r['limits_hit'])}",
        f"- seconds: {sum(float(r['seconds']) for r in ok):.1f}",  # type: ignore[arg-type]
    ]
