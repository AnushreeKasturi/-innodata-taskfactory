"""Mutants of a reference implementation, used to check that the feature tests catch wrong code.

Two kinds:
  * missing behaviour: revert one changed hunk back to the original code
  * wrong behaviour: flip one operator/constant on a line the reference added
Only lines the reference implementation touched are mutated, so mutants target the new feature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable

COMMENT = re.compile(r"^\s*(#|//|/\*|\*|--)")
# Lines where flipping a token only breaks the build, not the behaviour.
STRUCTURAL = re.compile(r"^\s*(@|import\b|from\s+\S+\s+import\b|#include\b|using\b|package\b|require\()")

Rep = str | Callable[[re.Match], str]
OPERATORS: list[tuple[str, re.Pattern, Rep]] = [
    ("<= -> <", re.compile(r"<="), "<"),
    (">= -> >", re.compile(r">="), ">"),
    ("< -> <=", re.compile(r"(?<![<>=!-])<(?![<=])"), "<="),
    ("> -> >=", re.compile(r"(?<![<>=!-])>(?![>=])"), ">="),
    ("== -> !=", re.compile(r"(?<![=!])==(?!=)"), "!="),
    ("!= -> ==", re.compile(r"!=(?!=)"), "=="),
    ("and -> or", re.compile(r"\band\b"), "or"),
    ("or -> and", re.compile(r"\bor\b"), "and"),
    ("&& -> ||", re.compile(r"&&"), "||"),
    ("|| -> &&", re.compile(r"\|\|"), "&&"),
    ("drop not", re.compile(r"\bnot\s+"), ""),
    ("True -> False", re.compile(r"\bTrue\b"), "False"),
    ("False -> True", re.compile(r"\bFalse\b"), "True"),
    ("true -> false", re.compile(r"\btrue\b"), "false"),
    ("false -> true", re.compile(r"\bfalse\b"), "true"),
    ("+ -> -", re.compile(r"(?<=\s)\+(?=\s)"), "-"),
    ("- -> +", re.compile(r"(?<=\s)-(?=\s)"), "+"),
    ("n -> n+1", re.compile(r"(?<![\w.])\d+(?![\w.])"), lambda m: str(int(m.group()) + 1)),
    ("min <-> max", re.compile(r"\b(min|max)(?=\()"), lambda m: "max" if m.group() == "min" else "min"),
]


@dataclass
class Mutant:
    kind: str  # "missing_behaviour" | "wrong_behaviour"
    description: str
    text: str


def _in_string(line: str, pos: int) -> bool:
    before = line[:pos]
    return before.count('"') % 2 == 1 or before.count("'") % 2 == 1


def _docstring_lines(lines: list[str]) -> set[int]:
    inside, out = False, set()
    for i, line in enumerate(lines):
        n = line.count('"""') + line.count("'''")
        if inside or n:
            out.add(i)
        if n % 2 == 1:
            inside = not inside
    return out


def _is_code(line: str) -> bool:
    return bool(line.strip()) and not COMMENT.match(line)


def generate_mutants(base_text: str | None, final_text: str, max_mutants: int = 20) -> list[Mutant]:
    base = (base_text or "").splitlines(keepends=True)
    final = final_text.splitlines(keepends=True)
    opcodes = SequenceMatcher(None, base, final, autojunk=False).get_opcodes()
    docs = _docstring_lines(final)

    reverts: list[Mutant] = []
    added: list[int] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        added.extend(j for j in range(j1, j2) if j not in docs)
        if not any(_is_code(l) and not STRUCTURAL.match(l) for l in final[j1:j2] + base[i1:i2]):
            continue
        text = "".join(final[:j1] + base[i1:i2] + final[j2:])
        first = next((l.strip() for l in final[j1:j2] if l.strip()), "(deleted lines)")
        reverts.append(Mutant("missing_behaviour", f"revert change at line {j1 + 1} (`{first[:60]}`)", text))

    per_line: list[list[Mutant]] = []
    for j in added:
        line = final[j]
        if not _is_code(line) or STRUCTURAL.match(line):
            continue
        muts = []
        for name, pat, rep in OPERATORS:
            m = next((m for m in pat.finditer(line) if not _in_string(line, m.start())), None)
            if m is None:
                continue
            new = line[: m.start()] + (rep(m) if callable(rep) else rep) + line[m.end():]
            text = "".join(final[:j] + [new] + final[j + 1:])
            muts.append(Mutant("wrong_behaviour", f"line {j + 1}: {name}: `{line.strip()[:70]}`", text))
        if muts:
            per_line.append(muts)

    # Interleave so a small budget still covers many lines: one op per line per round.
    ops: list[Mutant] = []
    for round_ in range(max((len(m) for m in per_line), default=0)):
        ops.extend(m[round_] for m in per_line if round_ < len(m))

    chosen: list[Mutant] = []
    seen = {final_text}
    budget_reverts = max(1, max_mutants // 3)
    for m in reverts[:budget_reverts] + ops + reverts[budget_reverts:]:
        if m.text not in seen:
            seen.add(m.text)
            chosen.append(m)
        if len(chosen) >= max_mutants:
            break
    return chosen
