"""Create the stand-in `shopcart` repository used until the organisers publish theirs."""
from __future__ import annotations

import shutil
from pathlib import Path

from .gitutil import git

SRC = Path(__file__).resolve().parent.parent / "examples" / "shopcart"


def init_sample(dest: Path) -> Path:
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git(["init", "-q", "-b", "main"], dest)
    git(["add", "-A"], dest)
    git(["-c", "user.name=taskfactory", "-c", "user.email=taskfactory@example.invalid",
         "commit", "-q", "-m", "shopcart baseline"], dest)
    return dest
