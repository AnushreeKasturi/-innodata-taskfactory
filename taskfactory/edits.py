"""Apply search/replace edits (the format the model writes) to a checkout."""
from __future__ import annotations

from pathlib import Path, PurePosixPath


class EditError(ValueError):
    pass


def _safe_path(root: Path, rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel or ".." in PurePosixPath(rel).parts:
        raise EditError(f"invalid path {rel!r}")
    return root / rel


def apply_edits(root: Path, edits: list[dict]) -> None:
    """Each edit is {path, search, replace}. An empty `search` creates a new file
    (or overwrites one when `overwrite` is true). Otherwise `search` must occur exactly once."""
    for e in edits:
        path = e.get("path", "")
        target = _safe_path(root, path)
        search = (e.get("search") or "").replace("\r\n", "\n")
        replace = (e.get("replace") or "").replace("\r\n", "\n")
        if not search:
            if target.exists() and not e.get("overwrite"):
                raise EditError(f"{path}: file already exists; give a `search` block to edit it")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(replace.encode("utf-8"))
            continue
        if not target.exists():
            raise EditError(f"{path}: file does not exist (use an empty `search` to create it)")
        text = target.read_bytes().decode("utf-8")
        if "\r\n" in text:
            search, replace = search.replace("\n", "\r\n"), replace.replace("\n", "\r\n")
        count = text.count(search)
        if count == 0:
            stripped = search.strip("\r\n")
            if stripped and text.count(stripped) == 1:
                search, replace = stripped, replace.strip("\r\n")
                count = 1
        if count == 0:
            raise EditError(f"{path}: search block not found. It must be copied exactly from the file:\n{search[:400]}")
        if count > 1:
            raise EditError(f"{path}: search block matches {count} places; include more surrounding lines")
        target.write_bytes(text.replace(search, replace, 1).encode("utf-8"))
