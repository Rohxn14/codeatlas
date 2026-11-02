"""`_signature` stops at the end of the header, so keys match the deep Python adapter."""

from codeatlas.indexer.registry import Registry
from codeatlas.models import NodeKind, ParseResult
from tests.indexer.structural.helpers import SNAPSHOT

SOURCE = '''\
class Shape:
    def label(self):  # first
        # a comment before the first statement
        return "a"

    def label(self, extra):
        # another comment
        return extra

    def area(
        self,  # the receiver
        scale,
    ):
        """Docs."""
        return scale


def render(x):
    # comment
    return x


def render(x, y):  # trailing
    return y
'''


def keys(result: ParseResult) -> list[str]:
    return [n.key for n in result.nodes if n.kind is not NodeKind.MODULE]


def test_deep_and_tags_adapters_give_the_same_keys() -> None:
    deep = Registry().adapter_for("python").parse("m.py", SOURCE.encode(), SNAPSHOT)
    tags = Registry(deep={}).adapter_for("python").parse("m.py", SOURCE.encode(), SNAPSHOT)
    assert deep.tier != tags.tier
    assert sorted(keys(deep)) == sorted(keys(tags))
    assert any("#" in key for key in keys(tags))  # the sample really repeats names


def test_editing_a_comment_does_not_change_a_key() -> None:
    edited = SOURCE.replace("# another comment", "# a different remark entirely")
    adapter = Registry(deep={}).adapter_for("python")
    before = adapter.parse("m.py", SOURCE.encode(), SNAPSHOT)
    after = adapter.parse("m.py", edited.encode(), SNAPSHOT)
    assert keys(before) == keys(after)


def test_signature_has_no_comments_and_no_semicolon() -> None:
    adapter = Registry(deep={}).adapter_for("python")
    result = adapter.parse("m.py", SOURCE.encode(), SNAPSHOT)
    signatures = {n.name: n.signature for n in result.nodes if n.name == "area"}
    assert signatures["area"] == "def area( self, scale, )"
    java = Registry(deep={}).adapter_for("java")
    iface = java.parse("I.java", b"interface I { void save(int a); }", SNAPSHOT)
    assert [n.signature for n in iface.nodes if n.name == "save"] == ["void save(int a)"]
