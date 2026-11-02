import json
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "search" / "fixture_queries.json"


def test_fixture_queries_are_well_formed():
    queries = json.loads(DATA.read_text(encoding="utf-8"))
    assert len(queries) == 15
    for q in queries:
        assert q["question"].endswith("?") and q["expected"]
        assert all("::" in key for key in q["expected"])
