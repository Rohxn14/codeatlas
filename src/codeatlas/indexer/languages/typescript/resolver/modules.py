"""Turn an import specifier into a repository file, or decide it is external.

Order (decision D-19 for the last step): relative path, tsconfig `paths`, tsconfig
`baseUrl`, workspace package, otherwise external.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.indexer.languages.typescript.resolver import paths
from codeatlas.indexer.languages.typescript.resolver.tsconfig import PathRules, ReadFile
from codeatlas.models import NodeKind

_CONDITIONS = ("import", "default", "types", "require", "node")


@dataclass(frozen=True, slots=True)
class Target:
    """Where a specifier points: a repo `path`, an `external` name, or neither (a relative
    import of a file that is not in the repository)."""

    path: str | None = None
    external: str | None = None


class ModuleResolver:
    def __init__(
        self,
        files: set[str],
        rules: list[PathRules],
        index: SymbolIndex,
        read: ReadFile,
    ) -> None:
        self._files = files
        self._rules = sorted(rules, key=lambda r: -len(r.directory))
        self._index = index
        self._read = read
        self._cache: dict[tuple[str, str], Target] = {}

    def resolve(self, specifier: str, importer: str) -> Target:
        key = (specifier, paths.parent(importer))
        if key not in self._cache:
            self._cache[key] = self._resolve(specifier, importer)
        return self._cache[key]

    def find_file(self, base: str | None) -> str | None:
        if base is None:
            return None
        for candidate in paths.file_candidates(base):
            if candidate in self._files:
                return candidate
        return None

    def _resolve(self, specifier: str, importer: str) -> Target:
        if specifier.startswith("."):
            base = paths.join(paths.parent(importer), specifier)
            return Target(path=self.find_file(base))
        found = self._by_tsconfig(specifier, importer) or self._by_package(specifier)
        return Target(path=found) if found else Target(external=specifier)

    def _by_tsconfig(self, specifier: str, importer: str) -> str | None:
        rule = next((r for r in self._rules if paths.under(importer, r.directory)), None)
        if rule is None:
            return None
        for pattern in _matching_patterns(rule.mappings, specifier):
            captured = _capture(pattern, specifier)
            for template in rule.mappings[pattern]:
                found = self.find_file(paths.join(rule.paths_dir, template.replace("*", captured)))
                if found:
                    return found
        if rule.base_dir is not None:
            return self.find_file(paths.join(rule.base_dir, specifier))
        return None

    def _by_package(self, specifier: str) -> str | None:
        name, _, subpath = _split_package(specifier)
        for node in self._index.by_name(name):
            if node.kind is NodeKind.PACKAGE and node.name == name and _is_manifest(node.path):
                return self._package_file(paths.parent(node.path), subpath)
        return None

    def _package_file(self, root: str, subpath: str) -> str | None:
        manifest = self._manifest(root)
        if subpath:
            exported = _exports_entry(manifest.get("exports"), "./" + subpath)
            for target in (exported, subpath, "src/" + subpath):
                found = target and self.find_file(paths.join(root, target))
                if found:
                    return found
            return None
        entries = [
            _exports_entry(manifest.get("exports"), "."),
            manifest.get("module"),
            manifest.get("main"),
            manifest.get("types"),
        ]
        for entry in entries:
            if isinstance(entry, str):
                found = self.find_file(paths.join(root, entry))
                found = found or self._source_of_build(root, entry)
                if found:
                    return found
        return self.find_file(paths.join(root, "index")) or self.find_file(
            paths.join(root, "src/index")
        )

    def _source_of_build(self, root: str, entry: str) -> str | None:
        """`./dist/index.js` names build output that is not committed: try `src/index`."""
        parts = [p for p in entry.split("/") if p not in (".", "")]
        if len(parts) > 1 and parts[0] in ("dist", "lib", "build", "out"):
            stem = "/".join(["src", *parts[1:]]).rsplit(".", 1)[0]
            return self.find_file(paths.join(root, stem))
        return None

    def _manifest(self, root: str) -> dict[str, object]:
        data = self._read(paths.join(root, "package.json") or "package.json")
        if data is None:
            return {}
        try:
            parsed = json.loads(data.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _is_manifest(path: str) -> bool:
    return path.rsplit("/", 1)[-1] == "package.json"


def _split_package(specifier: str) -> tuple[str, str, str]:
    """`@acme/ui/button` -> (`@acme/ui`, `/`, `button`); `lodash` -> (`lodash`, ``, ``)."""
    parts = specifier.split("/")
    size = 2 if specifier.startswith("@") else 1
    return "/".join(parts[:size]), "/" if len(parts) > size else "", "/".join(parts[size:])


def _exports_entry(exports: object, key: str) -> str | None:
    """The file named for `key` in a package `exports` field (string, conditions, map)."""
    if isinstance(exports, str):
        return exports if key == "." else None
    if not isinstance(exports, dict):
        return None
    if any(k.startswith(".") for k in exports):
        return _condition(exports.get(key))
    return _condition(exports) if key == "." else None


def _condition(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for name in _CONDITIONS:
            found = _condition(value.get(name))
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _condition(item)
            if found:
                return found
    return None


def _matching_patterns(mappings: dict[str, list[str]], specifier: str) -> list[str]:
    """Exact keys first, then wildcard keys with the longest prefix."""
    if specifier in mappings:
        return [specifier]
    wild = [p for p in mappings if "*" in p and _capture(p, specifier) is not None]
    return sorted(wild, key=lambda p: -len(p.split("*")[0]))


def _capture(pattern: str, specifier: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == specifier else None
    prefix, _, suffix = pattern.partition("*")
    if specifier.startswith(prefix) and specifier.endswith(suffix) and len(specifier) >= len(
        prefix
    ) + len(suffix):
        return specifier[len(prefix) : len(specifier) - len(suffix)]
    return None
