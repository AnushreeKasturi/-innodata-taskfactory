"""Turn a draft (requirements + edits) into patches, and write task packages to disk.

Package layout (until the organisers' task interface is published):
  <out>/<task-id>/
      task.json          metadata: base commit, fail_to_pass / pass_to_pass test ids, test command, provenance
      requirements.md    what the solver sees
      reference.patch    reference implementation (source files only)
      tests.patch        hidden feature tests (test files only)
      validation.json    full evidence from validate()
      draft.json         the raw draft the patches were built from
Rejected drafts go to <out>/_rejected/<task-id>/ with their validation report.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .config import RepoConfig
from .edits import EditError, apply_edits
from .gitutil import staged_diff, worktree


def build_patches(repo: Path, cfg: RepoConfig, base: str, draft: dict) -> tuple[str, str]:
    src_edits = draft.get("source_edits") or []
    test_edits = draft.get("test_edits") or []
    misplaced = [e["path"] for e in src_edits if cfg.is_test(e["path"])]
    misplaced += [e["path"] for e in test_edits if not cfg.is_test(e["path"])]
    if misplaced:
        raise EditError(f"source_edits must not touch test files and test_edits must only touch test files "
                        f"(test files match {cfg.test_globs}); misplaced: {misplaced}")
    if not src_edits or not test_edits:
        raise EditError("draft needs both source_edits and test_edits")
    with worktree(repo, base) as wt:
        apply_edits(wt, src_edits)
        apply_edits(wt, test_edits)
        src = staged_diff(wt, list(dict.fromkeys(e["path"] for e in src_edits)))
        tests = staged_diff(wt, list(dict.fromkeys(e["path"] for e in test_edits)))
    if not src.strip() or not tests.strip():
        raise EditError("edits produced an empty diff")
    return src, tests


def task_id(title: str, src: str, tests: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "task"
    return f"{slug}-{hashlib.sha1((src + tests).encode()).hexdigest()[:8]}"


def write_package(out: Path, *, repo_id: str, cfg: RepoConfig, base: str, draft: dict,
                  src: str, tests: str, report: dict, provenance: dict) -> Path:
    tid = task_id(draft.get("title", "task"), src, tests)
    d = (out if report["valid"] else out / "_rejected") / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "requirements.md").write_bytes(draft["requirements"].replace("\r\n", "\n").encode("utf-8"))
    (d / "reference.patch").write_bytes(src.encode("utf-8"))
    (d / "tests.patch").write_bytes(tests.encode("utf-8"))
    (d / "draft.json").write_text(json.dumps(draft, indent=2), encoding="utf-8")
    (d / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    meta = {
        "id": tid,
        "title": draft.get("title"),
        "category": draft.get("category"),
        "axes": draft.get("axes") or {},
        "repo": repo_id,
        "base_commit": base,
        "requirements": "requirements.md",
        "reference_patch": "reference.patch",
        "test_patch": "tests.patch",
        "test_files": report["test_files"],
        "source_files": report["source_files"],
        "fail_to_pass": report["fail_to_pass"],
        "pass_to_pass": report["pass_to_pass"],
        "test_cmd": cfg.test_cmd,
        "setup_cmd": cfg.setup_cmd,
        "valid": report["valid"],
        "mutation_score": report["mutation"]["score"],
        "warnings": [c["name"] for c in report["checks"] if not c["ok"] and c["severity"] == "warning"],
        "provenance": {**provenance, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
    }
    (d / "task.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return d


def load_package(d: Path) -> tuple[dict, str, str, str]:
    meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
    read = lambda name: (d / name).read_bytes().decode("utf-8")
    return meta, read(meta["requirements"]), read(meta["reference_patch"]), read(meta["test_patch"])
