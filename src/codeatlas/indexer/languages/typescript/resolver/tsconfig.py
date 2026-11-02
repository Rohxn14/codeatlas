"""tsconfig `baseUrl` and `paths`, with one level of `extends`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from codeatlas.indexer.languages.typescript.resolver import paths
from codeatlas.indexer.languages.typescript.resolver.jsonc import parse_jsonc

ReadFile = Callable[[str], bytes | None]
CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")


@dataclass(frozen=True, slots=True)
class PathRules:
    """What one config says about files under `directory`."""

    directory: str
    base_dir: str | None  # where `baseUrl` points
    paths_dir: str  # what the `paths` targets are relative to
    mappings: dict[str, list[str]] = field(default_factory=dict)


def load_rules(file_paths: list[str], read: ReadFile) -> tuple[list[PathRules], list[str]]:
    """Rules from every tsconfig in the repo, plus a report line for each config that
    could not be read. A broken config is reported, never fatal."""
    rules: list[PathRules] = []
    problems: list[str] = []
    for path in sorted(p for p in file_paths if p.rsplit("/", 1)[-1] in CONFIG_NAMES):
        try:
            rule = _rules_for(path, read)
        except (ValueError, OSError) as exc:
            problems.append(f"{path}: not read ({exc})")
            continue
        if rule is not None:
            rules.append(rule)
    return rules, problems


def _rules_for(path: str, read: ReadFile) -> PathRules | None:
    directory = paths.parent(path)
    own = _options(path, read)
    inherited: dict[str, object] = {}
    inherited_dir = directory
    for parent_path in _extends(own, directory):
        try:
            parent_options = _options(parent_path, read)
        except (ValueError, OSError):
            continue  # a missing or broken parent only loses its settings
        inherited = {**inherited, **{k: v for k, v in _compiler(parent_options).items()}}
        inherited_dir = paths.parent(parent_path)
    compiler = _compiler(own)
    base_url, base_owner = _pick("baseUrl", compiler, directory, inherited, inherited_dir)
    path_map, paths_owner = _pick("paths", compiler, directory, inherited, inherited_dir)
    if base_url is None and not path_map:
        return None
    base_dir = paths.join(base_owner, str(base_url)) if base_url is not None else None
    paths_dir = base_dir if base_dir is not None else paths_owner
    mappings = {}
    if isinstance(path_map, dict):
        mappings = {
            k: [str(t) for t in v] for k, v in path_map.items() if isinstance(v, list)
        }
    return PathRules(directory, base_dir, paths_dir, mappings)


def _pick(
    key: str, own: dict[str, object], own_dir: str, parent: dict[str, object], parent_dir: str
) -> tuple[object | None, str]:
    """The child's setting wins; a setting remembers the folder of the config that wrote it."""
    if key in own:
        return own[key], own_dir
    return parent.get(key), parent_dir


def _options(path: str, read: ReadFile) -> dict[str, object]:
    data = read(path)
    if data is None:
        raise OSError("file not readable")
    parsed = parse_jsonc(data.decode("utf-8", errors="replace"))
    if not isinstance(parsed, dict):
        raise ValueError("top level is not an object")
    return parsed


def _compiler(options: dict[str, object]) -> dict[str, object]:
    compiler = options.get("compilerOptions")
    return compiler if isinstance(compiler, dict) else {}


def _extends(options: dict[str, object], directory: str) -> list[str]:
    """Repo paths of relative `extends` targets; a package name is out of reach."""
    raw = options.get("extends")
    names = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    found: list[str] = []
    for name in names:
        if isinstance(name, str) and name.startswith("."):
            target = paths.join(directory, name if name.endswith(".json") else name + ".json")
            if target is not None:
                found.append(target)
    return found
