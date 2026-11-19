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
    # Interpreter substituted for {python} in commands. "auto" = the target repo's .venv if it has one.
    python: str = "python"
    # Extra environment variables for setup/test commands (e.g. PYTHONPATH = "src").
    env: dict[str, str] = field(default_factory=dict)
    # How per-test results are read: "junit" ({junit} report) or "pytest" (pytest -rA summary,
    # giving node ids like tests/test_x.py::test_y -- the vocabulary Harbor graders expect).
    parser: str = "junit"
    # A ref in the repo that tracks live upstream (e.g. "origin/main"). Tasks whose new
    # functions/classes already exist there are rejected as not novel.
    upstream_ref: str = ""
    # Curated regression set: existing tests from the N test files most related to the feature.
    p2p_files: int = 3
    p2p_max: int = 250

    def is_test(self, path: str) -> bool:
        p = path.replace("\\", "/")
        return any(fnmatch.fnmatch(p, g) for g in self.test_globs)

    def is_excluded(self, path: str) -> bool:
        p = path.replace("\\", "/")
        return any(fnmatch.fnmatch(p, g) for g in self.exclude_globs)


@dataclass
class HarborConfig:
    """How to export validated tasks as Harbor packages (see taskfactory/harbor.py)."""
    source_repo: str            # org/repo, e.g. "pallets/click"
    clone_url: str
    license: str
    programming_language: str
    instance_prefix: str        # e.g. "pallets__click"
    base_image: str = "python:3.12-slim-bookworm"
    # Shell run inside /app after the repo is cloned; must leave a working test toolchain.
    install_cmd: str = 'python -m venv /app/.venv && /app/.venv/bin/pip install -e . "pytest==9.2.0"'
    # Command run_script.sh uses; "{files}" is replaced by the graded test files that exist.
    run_cmd: str = ('/app/.venv/bin/python -m pytest {files} -rA --tb=short -p no:cacheprovider '
                    '--color=no --continue-on-collection-errors')
    agent_timeout_sec: float = 3600.0
    verifier_timeout_sec: float = 1800.0
    cpus: int = 2
    memory_mb: int = 4096


def _section(data: dict, name: str, cls, path: Path):
    section = data.get(name, {})
    known = {f.name for f in fields(cls)}
    unknown = set(section) - known
    if unknown:
        raise ValueError(f"{path}: unknown keys in [{name}]: {sorted(unknown)}")
    return cls(**section)


def load_config(path: Path, repo: Path | None = None) -> RepoConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    cfg = _section(data if "repo" in data else {"repo": data}, "repo", RepoConfig, path)
    if cfg.python == "auto":
        cands = [repo / ".venv" / "Scripts" / "python.exe", repo / ".venv" / "bin" / "python"] if repo else []
        cfg.python = str(next((c.resolve() for c in cands if c.exists()), "python"))
    return cfg


def load_harbor_config(path: Path) -> HarborConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    if "harbor" not in data:
        raise ValueError(f"{path}: no [harbor] section")
    return _section(data, "harbor", HarborConfig, path)
