"""Per-repository configuration (how to set up and run the target repo's tests)."""
from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_TEST_GLOBS = [
    "tests/*", "test/*", "spec/*", "__tests__/*",
    "*/tests/*", "*/test/*",
    "test_*.py", "*/test_*.py", "*_test.py", "*_test.go",
    "*.test.*", "*.spec.*", "*Test.java", "*Tests.java",
]


@dataclass
class RepoConfig:
    # Command that runs tests. Placeholders: {junit} = path for a JUnit XML report,
    # {tests} = space-separated test files (empty string means "whole suite").
    test_cmd: str
    # Optional command run once in each fresh checkout (install deps, build, ...).
    setup_cmd: str = ""
    test_globs: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_GLOBS))
    # Files never shown to the model or mutated (lockfiles, generated code, ...).
    exclude_globs: list[str] = field(default_factory=lambda: [
        "*.lock", "package-lock.json", "*.min.js", "*.png", "*.jpg", "*.gif", "*.ico", "*.pdf",
    ])
    timeout: int = 600
    # A task is rejected if its tests kill fewer than this share of mutants.
    mutation_threshold: float = 0.6
    max_mutants: int = 20

    def is_test(self, path: str) -> bool:
        p = path.replace("\\", "/")
        return any(fnmatch.fnmatch(p, g) for g in self.test_globs)

    def is_excluded(self, path: str) -> bool:
        p = path.replace("\\", "/")
        return any(fnmatch.fnmatch(p, g) for g in self.exclude_globs)


def load_config(path: Path) -> RepoConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    section = data.get("repo", data)
    known = {f.name for f in fields(RepoConfig)}
    unknown = set(section) - known
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    return RepoConfig(**section)
