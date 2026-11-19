"""Validate a task package: is it solvable, and do its tests really check the feature?

Runs, all in one throwaway checkout of the base commit:
  1. base             - original repo, full suite  -> which tests pass to begin with
  2. base + tests     - hidden tests, no feature   -> feature tests must FAIL here
  3. base + tests + reference                      -> everything must PASS (run twice: flakiness)
  4. mutants of the reference                      -> feature tests must catch them
"""
from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .config import RepoConfig
from .gitutil import added_lines, apply_patch, patch_paths, show, word_in_tree, worktree
from .mutate import generate_mutants
from .runner import FAIL, PASS, RunResult, run_setup, run_tests

IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
COMMON = set(keyword.kwlist) | set(dir(builtins)) | {"self", "cls", "pytest", "assert", "test", "tests"}


@dataclass
class Check:
    name: str
    ok: bool
    severity: str  # "error" fails the task, "warning" is reported only
    detail: str = ""


def undisclosed_interface(repo: Path, base: str, src_patch: str, test_patch: str, requirements: str) -> list[str]:
    """New identifiers that the tests rely on but the requirements never mention.
    A solver can't be expected to guess these names, so the task would be unfair."""
    new_in_src = set(IDENT.findall("\n".join(added_lines(src_patch))))
    used_by_tests = set(IDENT.findall("\n".join(added_lines(test_patch))))
    mentioned = set(IDENT.findall(requirements))
    cands = sorted(n for n in new_in_src & used_by_tests if n not in mentioned and n not in COMMON)
    return [n for n in cands if not word_in_tree(repo, base, n)]


