"""LLM pipeline: propose diverse features -> write requirements, reference and tests -> validate -> repair."""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .config import RepoConfig
from .edits import EditError
from .gitutil import repo_identity
from .llm import LLM, LLMError
from .package import build_patches, write_package
from .repomap import build_repo_map, example_tests, read_files
from .validate import failure_summary, validate

# Variation comes from forcing different *kinds* of behaviour, not different names.
CATEGORIES = {
    "business_rule": "a new rule or policy that changes computed results under specific conditions",
    "validation": "new input or state validation with specific, documented error types",
    "state_interaction": "behaviour that depends on how two or more existing components interact, or on the order of operations",
    "query_aggregation": "a new derived query, filter, aggregation or report over existing data",
    "configuration": "a new option that changes existing behaviour, with a backward-compatible default",
    "lifecycle": "new state transitions such as expiry, cancellation, undo, or limits over time/count",
    "error_handling": "graceful handling of a currently unhandled edge case or failure mode",
}

PROPOSE_SYSTEM = """You design feature-development tasks used to evaluate AI coding systems.
Each task asks a solver to add ONE realistic feature to an existing repository.
Good tasks:
- change observable behaviour (rules, interactions, states), not names or structure
- fit the existing design and could plausibly appear in the project's issue tracker
- need roughly 20-150 lines of source changes
- can be verified by deterministic automated tests (no network, clock, randomness or new dependencies)
- have behaviour that can be specified precisely, including edge cases
Reply with JSON only."""

PROPOSE_USER = """Repository (base commit {base}):
{repo_map}

Feature categories:
{categories}

Tasks that already exist (do NOT propose anything overlapping):
{existing}

Propose {n} new tasks, each from a DIFFERENT category where possible, preferring ones that touch different parts of the code.
Return:
{{"proposals": [{{
  "title": "short imperative title",
  "category": "one of the category keys",
  "summary": "2-3 sentences",
  "behaviours": ["3-6 concrete rules the tests will check, including edge cases and error conditions"],
  "files_to_read": ["existing files needed for context"],
  "files_to_change": ["source files to modify or create"]
}}]}}"""

IMPLEMENT_SYSTEM = """You write complete task packages for evaluating AI coding systems. A package has:
1. requirements: Markdown given to the solver. Describe the feature precisely: every rule, edge case,
   error type and return value the tests check. You MUST name every new public class, function, method,
   parameter, attribute and exception the tests use, with signatures. Do not explain how to implement it
   and do not mention hidden tests.
2. source_edits: the reference implementation, as search/replace edits on NON-test files.
3. test_edits: new tests, as search/replace edits on test files only (prefer one new test file).
   Tests must FAIL on the original code and PASS with the reference. Cover every stated behaviour and
   boundary (e.g. exactly at a threshold, just past it), so a wrong or partial implementation fails.
   Only test behaviour stated in the requirements. Reuse existing fixtures and style. Deterministic only.
   Never change existing tests.

Edit format: {"path": "...", "search": "exact text copied from the current file, unique within it",
"replace": "new text"}. To create a new file use "search": "" and put the whole file in "replace".
Keep search blocks short (a few lines) but unique. Reply with JSON only."""

IMPLEMENT_USER = """Task proposal:
{proposal}

Source files (base commit):
{files}

Existing tests, for style and fixtures:
{tests}

Test files are paths matching: {test_globs}
Tests are run with: {test_cmd}

Return:
{{"title": "...", "category": "...", "requirements": "markdown",
  "source_edits": [{{"path": "...", "search": "...", "replace": "..."}}],
  "test_edits": [{{"path": "...", "search": "...", "replace": "..."}}]}}"""

