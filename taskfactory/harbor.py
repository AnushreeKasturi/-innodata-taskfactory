"""Export validated tasks as Harbor task packages (the organisers' Track 1 interface).

  <instance_id>/
    task.toml, instruction.md
    solution/solve.sh, solution/patch.diff
    tests/test.sh, grade.py, parser.py, run_script.sh, test_patch.diff, fail_to_pass.json, pass_to_pass.json
    environment/Dockerfile          (self-contained: clone upstream at base_commit, fresh git tree, toolchain)

grade.py / parser.py / test.sh / solve.sh are the organisers' reference files, shipped unchanged.
"""
from __future__ import annotations

import json
import re
import shutil
from importlib import resources
from pathlib import Path

from .config import HarborConfig
from .package import load_package

TEMPLATES = ("grade.py", "parser.py", "test.sh")


def _template(name: str) -> str:
    return resources.files("taskfactory.harbor_templates").joinpath(name).read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def instance_id(hcfg: HarborConfig, meta: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("title") or "task").lower()).strip("-")[:40].strip("-")
    return f"{hcfg.instance_prefix}-{slug}-{meta['id'][-6:]}"


def task_toml(hcfg: HarborConfig, iid: str, meta: dict) -> str:
    return f'''[metadata]
name = "{iid}"
instance_id = "{iid}"
task = "swe-feature-implementation"
source_repo = "{hcfg.source_repo}"
base_commit = "{meta['base_commit']}"
license = "{hcfg.license}"
language = "en"
programming_language = "{hcfg.programming_language}"
category = "{meta.get('category') or 'feature'}"

[environment]
docker_image = ""
build_timeout_sec = 3600.0
cpus = {hcfg.cpus}
memory_mb = {hcfg.memory_mb}
workdir = "/app"
network_mode = "no-network"

[agent]
timeout_sec = {hcfg.agent_timeout_sec}

[verifier]
environment_mode = "shared"
timeout_sec = {hcfg.verifier_timeout_sec}

[rollout_baseline.oracle]
reward = 1.0

[rollout_baseline.nop]
reward = 0.0
'''


def dockerfile(hcfg: HarborConfig, base_commit: str) -> str:
    return f'''FROM {hcfg.base_image}
ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates bash && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Upstream at the pinned base commit. History is dropped so later commits are not visible to the solver.
RUN git clone --quiet {hcfg.clone_url} /tmp/upstream \\
    && git -C /tmp/upstream checkout --quiet {base_commit} \\
    && cp -a /tmp/upstream/. /app/ && rm -rf /app/.git /tmp/upstream

# /app must be a git working tree so solve.sh and the grader can `git apply`.
RUN git init --quiet \\
    && git config user.email bench@local && git config user.name bench \\
    && git config core.autocrlf false \\
    && git add -A && git commit --quiet -m "base state" \\
    && git config --global --add safe.directory /app

RUN {hcfg.install_cmd}
CMD ["/bin/bash"]
'''


def run_script(hcfg: HarborConfig, files: list[str]) -> str:
    listed = "\n".join(f'  "{f}"' for f in files)
    cmd = hcfg.run_cmd.replace("{files}", '"${PRESENT[@]}"')
    return f'''#!/usr/bin/env bash
# Run the graded tests. Only files present in the tree are passed, so the feature-absent (nop)
# state still runs the regression files. Not `set -e`: the runner exits non-zero when tests fail.
set -uo pipefail
cd /app
ALL=(
{listed}
)
PRESENT=()
for f in "${{ALL[@]}}"; do [ -e "$f" ] && PRESENT+=("$f"); done
[ "${{#PRESENT[@]}}" -eq 0 ] && {{ echo "no graded test files present"; exit 0; }}
{cmd}
'''


SOLVE = '''#!/bin/bash
# Oracle: apply the reference implementation.
set -e
git -C /app apply --whitespace=nowarn "$(dirname "$0")/patch.diff"
echo "gold applied to /app"
'''


def export_task(pkg_dir: Path, hcfg: HarborConfig, dest: Path) -> Path:
    meta, requirements, src_patch, test_patch = load_package(pkg_dir)
    if not meta.get("valid"):
        raise ValueError(f"{pkg_dir}: package did not pass validation; refusing to export")
    f2p, p2p = meta["fail_to_pass"], meta["pass_to_pass"]
    if not all("::" in t for t in f2p + p2p):
        raise ValueError(f"{pkg_dir}: test ids are not runner node ids; validate with parser = \"pytest\"")
    iid = instance_id(hcfg, meta)
    d = dest / iid
    if d.exists():
        shutil.rmtree(d)
    files = sorted({t.split("::")[0] for t in f2p + p2p})
    _write(d / "task.toml", task_toml(hcfg, iid, meta))
    _write(d / "instruction.md", requirements.strip() + "\n")
    _write(d / "solution" / "patch.diff", src_patch)
    _write(d / "solution" / "solve.sh", SOLVE)
    _write(d / "tests" / "test_patch.diff", test_patch)
    _write(d / "tests" / "run_script.sh", run_script(hcfg, files))
    _write(d / "tests" / "fail_to_pass.json", json.dumps(f2p, indent=2) + "\n")
    _write(d / "tests" / "pass_to_pass.json", json.dumps(p2p, indent=2) + "\n")
    for name in TEMPLATES:
        _write(d / "tests" / name, _template(name))
    _write(d / "environment" / "Dockerfile", dockerfile(hcfg, meta["base_commit"]))
    return d


def pipeline_run(tasks_dir: Path, exported: dict[str, Path], pipeline: str) -> dict:
    """pipeline_run.json rows (SUBMISSION.md 3b) from each package's recorded provenance."""
    rows = []
    for pkg, iid_dir in exported.items():
        meta = json.loads((tasks_dir / pkg / "task.json").read_text(encoding="utf-8"))
        prov = meta.get("provenance", {})
        rows.append({
            "instance_id": iid_dir.name,
            "model": prov.get("model", "none"),
            "wall_seconds": prov.get("wall_seconds", 0),
            "model_calls": prov.get("model_calls", 0),
            "attempts": prov.get("attempts", 1),
            "n_input_tokens": prov.get("n_input_tokens", 0),
            "n_output_tokens": prov.get("n_output_tokens", 0),
            "n_cache_tokens": prov.get("n_cache_tokens", 0),
        })
    return {"pipeline": pipeline, "tasks": rows}
