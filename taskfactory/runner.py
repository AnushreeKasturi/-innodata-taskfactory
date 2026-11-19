"""Run the target repository's tests and read per-test outcomes from JUnit XML."""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import RepoConfig

PASS, FAIL, SKIP = "pass", "fail", "skip"


@dataclass
class RunResult:
    outcomes: dict[str, str]
    crashed: bool  # timed out, or produced no parseable results
    returncode: int | None
    duration: float
    log: str

    def passed(self, test_id: str) -> bool:
        return self.outcomes.get(test_id) == PASS

    def summary(self) -> dict:
        counts = {PASS: 0, FAIL: 0, SKIP: 0}
        for o in self.outcomes.values():
            counts[o] += 1
        return {**counts, "crashed": self.crashed, "seconds": round(self.duration, 2)}


def _quote(arg: str) -> str:
    return subprocess.list2cmdline([arg]) if os.name == "nt" else shlex.quote(arg)


def _env(cfg: RepoConfig) -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", **cfg.env}


def run_setup(wt: Path, cfg: RepoConfig) -> None:
    if not cfg.setup_cmd:
        return
    p = subprocess.run(cfg.setup_cmd, shell=True, cwd=wt, capture_output=True, timeout=cfg.timeout, env=_env(cfg))
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).decode("utf-8", "replace")[-3000:]
        raise RuntimeError(f"setup_cmd failed ({p.returncode}):\n{tail}")


def run_tests(wt: Path, cfg: RepoConfig, tests: list[str] | None = None) -> RunResult:
    fd, junit = tempfile.mkstemp(prefix="tf-junit-", suffix=".xml")
    os.close(fd)
    os.unlink(junit)
    cmd = cfg.test_cmd.format(junit=_quote(junit), python=_quote(cfg.python),
                              tests=" ".join(_quote(t) for t in tests or []))
    start = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=wt, capture_output=True, timeout=cfg.timeout, env=_env(cfg))
        rc: int | None = p.returncode
        stdout, stderr = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rc, stdout, stderr = None, "", f"TIMEOUT after {cfg.timeout}s"
    duration = time.monotonic() - start
    if cfg.parser == "pytest":
        outcomes = parse_pytest_summary(stdout, stderr)
    else:
        outcomes = parse_junit(Path(junit)) if os.path.exists(junit) else {}
    if os.path.exists(junit):
        os.unlink(junit)
    log = stdout + stderr
    return RunResult(outcomes, rc is None or not outcomes, rc, duration, log[-6000:])


_PYTEST_STATUS = {"PASSED": PASS, "FAILED": FAIL, "ERROR": FAIL, "SKIPPED": SKIP}


def parse_pytest_summary(stdout: str, stderr: str) -> dict[str, str]:
    """Node ids from `pytest -rA`, using the exact parser shipped inside every Harbor package,
    so the ids we validate with are the ids the grader will look up."""
    from .harbor_templates.parser import parse_test_output
    out: dict[str, str] = {}
    for r in parse_test_output(stdout, stderr):
        status = _PYTEST_STATUS[r.status.name]
        if out.get(r.name) != FAIL:
            out[r.name] = status
    return out


def parse_junit(path: Path) -> dict[str, str]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for tc in root.iter("testcase"):
        cls, name = tc.get("classname", ""), tc.get("name", "")
        tid = f"{cls}::{name}" if cls else name
        if tc.find("failure") is not None or tc.find("error") is not None:
            status = FAIL
        elif tc.find("skipped") is not None:
            status = SKIP
        else:
            status = PASS
        if out.get(tid) != FAIL:  # a teardown error can add a second entry; keep the worst
            out[tid] = status
    return out
