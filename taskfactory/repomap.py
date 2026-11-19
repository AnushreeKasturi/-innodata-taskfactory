"""Compact view of a repository for prompting: file tree, code outlines, chosen files in full."""
from __future__ import annotations

import ast
from pathlib import Path

from .config import RepoConfig
from .gitutil import ls_files, show

CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rb", ".rs", ".cs", ".php", ".c", ".cpp", ".h", ".swift")


def _py_outline(text: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "\n".join(text.splitlines()[:40])

    def sig(fn: ast.FunctionDef | ast.AsyncFunctionDef, indent: str) -> str:
        ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
        deco = "".join(f"{indent}@{ast.unparse(d)}\n" for d in fn.decorator_list)
        doc = ast.get_docstring(fn)
        doc = f'  # {doc.splitlines()[0][:80]}' if doc else ""
        return f"{deco}{indent}def {fn.name}({ast.unparse(fn.args)}){ret}: ...{doc}"

    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(ast.unparse(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(sig(node, ""))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            out.append("".join(f"@{ast.unparse(d)}\n" for d in node.decorator_list) + f"class {node.name}({bases}):")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(sig(item, "    "))
                elif isinstance(item, (ast.AnnAssign, ast.Assign)):
                    out.append("    " + ast.unparse(item)[:120])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.append(ast.unparse(node)[:160])
    return "\n".join(out)


def outline(path: str, text: str) -> str:
    if path.endswith(".py"):
        return _py_outline(text)
    return "\n".join(text.splitlines()[:40])


def build_repo_map(repo: Path, base: str, cfg: RepoConfig, budget: int = 24_000) -> str:
    files = [f for f in ls_files(repo, base) if not cfg.is_excluded(f)]
    parts = ["## File tree", "\n".join(files[:400])]
    used = len(parts[1])
    for f in files:
        if cfg.is_test(f) or not f.endswith(CODE_EXT):
            continue
        text = show(repo, base, f) or ""
        block = f"\n## {f} (outline)\n{outline(f, text)}"
        if used + len(block) > budget:
            parts.append(f"\n(outline budget reached; {f} and later files omitted)")
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def read_files(repo: Path, base: str, paths: list[str], budget: int = 40_000) -> str:
    out, used = [], 0
    for p in dict.fromkeys(paths):
        text = show(repo, base, p)
        if text is None:
            out.append(f"\n### {p}\n(does not exist yet)")
            continue
        if used + len(text) > budget:
            out.append(f"\n### {p}\n(omitted: context budget reached)")
            continue
        out.append(f"\n### {p}\n```\n{text}\n```")
        used += len(text)
    return "\n".join(out)


def example_tests(repo: Path, base: str, cfg: RepoConfig, budget: int = 6_000) -> str:
    files = [f for f in ls_files(repo, base) if cfg.is_test(f) and f.endswith(CODE_EXT)]
    return read_files(repo, base, files[:3], budget) if files else "(repository has no tests)"