REPAIR_USER = """Your task package failed validation.

Problems:
{problems}

Previous package:
{draft}

Source files (base commit, before your edits):
{files}

Fix the package. You may change the requirements, reference implementation and tests. Keep the same feature.
Return the COMPLETE corrected package in the same JSON format (edits apply to the ORIGINAL files)."""


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def existing_titles(out: Path) -> list[str]:
    titles = []
    for meta in out.glob("*/task.json"):
        d = json.loads(meta.read_text(encoding="utf-8"))
        titles.append(f"{d.get('title')} [{d.get('category')}]")
    return titles


def propose(llm: LLM, repo: Path, cfg: RepoConfig, base: str, n: int, existing: list[str]) -> list[dict]:
    user = PROPOSE_USER.format(
        base=base[:12],
        repo_map=build_repo_map(repo, base, cfg),
        categories="\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()),
        existing="\n".join(f"- {t}" for t in existing) or "(none)",
        n=n,
    )
    props = llm.chat_json(PROPOSE_SYSTEM, user, "propose").get("proposals", [])
    kept: list[dict] = []
    for p in props:
        text = f"{p.get('title', '')} {p.get('summary', '')}"
        if any(_similar(text, t) > 0.75 for t in existing + [f"{k.get('title')} {k.get('summary')}" for k in kept]):
            continue
        kept.append(p)
    return kept


def _context_files(p: dict) -> list[str]:
    return list(dict.fromkeys((p.get("files_to_read") or []) + (p.get("files_to_change") or [])))


def generate_one(llm: LLM, repo: Path, cfg: RepoConfig, base: str, proposal: dict, out: Path,
                 *, max_repairs: int = 2, log: Callable[[str], None] = print) -> Path | None:
    files = read_files(repo, base, _context_files(proposal))
    draft = llm.chat_json(IMPLEMENT_SYSTEM, IMPLEMENT_USER.format(
        proposal=json.dumps(proposal, indent=2), files=files, tests=example_tests(repo, base, cfg),
        test_globs=cfg.test_globs, test_cmd=cfg.test_cmd), "implement")
    draft.setdefault("title", proposal.get("title"))
    draft.setdefault("category", proposal.get("category"))

    last = None
    for attempt in range(max_repairs + 1):
        try:
            src, tests = build_patches(repo, cfg, base, draft)
            log(f"  validating (attempt {attempt + 1})")
            report = validate(repo, cfg, base, src, tests, draft.get("requirements", ""), log=log)
            last = (src, tests, report)
            if report["valid"]:
                break
            problems = failure_summary(report)
        except EditError as e:
            problems = f"- edits could not be applied: {e}"
        log(f"  attempt {attempt + 1} failed:\n    " + problems.replace("\n", "\n    ")[:1200])
        if attempt == max_repairs:
            break
        try:
            draft = llm.chat_json(IMPLEMENT_SYSTEM, REPAIR_USER.format(
                problems=problems, draft=json.dumps(draft, indent=2), files=files), "repair")
        except LLMError as e:
            log(f"  repair call failed: {e}")
            break

    if last is None:
        return None
    src, tests, report = last
    prov = {"generator": "llm", "model": llm.model, "attempts": attempt + 1, "manual_edits": False}
    return write_package(out, repo_id=repo_identity(repo), cfg=cfg, base=base, draft=draft,
                         src=src, tests=tests, report=report, provenance=prov)


def generate(llm: LLM, repo: Path, cfg: RepoConfig, base: str, out: Path, n: int,
             *, max_repairs: int = 2, log: Callable[[str], None] = print) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    proposals = propose(llm, repo, cfg, base, n, existing_titles(out))
    log(f"{len(proposals)} proposals after de-duplication")
    made = []
    for i, p in enumerate(proposals, 1):
        log(f"[{i}/{len(proposals)}] {p.get('title')} ({p.get('category')})")
        try:
            d = generate_one(llm, repo, cfg, base, p, out, max_repairs=max_repairs, log=log)
        except LLMError as e:
            log(f"  model error: {e}")
            continue
        if d is not None:
            log(f"  -> {'VALID' if d.parent == out else 'rejected'}: {d}")
            made.append(d)
    log(f"model usage: {llm.usage}")
    return made
