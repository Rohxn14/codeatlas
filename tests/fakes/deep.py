"""A fake deep adapter, to check that deep adapters take precedence."""

from codeatlas.indexer.generic.adapter import module_node
from codeatlas.models import ParseResult, Tier


class FakeDeepAdapter:
    language = "go"
    tier = Tier.DEEP
    extensions = (".go",)

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        module = module_node(path, "go", source, snapshot_id)
        return ParseResult(path, self.language, self.tier, (module,))


class NotAnAdapter:
    pass
