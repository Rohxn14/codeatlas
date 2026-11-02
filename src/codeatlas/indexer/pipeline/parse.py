"""Intake, discovery and parsing of one source: the part `codeatlas scan` reports on."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from codeatlas import __version__
from codeatlas.config import Config, Deadline
from codeatlas.indexer.discover import TEXT_LANGUAGE, Discovery, discover
from codeatlas.indexer.generic.adapter import TextAdapter, module_node
from codeatlas.indexer.intake import IntakeResult, open_source
from codeatlas.indexer.registry import Registry
from codeatlas.models import FileRecord, ParseResult, Snapshot, Tier, make_snapshot_id

UNKNOWN_TYPE_REASON = "unknown file type: no language matches this file name or extension"


@dataclass(slots=True)
class Parsed:
    """Everything parsing learned, before anything is resolved or stored."""

    intake: IntakeResult
    discovery: Discovery
    snapshot: Snapshot
    results: dict[str, ParseResult]  # path -> result, in discovery order


def parse_source(source: str, config: Config, registry: Registry | None = None) -> Parsed:
    """Intake, discovery and parsing of one source, stopping at the configured limits.

    A file the deadline cuts off still gets a module node carrying the reason, so no
    file vanishes from the graph.
    """
    registry = registry or Registry()
    intake = open_source(source, config)
    # The limit covers indexing only: a slow clone must not use up the parse budget.
    deadline = Deadline(config.max_seconds)
    discovery = discover(intake.root, config, registry.tier_for, deadline)
    sha = intake.commit_sha or content_sha(discovery.files)
    snapshot_id = make_snapshot_id(intake.repo, sha)
    results: dict[str, ParseResult] = {}
    limits = set(discovery.limits_hit)
    for record in discovery.files:
        reason = discovery.skip_reasons.get(record.path)
        if reason is None and deadline.expired():
            limits.add("max_seconds")
            reason = "not parsed: the max_seconds limit was reached"
        results[record.path] = (
            skipped_result(record, reason, snapshot_id)
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
    return Parsed(intake, discovery, snapshot, results)


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


def skipped_result(record: FileRecord, reason: str, snapshot_id: str) -> ParseResult:
    """A TEXT-tier module node for a file that is not parsed, carrying the reason."""
    module = module_node(record.path, record.language, b"", snapshot_id, {"skipped_reason": reason})
    return ParseResult(record.path, record.language, Tier.TEXT, (module,))


def content_sha(files: Sequence[FileRecord]) -> str:
    """A stand-in commit SHA for a folder outside git: a hash of every file's hash."""
    digest = hashlib.sha1(usedforsecurity=False)
    for record in files:
        digest.update(f"{record.path}\0{record.sha256}\n".encode())
    return digest.hexdigest()
