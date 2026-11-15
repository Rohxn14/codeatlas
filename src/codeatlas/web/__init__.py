"""The local web app behind `codeatlas serve` (docs/explainers/web-app.md)."""

from codeatlas.web.app import create_app, find_snapshot, snapshot_slug

__all__ = ["create_app", "find_snapshot", "snapshot_slug"]