def validate(
    repo: Path,
    cfg: RepoConfig,
    base: str,
    src_patch: str,
    test_patch: str,
    requirements: str,
    *,
    mutants: bool = True,
    log: Callable[[str], None] = lambda s: None,
) -> dict:
    checks: list[Check] = []
    src_paths, test_paths = patch_paths(src_patch), patch_paths(test_patch)
    wrong_src = [p for p in src_paths if cfg.is_test(p)]
    wrong_test = [p for p in test_paths if not cfg.is_test(p)]
    checks.append(Check(
        "patch_separation",
        bool(src_paths) and bool(test_paths) and not wrong_src and not wrong_test,
        "error",
        f"source patch touches test files {wrong_src}; test patch touches non-test files {wrong_test}"
        if wrong_src or wrong_test else ("" if src_paths and test_paths else "reference or test patch is empty"),
    ))

    runs: dict[str, RunResult] = {}
    mutation: dict = {"total": 0, "killed": 0, "score": None, "survivors": [], "results": []}
    with worktree(repo, base) as wt:
        run_setup(wt, cfg)
        log("  run 1/4: original repo")
        runs["base"] = run_tests(wt, cfg)
        apply_patch(wt, test_patch)
        log("  run 2/4: tests without the feature")
        runs["tests_only"] = run_tests(wt, cfg)
        apply_patch(wt, src_patch)
        log("  run 3/4: tests with reference implementation (x2)")
        runs["reference"] = run_tests(wt, cfg)
        runs["reference_rerun"] = run_tests(wt, cfg)

        full = runs["reference"].outcomes
        base_pass = {t for t, o in runs["base"].outcomes.items() if o == PASS}
        # A test that already passed before the feature is not fail-to-pass, even if the
        # tests-only run lost it (e.g. a collection error aborting the whole session).
        f2p = sorted(t for t, o in full.items()
                     if o == PASS and not runs["tests_only"].passed(t) and t not in base_pass)
        test_files = [p for p in test_paths if (wt / p).exists()]

        if mutants and f2p and not runs["reference"].crashed:
            per_file = max(3, cfg.max_mutants // max(1, len(src_paths)))
            todo = []
            for p in src_paths:
                if (wt / p).exists():
                    final = (wt / p).read_bytes().decode("utf-8", "replace")
                    todo += [(p, final, m) for m in generate_mutants(show(repo, base, p), final, per_file)]
            todo = todo[: cfg.max_mutants]
            log(f"  run 4/4: {len(todo)} mutants")
            for path, final, m in todo:
                (wt / path).write_bytes(m.text.encode("utf-8"))
                r = run_tests(wt, cfg, test_files)
                (wt / path).write_bytes(final.encode("utf-8"))
                caught = [t for t in f2p if not r.passed(t)]
                killed = r.crashed or bool(caught)
                # Killed because nothing could even run (syntax/import error): proves little.
                trivial = r.crashed or not any(o == PASS for o in r.outcomes.values())
                mutation["results"].append({"file": path, "kind": m.kind, "mutant": m.description,
                                            "killed": killed, "trivial": trivial, "caught_by": caught[:5]})
                if not killed:
                    mutation["survivors"].append(f"{path}: {m.description}")
            res = mutation["results"]
            mutation["total"] = len(res)
            mutation["killed"] = sum(r["killed"] for r in res)
            behavioural = [r for r in res if not r["trivial"]]
            mutation["behavioural_total"] = len(behavioural)
            mutation["behavioural_killed"] = sum(r["killed"] for r in behavioural)
            # Score on mutants that still run, unless there are too few of them to mean anything.
            if len(behavioural) >= 3:
                mutation["score"] = round(mutation["behavioural_killed"] / len(behavioural), 3)
            elif res:
                mutation["score"] = round(mutation["killed"] / len(res), 3)

    base_out, tonly, rerun = runs["base"].outcomes, runs["tests_only"], runs["reference_rerun"].outcomes
    p2p = sorted(t for t in base_pass if full.get(t) == PASS)
    regressions = sorted(t for t in base_pass if full.get(t) != PASS)
    failing = sorted(t for t, o in full.items() if o == FAIL)
    new_tests = sorted(t for t in full if t not in base_out)
    weak = sorted(t for t in new_tests if tonly.passed(t))
    flaky = sorted(t for t in full if rerun.get(t) != full[t])

    checks += [
        Check("base_suite_runs", not runs["base"].crashed, "error", "original test suite did not run" if runs["base"].crashed else ""),
        Check("reference_passes", not runs["reference"].crashed and not failing, "error",
              f"failing with reference implementation: {failing[:10]}" if failing else
              ("test run crashed with the reference implementation" if runs["reference"].crashed else "")),
        Check("has_fail_to_pass", bool(f2p), "error", "" if f2p else "no test fails without the feature and passes with it"),
        Check("no_regressions", not regressions, "error", f"previously passing tests now fail/missing: {regressions[:10]}" if regressions else ""),
        Check("deterministic", not flaky, "error", f"different result on rerun: {flaky[:10]}" if flaky else ""),
        Check("new_tests_need_feature", not weak, "warning",
              f"new tests already pass without the feature (not testing it): {weak[:10]}" if weak else ""),
    ]
    if mutants:
        score = mutation["score"]
        checks.append(Check(
            "mutation_score",
            score is not None and score >= cfg.mutation_threshold,
            "error" if mutation["total"] else "warning",
            f"{mutation['killed']}/{mutation['total']} mutants caught; "
            f"{mutation.get('behavioural_killed', 0)}/{mutation.get('behavioural_total', 0)} of those that still run "
            f"(score {mutation['score']}, threshold {cfg.mutation_threshold})"
            if mutation["total"] else "no mutants could be generated",
        ))
    hidden = undisclosed_interface(repo, base, src_patch, test_patch, requirements)
    checks.append(Check("interface_disclosed", not hidden, "warning",
                        f"tests use new names the requirements never mention: {hidden}" if hidden else ""))

    return {
        "valid": all(c.ok for c in checks if c.severity == "error"),
        "checks": [asdict(c) for c in checks],
        "fail_to_pass": f2p,
        "pass_to_pass": p2p,
        "test_files": test_files,
        "source_files": src_paths,
        "mutation": mutation,
        "runs": {k: v.summary() for k, v in runs.items()},
        "logs": {k: v.log[-2500:] for k, v in runs.items() if v.crashed or k == "reference" and failing},
    }


def failure_summary(report: dict) -> str:
    """Compact, model-readable explanation of why a task failed validation."""
    lines = []
    for c in report["checks"]:
        if not c["ok"]:
            lines.append(f"- [{c['severity']}] {c['name']}: {c['detail']}")
    if report["mutation"]["survivors"]:
        lines.append("Wrong implementations that the tests did NOT catch (add assertions that would fail for these):")
        lines += [f"  * {s}" for s in report["mutation"]["survivors"][:10]]
    for name, text in report.get("logs", {}).items():
        lines.append(f"--- tail of test output ({name}) ---\n{text[-1500:]}")
    return "\n".join(lines)
