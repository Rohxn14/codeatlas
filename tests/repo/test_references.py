"""Files that name other files: how a name is looked up, and what is left out (D-62)."""

from pathlib import Path

import pytest

from codeatlas.models import EdgeKind, FileRecord, Resolution, Tier
from codeatlas.repo.references import ReferenceAnalyzer

SID = "demo@0123456789ab"


def named(tmp_path: Path, files: dict[str, str | bytes], code: tuple[str, ...] = (".py",)):
    """(source, target, confidence, resolution, line) for every edge found."""
    records = []
    for path, content in files.items():
        target = tmp_path.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode()
        target.write_bytes(data)
        tier = Tier.DEEP if path.endswith(code) else Tier.TEXT
        records.append(FileRecord(path, "python" if tier is Tier.DEEP else "text", tier, "x",
                                  len(data)))
    nodes, edges = ReferenceAnalyzer().analyze(tmp_path, records, SID)
    assert nodes == [] and all(e.kind is EdgeKind.REFERENCES for e in edges)

    def path_of(node_id: str) -> str:
        return node_id.removeprefix(SID + "/").removesuffix("::")

    return [(path_of(e.src_id), path_of(e.dst_id), e.confidence, e.resolution, e.line)
            for e in edges]


def test_a_path_is_looked_up_next_to_the_file_then_from_the_root(tmp_path: Path) -> None:
    found = named(tmp_path, {
        "docs/guide.md": "intro\n![chart](images/chart.png) and ../README.md\nsee app/main.py",
        "docs/images/chart.png": b"\x89PNG\x00", "README.md": "hello", "app/main.py": "x = 1",
    })
    assert found == [
        ("docs/guide.md", "README.md", 1.0, Resolution.DIRECT, 2),
        ("docs/guide.md", "app/main.py", 1.0, Resolution.DIRECT, 3),
        ("docs/guide.md", "docs/images/chart.png", 1.0, Resolution.DIRECT, 2),
    ]


def test_a_bare_name_next_to_it_at_the_root_or_the_only_one(tmp_path: Path) -> None:
    found = named(tmp_path, {
        "ci/build.yml": "run: pip install -r requirements.txt\nuses: steps.yml\nsee notes.md",
        "ci/steps.yml": "a: 1", "requirements.txt": "pandas", "deep/down/notes.md": "x",
    })
    assert [(t, c, r) for _, t, c, r, _ in found] == [
        ("ci/steps.yml", 0.8, Resolution.CONVENTION),
        ("deep/down/notes.md", 0.3, Resolution.NAME_GUESS),
        ("requirements.txt", 0.8, Resolution.CONVENTION),
    ]


def test_a_name_two_files_have_is_not_guessed(tmp_path: Path) -> None:
    files = {"a.md": "see notes.md and lib/x.md", "p/notes.md": "1", "q/notes.md": "2",
             "p/lib/x.md": "3", "q/lib/x.md": "4"}
    assert named(tmp_path, files) == []


def test_the_end_of_a_path_is_a_guess(tmp_path: Path) -> None:
    files = {"a.md": "the rules are in pipeline/lake.py", "src/pipeline/lake.py": "x = 1"}
    assert named(tmp_path, files) == [
        ("a.md", "src/pipeline/lake.py", 0.3, Resolution.NAME_GUESS, 1)]


def test_a_folder_shares_its_confidence_among_its_files(tmp_path: Path) -> None:
    files: dict[str, str | bytes] = {"ui.py": 'ICONS = "images/tyres/"\nBIG = "images/many/"\n'}
    files |= {f"images/tyres/{i}.png": b"\x00" for i in range(5)}
    files |= {f"images/many/{i}.png": b"\x00" for i in range(30)}
    found = named(tmp_path, files)
    assert [f[2] for f in found] == [pytest.approx(0.2)] * 5
    assert {f[1].rsplit("/", 1)[0] for f in found} == {"images/tyres"}  # 30 files say nothing


def test_code_naming_code_is_left_to_imports(tmp_path: Path) -> None:
    files = {"a.py": "# see b.py and data.json", "b.py": "x = 1", "data.json": "{}"}
    assert [(s, t) for s, t, *_ in named(tmp_path, files)] == [("a.py", "data.json")]


def test_the_surest_way_wins_and_a_file_never_names_itself(tmp_path: Path) -> None:
    files = {"docs/a.md": "b.md\nthen docs/b.md, and a.md itself", "docs/b.md": "x"}
    assert named(tmp_path, files) == [("docs/a.md", "docs/b.md", 1.0, Resolution.DIRECT, 2)]


def test_secrets_binaries_and_long_files_are_not_read(tmp_path: Path) -> None:
    files = {".env": "FILE=data.json", "x.png": b"data.json\x00", "big.json": "data.json " * 60_000,
             "app.min.js": "data.json", "data.json": "{}"}
    assert named(tmp_path, files) == []


def test_addresses_and_sentences_name_nothing(tmp_path: Path) -> None:
    files = {"a.md": "https://github.com/x/y/blob/main/b.md e.g. v1.2 and/or etc. 3.14",
             "docs/b.md": "x"}
    assert named(tmp_path, files) == []
