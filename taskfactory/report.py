"""Aggregate a directory of task packages into SUMMARY.md (validity, test strength, variation)."""
from __future__ import annotations

import itertools
import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


def _load(dirs: list[Path]) -> list[tuple[dict, dict, str]]:
    rows = []
    for d in dirs:
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        val = json.loads((d / "validation.json").read_text(encoding="utf-8"))
        rows.append((meta, val, (d / "requirements.md").read_text(encoding="utf-8")))
    return rows


def summarize(out: Path) -> str:
    valid = _load(sorted(p.parent for p in out.glob("*/task.json")))
    rejected = _load(sorted(p.parent for p in (out / "_rejected").glob("*/task.json")))
    lines = ["# Task factory summary", "",
             f"- valid tasks: **{len(valid)}**",
             f"- rejected drafts: **{len(rejected)}** (kept in `_rejected/` with their reports)", ""]

    lines += ["## Tasks", "",
              "| task | category | fail→pass | pass→pass | behavioural mutants caught | files | +lines | warnings |",
              "|---|---|---|---|---|---|---|---|"]
    for meta, val, _ in valid:
        m = val["mutation"]
        patch = (out / meta["id"] / "reference.patch").read_text(encoding="utf-8")
        plus = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
        lines.append(f"| `{meta['id']}` | {meta.get('category')} | {len(meta['fail_to_pass'])} | "
                     f"{len(meta['pass_to_pass'])} | {m.get('behavioural_killed', m['killed'])}/{m.get('behavioural_total', m['total'])} | {len(meta['source_files'])} | "
                     f"{plus} | {', '.join(meta['warnings']) or '-'} |")

    if valid:
        cats = Counter(m.get("category") for m, _, _ in valid)
        files = Counter(f for m, _, _ in valid for f in m["source_files"])
        sims = [SequenceMatcher(None, a, b).ratio() for (_, _, a), (_, _, b) in itertools.combinations(valid, 2)]
        scores = [v["mutation"]["score"] for _, v, _ in valid if v["mutation"]["score"] is not None]
        lines += ["", "## Variation", "",
                  f"- categories: {dict(cats)}",
                  f"- source files touched: {dict(files)}",
                  f"- requirement text similarity between tasks: mean {sum(sims) / len(sims):.2f}, max {max(sims):.2f}" if sims else "- (one task, no pairwise similarity)",
                  "", "## Test strength", "",
                  f"- mean mutation score: {sum(scores) / len(scores):.2f}" if scores else "- no mutation data"]

    if rejected:
        lines += ["", "## Why drafts were rejected", ""]
        reasons = Counter(c["name"] for _, v, _ in rejected for c in v["checks"] if not c["ok"] and c["severity"] == "error")
        lines += [f"- {k}: {n}" for k, n in reasons.most_common()]

    text = "\n".join(lines) + "\n"
    (out / "SUMMARY.md").write_text(text, encoding="utf-8")
    return text
