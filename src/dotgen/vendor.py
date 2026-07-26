from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

GIT_ARTIFACTS = frozenset({".git", ".gitignore"})
NODE_ARTIFACTS = frozenset({"node_modules", "package-lock.json"})
PY_ARTIFACTS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "*.egg-info"})
BUILD_ARTIFACTS = frozenset({"dist", "build", "target", ".next"})


def _matches_any(candidates: Iterable[str], patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(candidate, pattern) for candidate in candidates for pattern in patterns)


@dataclass(frozen=True)
class VendorDir:
    """One source directory to vendor into ``dist/<env>/config/<dest>/``.

    ``exclude_dirs`` entries are fnmatch patterns tested against *every component* of a
    source-relative path, so an entry matches a directory at any depth (``node_modules``) and
    equally a bare file name or glob-shaped name at any depth (``.gitignore``, ``*.egg-info``).

    ``exclude_globs`` and ``include_globs`` are fnmatch patterns tested against *both* the POSIX
    relative path and the bare file name, so ``*.test.ts`` and ``package-lock.json`` match at any
    depth while ``dist/**`` matches only below that path.
    """

    source: Path
    dest: str
    exclude_dirs: frozenset[str] = frozenset()
    exclude_globs: tuple[str, ...] = ()
    include_globs: tuple[str, ...] = ()
    preserve_modes: bool = True

    def prunes_dir(self, name: str) -> bool:
        """Whether a directory name is pruned before descending into it."""
        return _matches_any((name,), self.exclude_dirs)

    def vendors_path(self, rel: PurePosixPath) -> bool:
        """Whether a source-relative file path is vendored.

        Deny rules apply first and also apply on top of allow-list mode: when ``include_globs``
        is non-empty only matching paths are vendored.
        """
        if _matches_any(rel.parts, self.exclude_dirs):
            return False
        targets = (rel.as_posix(), rel.name)
        if _matches_any(targets, self.exclude_globs):
            return False
        if self.include_globs:
            return _matches_any(targets, self.include_globs)
        return True
