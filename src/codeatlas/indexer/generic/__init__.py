"""Language-independent adapters: tags-query extraction for any grammar, and the text tier."""

from codeatlas.indexer.generic.tags import TagsAdapter
from codeatlas.indexer.generic.text import TextAdapter

__all__ = ["TagsAdapter", "TextAdapter"]
