
from ts_samples import parse_sample

from codeatlas.models import RawImport


def test_every_es_module_form() -> None:
    m = "web/imports.ts::"
    assert parse_sample("imports.ts").imports == (
        RawImport(m, "react", (("default", "React"),), line=1),
        RawImport(m, "react", (("useState", "useLocalState"), ("useEffect", None)), line=2),
        RawImport(m, "./api", alias="api", line=3),
        RawImport(m, "./styles.css", line=4),
        RawImport(m, "./mixed", (("default", "Default"), ("named", None)), line=5),
        RawImport(m, "./types", (("User", None),), line=6),
        RawImport(m, "./legacy", alias="legacy", line=7),
        RawImport(m, "./store", (("save", None), ("load", "fetchOne")), is_reexport=True, line=8),
        RawImport(m, "./models", is_reexport=True, line=9),
        RawImport(m, "./helpers", alias="helpers", is_reexport=True, line=10),
        RawImport(m, "./heavy", line=13),
    )


def test_commonjs_require() -> None:
    result = parse_sample("require.cjs")
    m = "web/require.cjs::"
    assert result.language == "javascript"
    assert result.imports == (
        RawImport(m, "express", alias="express", line=1),
        RawImport(m, "path", (("join", None), ("resolve", "resolvePath")), line=2),
        RawImport(m, "dotenv/config", line=3),
    )
    # A literal require is an import, not a call; `require(name)` stays a call.
    assert [(c.callee_text, c.line) for c in result.calls] == [("require", 4), ("join", 7)]


def test_commonjs_exports_mark_functions_exported() -> None:
    load = parse_sample("require.cjs").nodes[1]
    assert (load.key, load.attrs["exported"]) == ("web/require.cjs::load", True)


def test_unbound_requires_are_still_imports() -> None:
    """A literal require anywhere is a dependency, bound to a name or not."""
    from codeatlas.indexer.languages.typescript.adapter import JavaScriptAdapter

    source = b"""require("dotenv").config();
const log = require("debug")("app");
app.use(require("./routes"));
module.exports = require("./x");
const a = __importDefault(require("axios"));
"""
    result = JavaScriptAdapter().parse("a.js", source, "s@0")
    assert [(i.target, i.line) for i in result.imports] == [
        ("dotenv", 1), ("debug", 2), ("./routes", 3), ("./x", 4), ("axios", 5),
    ]
    assert all(i.alias is None and i.names == () for i in result.imports)
    assert "require" not in [c.name for c in result.calls]  # an import, not a call
