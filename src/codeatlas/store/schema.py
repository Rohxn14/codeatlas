"""The SQLite schema (v1) and the checks run when a database is opened."""

import sqlite3

SCHEMA_VERSION = "1"


class StoreError(RuntimeError):
    """The database cannot be used as it is: missing FTS5 or an old schema."""


DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id              TEXT PRIMARY KEY,
    repo            TEXT NOT NULL,
    commit_sha      TEXT NOT NULL,
    indexed_at      TEXT NOT NULL,
    indexer_version TEXT NOT NULL,
    source          TEXT NOT NULL,
    limits_hit_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS snapshots_repo ON snapshots (repo, indexed_at);

CREATE TABLE IF NOT EXISTS files (
    snapshot_id TEXT NOT NULL,
    path        TEXT NOT NULL,
    language    TEXT NOT NULL,
    tier        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS nodes (
    pk          INTEGER PRIMARY KEY,
    id          TEXT NOT NULL UNIQUE,
    key         TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    kind        TEXT NOT NULL,
    language    TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualname    TEXT NOT NULL,
    path        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    start_col   INTEGER NOT NULL,
    end_col     INTEGER NOT NULL,
    signature   TEXT,
    docstring   TEXT,
    owner_key   TEXT,
    attrs_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS nodes_key   ON nodes (snapshot_id, key);
CREATE INDEX IF NOT EXISTS nodes_name  ON nodes (snapshot_id, name);
CREATE INDEX IF NOT EXISTS nodes_path  ON nodes (snapshot_id, path);
CREATE INDEX IF NOT EXISTS nodes_owner ON nodes (snapshot_id, owner_key);

CREATE TABLE IF NOT EXISTS edges (
    snapshot_id TEXT NOT NULL,
    src_id      TEXT NOT NULL,
    dst_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    confidence  REAL NOT NULL,
    resolution  TEXT NOT NULL,
    line        INTEGER,
    attrs_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS edges_src ON edges (snapshot_id, src_id, kind);
CREATE INDEX IF NOT EXISTS edges_dst ON edges (snapshot_id, dst_id, kind);

CREATE TABLE IF NOT EXISTS raw_calls (
    snapshot_id TEXT NOT NULL,
    caller_key  TEXT NOT NULL,
    callee_text TEXT NOT NULL,
    name        TEXT NOT NULL,
    receiver    TEXT,
    line        INTEGER NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS raw_calls_caller ON raw_calls (snapshot_id, caller_key);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5 (
    name, qualname, signature, docstring, path,
    content='nodes', content_rowid='pk'
);

-- pk is declared so VACUUM never renumbers the rowids nodes_fts points at.
-- External-content FTS tables are not updated by SQLite itself; these triggers keep
-- nodes_fts in step with nodes.
CREATE TRIGGER IF NOT EXISTS nodes_fts_insert AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts (rowid, name, qualname, signature, docstring, path)
    VALUES (new.pk, new.name, new.qualname, new.signature, new.docstring, new.path);
END;
CREATE TRIGGER IF NOT EXISTS nodes_fts_delete AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts (nodes_fts, rowid, name, qualname, signature, docstring, path)
    VALUES ('delete', old.pk, old.name, old.qualname, old.signature, old.docstring,
            old.path);
END;
CREATE TRIGGER IF NOT EXISTS nodes_fts_update AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts (nodes_fts, rowid, name, qualname, signature, docstring, path)
    VALUES ('delete', old.pk, old.name, old.qualname, old.signature, old.docstring,
            old.path);
    INSERT INTO nodes_fts (rowid, name, qualname, signature, docstring, path)
    VALUES (new.pk, new.name, new.qualname, new.signature, new.docstring, new.path);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    node_id TEXT NOT NULL,
    model   TEXT NOT NULL,
    dim     INTEGER NOT NULL,
    vector  BLOB NOT NULL,
    PRIMARY KEY (node_id, model)
);
"""


def ensure_fts5() -> None:
    """Fail early and clearly if this Python's SQLite was built without FTS5."""
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE probe USING fts5 (x)")
    except sqlite3.OperationalError as exc:
        raise StoreError(
            f"SQLite {sqlite3.sqlite_version} has no FTS5 module, which CodeAtlas needs "
            "for text search. Use a Python build whose SQLite includes FTS5."
        ) from exc
    finally:
        probe.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the tables in a new database, or check an existing one's version."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if has_meta:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        found = row[0] if row else None
        if found != SCHEMA_VERSION:
            raise StoreError(
                f"This index uses store schema version {found!r}, but this CodeAtlas "
                f"expects {SCHEMA_VERSION!r}. Delete the database file and re-index."
            )
    conn.executescript(DDL)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
