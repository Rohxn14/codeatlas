"""The contract's SymbolIndex, answered from one snapshot in the store."""

from typing import TYPE_CHECKING

from codeatlas.models import FileRecord, Node, make_node_id

if TYPE_CHECKING:
    from codeatlas.store.sqlite import GraphStore


class StoreSymbolIndex:
    """Read-only lookups for resolvers and linkers, scoped to one snapshot.

    Each call is an indexed SQL query, so a resolver can look up thousands of names
    without loading the whole snapshot into memory.
    """

    def __init__(self, store: "GraphStore", snapshot_id: str) -> None:
        self._store = store
        self.snapshot_id = snapshot_id

    def by_key(self, key: str) -> Node | None:
        return self._store.node(make_node_id(self.snapshot_id, key))

    def by_name(self, name: str, language: str | None = None) -> list[Node]:
        return self._store.nodes_by_name(self.snapshot_id, name, language)

    def module_for_path(self, path: str) -> Node | None:
        return self._store.module_for_path(self.snapshot_id, path)

    def members(self, class_key: str) -> list[Node]:
        return self._store.members(self.snapshot_id, class_key)

    def files(self) -> list[FileRecord]:
        return self._store.files(self.snapshot_id)
