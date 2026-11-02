"""One static manifest parser per ecosystem; each exposes `find(view) -> Found`."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from codeatlas.repo.ecosystems import dotnet, go, gradle, maven, npm, php, python, rust

# Order matters only for ties: when two packages share a root and neither matches a
# file's language, the earlier ecosystem owns the file.
ECOSYSTEMS: tuple[ModuleType, ...] = (npm, python, go, rust, maven, gradle, dotnet, php)

# How each ecosystem compares names; exact comparison where none is listed.
NORMALIZERS: dict[str, Callable[[str], str]] = {
    python.ECOSYSTEM: python.normalize,
    rust.ECOSYSTEM: rust.normalize,
    dotnet.ECOSYSTEM: dotnet.normalize,
    php.ECOSYSTEM: php.normalize,
}

# The languages a package's files are most likely in, used when a package root is shared.
# The first one names a package's language when it holds no parsed files.
LANGUAGES: dict[str, tuple[str, ...]] = {
    npm.ECOSYSTEM: ("javascript", "typescript", "tsx"),
    python.ECOSYSTEM: ("python",),
    go.ECOSYSTEM: ("go",),
    rust.ECOSYSTEM: ("rust",),
    maven.ECOSYSTEM: ("java", "kotlin", "scala"),
    gradle.ECOSYSTEM: ("java", "kotlin", "scala"),
    dotnet.ECOSYSTEM: ("c_sharp",),
    php.ECOSYSTEM: ("php",),
}


def normalize(ecosystem: str, name: str) -> str:
    return NORMALIZERS.get(ecosystem, str)(name)
