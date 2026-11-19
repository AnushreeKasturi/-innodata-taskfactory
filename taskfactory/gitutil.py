"""Thin git helpers. Everything runs on bytes so patches survive Windows newline handling."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "advice.detachedHead=false"]


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, *, check: bool = True, input: str | None = None) -> str:
    p = subprocess.run(
        GIT + list(args),
        cwd=cwd,
        input=input.encode("utf-8") if input is not None else None,
        capture_output=True,
    )
    out = p.stdout.decode("utf-8", "replace")
    if check and p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args[:3])} failed: {err}")
    return out


def rev_parse(repo: Path, rev: str = "HEAD") -> str:
    return git(["rev-parse", "--verify", f"{rev}^{{commit}}"], repo).strip()


def repo_identity(repo: Path) -> str:
    url = git(["config", "--get", "remote.origin.url"], repo, check=False).strip()
    return url or Path(repo).resolve().name


@contextmanager
def worktree(repo: Path, commit: str) -> Iterator[Path]:
    """A throwaway detached checkout of `commit`."""
    tmp = Path(tempfile.mkdtemp(prefix="tfwt-"))
    path = tmp / "wt"
    git(["worktree", "add", "--detach", "--quiet", str(path), commit], repo)
    try:
        yield path
    finally:
        git(["worktree", "remove", "--force", str(path)], repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
        git(["worktree", "prune"], repo, check=False)


def apply_patch(wt: Path, patch: str) -> None:
    if patch.strip():
        git(["apply", "--whitespace=nowarn", "-"], wt, input=patch)


def staged_diff(wt: Path, paths: list[str]) -> str:
    if not paths:
        return ""
    git(["add", "-A", "--", *paths], wt)
    return git(["diff", "--cached", "--binary", "--", *paths], wt)


def patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for a, b in re.findall(r"^diff --git a/(\S+) b/(\S+)$", patch, re.M):
        for p in (a, b):
            if p not in paths:
                paths.append(p)
    return paths


def added_lines(patch: str) -> list[str]:
    return [l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]


def show(repo: Path, commit: str, path: str) -> str | None:
    try:
        return git(["show", f"{commit}:{path}"], repo)
    except GitError:
        return None


def ls_files(repo: Path, commit: str) -> list[str]:
    return [l for l in git(["ls-tree", "-r", "--name-only", commit], repo).splitlines() if l]


def word_in_tree(repo: Path, commit: str, word: str) -> bool:
    p = subprocess.run(GIT + ["grep", "-q", "-w", "-F", "-e", word, commit], cwd=repo, capture_output=True)
    return p.returncode == 0
