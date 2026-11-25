"""Intake, discovery and parsing of one source: the part `codeatlas scan` reports on."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codeatlas import __version__
from codeatlas.config import Config, Deadline
from codeatlas.indexer.discover import TEXT_LANGUAGE, Discovery, discover
from codeatlas.indexer.generic.adapter import TextAdapter, module_node, part_nodes
from codeatlas.indexer.intake import IntakeResult, open_source
from codeatlas.indexer.registry import Registry
from codeatlas.models import FileRecord, ParseResult, Snapshot, Tier, make_snapshot_id

UNKNOWN_TYPE_REASON = "unknown file type: no language matches this file name or extension"
# Called as `progress(step, detail)` when a step starts, so a caller that waits (the web
# app) can show where an index is. The step names are those of the report's `seconds`.
Progress = Callable[[str, str], None]
PARSE_REPORT_EVERY = 25
HEAD_BYTES = 1_000_000  # read of a text file too long to parse


def no_progress(step: str, detail: str) -> None:
    """The default: nobody is watching."""


@dataclass(slots=True)
class Parsed:
    """Everything parsing learned, before anything is resolved or stored."""

    intake: IntakeResult
    discovery: Discovery
    snapshot: Snapshot
    results: dict[str, ParseResult]  # path -> result, in discovery order
    seconds: dict[str, float] = field(default_factory=dict)  # intake, discover, parse


def parse_source(
    source: str,
    config: Config,
    registry: Registry | None = None,
    progress: Progress = no_progress,
) -> Parsed:
    """Intake, discovery and parsing of one source, stopping at the configured limits.

    A file the deadline cuts off still gets a module node carrying the reason, so no
    file vanishes from the graph.
    """
    registry = registry or Registry()
    started = time.perf_counter()
    progress("intake", "")
    intake = open_source(source, config)
    intake_done = time.perf_counter()
    progress("discover", "")
    # The limit covers indexing only: a slow clone must not use up the parse budget.
    deadline = Deadline(config.max_seconds)
    discovery = discover(intake.root, config, registry.tier_for, deadline)
    discover_done = time.perf_counter()
    sha = intake.commit_sha or content_sha(discovery.files)
    snapshot_id = make_snapshot_id(intake.repo, sha)
    results: dict[str, ParseResult] = {}
    limits = set(discovery.limits_hit)
    total = len(discovery.files)
    for done, record in enumerate(discovery.files):
        if done % PARSE_REPORT_EVERY == 0:
            progress("parse", f"{done:,} of {total:,} files")
        reason = discovery.skip_reasons.get(record.path)
        if reason is None and deadline.expired():
            limits.add("max_seconds")
            reason = "not parsed: the max_seconds limit was reached"
        results[record.path] = (
            skipped_result(record, reason, snapshot_id, _head(intake.root, record, reason))
            if reason
            else parse_file(intake, record, registry, snapshot_id)
        )
    snapshot = Snapshot(
        id=snapshot_id,
        repo=intake.repo,
        commit_sha=sha,
        indexed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        indexer_version=__version__,
        source=intake.source,
        limits_hit=tuple(sorted(limits)),
    )
    seconds = {
        "intake": intake_done - started,
        "discover": discover_done - intake_done,
        "parse": time.perf_counter() - discover_done,
    }
    return Parsed(intake, discovery, snapshot, results, seconds)


def parse_file(
    intake: IntakeResult, record: FileRecord, registry: Registry, snapshot_id: str
) -> ParseResult:
    adapter = (
        TextAdapter(TEXT_LANGUAGE, UNKNOWN_TYPE_REASON)
        if record.language == TEXT_LANGUAGE
        else registry.adapter_for(record.language)
    )
    try:
        source = intake.root.joinpath(*record.path.split("/")).read_bytes()
    except OSError as exc:
        return skipped_result(record, f"unreadable: {exc}", snapshot_id)
    return adapter.parse(record.path, source, snapshot_id)


def skipped_result(record: FileRecord, reason: str, snapshot_id: str,
                   head: bytes = b"") -> ParseResult:
    """A TEXT-tier module node for a file that is not parsed, carrying the reason.

    `head` is the start of a text file that is only too long: its text stays searchable.
    """
    attrs: dict[str, object] = {"skipped_reason": reason}
    parts = part_nodes(record.path, record.language, head.decode("utf-8", errors="replace"),
                       snapshot_id, attrs) if head else []
    module = module_node(record.path, record.language, head, snapshot_id, attrs)
    return ParseResult(record.path, record.language, Tier.TEXT, (module, *parts))


def _head(root: Path, record: FileRecord, reason: str | None) -> bytes:
    """The first megabyte of a text file over `max_file_bytes`; nothing for other reasons."""
    if reason is None or not reason.startswith("over max_file_bytes"):
        return b""
    try:
        with root.joinpath(*record.path.split("/")).open("rb") as handle:
            return handle.read(HEAD_BYTES)
    except OSError:
        return b""


def content_sha(files: Sequence[FileRecord]) -> str:
    """A stand-in commit SHA for a folder outside git: a hash of every file's hash."""
    digest = hashlib.sha1(usedforsecurity=False)
    for record in files:
        digest.update(f"{record.path}\0{record.sha256}\n".encode())
    return digest.hexdigest()
