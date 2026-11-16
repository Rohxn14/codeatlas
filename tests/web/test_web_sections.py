"""Documentation sections in the web app: found by search, listed on the file, opened."""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.web import create_app, snapshot_slug

FILES = {
    "app.py": "def run():\n    pass\n",
    "README.md": "# Demo\n\nA demo.\n\n## Install <b>now</b>\n\nUse the zeppelin installer.\n",
}


def test_search_finds_a_section_and_its_page_shows_the_text(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    sid = index_repository(str(make_repo(FILES, name="demo")), config, db_path).snapshot["id"]
    client = TestClient(create_app(db_path, config))
    base = f"/s/{snapshot_slug(sid)}"
    key = "README.md::section:Install <b>now</b>"

    found = client.get(f"{base}/search", params={"q": "zeppelin"}).text
    assert f"{base}/symbol?key={quote(key)}" in found
    assert "Install &lt;b&gt;now&lt;/b&gt;" in found and "<b>now</b>" not in found
    assert '<span class="tag">section</span>' in found
    assert "In the documentation" in found and "In the code" not in found

    page = client.get(f"{base}/symbol", params={"key": key})
    assert page.status_code == 200
    assert "Use the zeppelin installer." in page.text
    assert "What could a change here break?" not in page.text
    assert "Used by" not in page.text

    outline = client.get(f"{base}/file", params={"path": "README.md"}).text
    assert "Defined here" in outline and "--depth: 1" in outline
