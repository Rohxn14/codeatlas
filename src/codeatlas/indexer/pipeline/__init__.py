"""The pipeline: turn a path or a GitHub URL into a stored graph.

`parse_source` does intake, discovery and parsing (what `codeatlas scan` shows);
`build_graph` adds containment, the repository layer, the registered resolvers and
linkers, and writes everything to a `GraphStore`.
"""

from codeatlas.indexer.pipeline.build import BuildResult, build_graph
from codeatlas.indexer.pipeline.parse import Parsed, parse_source

__all__ = ["BuildResult", "Parsed", "build_graph", "parse_source"]
