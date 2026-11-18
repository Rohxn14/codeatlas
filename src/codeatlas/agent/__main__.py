"""`python -m codeatlas.agent ask "..."` and `python -m codeatlas.agent mcp`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from codeatlas.config import load_config
from codeatlas.indexer.pipeline.build import default_db_path
from codeatlas.store import GraphStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m codeatlas.agent")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("ask", "answer a question about an indexed repository"),
                            ("mcp", "serve the tools over MCP on stdio")):
        p = sub.add_parser(name, help=help_text)
        if name == "ask":
            p.add_argument("question")
            p.add_argument("--max-steps", type=int, default=20)
        p.add_argument("--db", type=Path, default=None,
                       help="store file (default: <data_dir>/codeatlas.db)")
        p.add_argument("--snapshot", default=None,
                       help="snapshot id (default: the most recently indexed)")
    return parser


def _open(db: Path | None, snapshot: str | None) -> tuple[GraphStore, str]:
    """Open the store and pick a snapshot, with a clear message when there is none."""
    config = load_config()
    # The same file `codeatlas index` writes; this said codeatlas.sqlite before Nov 17.
    path = db or default_db_path(config)
    if not path.is_file():
        raise SystemExit(f"no store at {path}; index a repository first or pass --db")
    store = GraphStore(path)
    if snapshot is None:
        snapshot = latest_snapshot_id(store)
    if store.get_snapshot(snapshot) is None:
        store.close()
        raise SystemExit(f"no snapshot {snapshot!r} in {path}")
    return store, snapshot


def latest_snapshot_id(store: GraphStore) -> str:
    """The most recently indexed snapshot of any repository."""
    rows = store._conn.execute(  # noqa: SLF001 - no public "latest of all" lookup exists
        "SELECT id FROM snapshots ORDER BY indexed_at DESC, rowid DESC LIMIT 1").fetchall()
    if not rows:
        raise SystemExit("the store has no snapshots; index a repository first")
    return rows[0]["id"]


def _ask(args: argparse.Namespace) -> int:
    from codeatlas.agent.loop import ask
    from codeatlas.llm import LLMClient, LLMError

    store, snapshot_id = _open(args.db, args.snapshot)
    try:
        with store:
            answer = ask(args.question, store, snapshot_id, LLMClient.from_config(),
                         max_steps=args.max_steps, config=load_config())
    except LLMError as exc:  # the trajectory so far is already on disk
        print(f"The language model could not be reached: {exc}", file=sys.stderr)
        return 1
    print(answer.text)
    print("\nCitations:")
    for c in answer.citations or []:
        print(f"  {'ok     ' if c.valid else 'INVALID'} {c.text}" + ("" if c.valid
                                                                    else f"  ({c.reason})"))
    if not answer.citations:
        print("  none")
    print(f"\nSteps: {answer.steps}  tokens in/out: {answer.input_tokens}/{answer.output_tokens}")
    print(f"Trajectory: {answer.trajectory_path}")
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from codeatlas.agent.mcp_server import serve_stdio
    from codeatlas.agent.tools import ToolSet

    store, snapshot_id = _open(args.db, args.snapshot)
    print(f"codeatlas MCP server on stdio, snapshot {snapshot_id}", file=sys.stderr)
    with store:
        asyncio.run(serve_stdio(ToolSet(store, snapshot_id, load_config())))
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:  # a real command line, not a test: read the keys from ./.env
        from codeatlas.envfile import load_env_file

        load_env_file()
    args = _parser().parse_args(argv)
    return _ask(args) if args.command == "ask" else _mcp(args)


if __name__ == "__main__":
    raise SystemExit(main())
