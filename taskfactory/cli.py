"""Command line entry point: python -m taskfactory <command> ..."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from .config import load_config
from .edits import EditError
from .gitutil import repo_identity, rev_parse
from .package import build_patches, load_package, write_package
from .report import summarize
from .validate import failure_summary, validate


def _log(msg: str) -> None:
    print(msg, flush=True)


def _common(args):
    repo = Path(args.repo).resolve()
    cfg = load_config(Path(args.config) if args.config else repo / "taskfactory.toml")
    return repo, cfg, rev_parse(repo, args.base)


def cmd_init_sample(args) -> int:
    from .sample import init_sample
    d = init_sample(Path(args.dest))
    _log(f"created {d}")
    return 0


def cmd_drafts(args) -> int:
    """Validate and package hand-written drafts (TOML or JSON). Used for the offline demo and for
    any task a human wrote or fixed; provenance records that."""
    repo, cfg, base = _common(args)
    path = Path(args.drafts)
    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw) if path.suffix == ".toml" else json.loads(raw)
    out = Path(args.out)
    ok = 0
    for i, draft in enumerate(data["tasks"], 1):
        _log(f"[{i}/{len(data['tasks'])}] {draft.get('title')}")
        try:
            src, tests = build_patches(repo, cfg, base, draft)
        except EditError as e:
            _log(f"  edit error: {e}")
            continue
        report = validate(repo, cfg, base, src, tests, draft["requirements"], mutants=not args.no_mutants, log=_log)
        d = write_package(out, repo_id=repo_identity(repo), cfg=cfg, base=base, draft=draft, src=src, tests=tests,
                          report=report, provenance={"generator": "manual-draft", "source": path.name, "manual_edits": True})
        ok += report["valid"]
        _log(f"  -> {'VALID' if report['valid'] else 'REJECTED'} {d}")
        if not report["valid"]:
            _log("    " + failure_summary(report).replace("\n", "\n    ")[:1500])
    summarize(out)
    _log(f"{ok}/{len(data['tasks'])} valid; summary in {out / 'SUMMARY.md'}")
    return 0


def cmd_generate(args) -> int:
    from .generate import generate
    from .llm import LLM
    repo, cfg, base = _common(args)
    out = Path(args.out)
    llm = LLM.from_env(log_path=out / "_llm_log.jsonl")
    generate(llm, repo, cfg, base, out, args.n, max_repairs=args.max_repairs, log=_log)
    _log(summarize(out))
    return 0


def cmd_validate(args) -> int:
    """Re-run validation for an existing package from its patches (reproducibility check)."""
    d = Path(args.task)
    meta, req, src, tests = load_package(d)
    repo = Path(args.repo).resolve()
    cfg = load_config(Path(args.config) if args.config else repo / "taskfactory.toml")
    report = validate(repo, cfg, meta["base_commit"], src, tests, req, mutants=not args.no_mutants, log=_log)
    for c in report["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["severity"] == "error" else "warn")
        _log(f"  [{mark}] {c['name']} {c['detail']}")
    _log(f"fail_to_pass={len(report['fail_to_pass'])} pass_to_pass={len(report['pass_to_pass'])} "
         f"mutation={report['mutation']['killed']}/{report['mutation']['total']}")
    _log("VALID" if report["valid"] else "INVALID")
    return 0 if report["valid"] else 1


def cmd_report(args) -> int:
    _log(summarize(Path(args.out)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="taskfactory", description="Generate validated feature-development tasks from a repository.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def repo_args(p):
        p.add_argument("--repo", required=True, help="path to the target git repository")
        p.add_argument("--config", help="repo config TOML (default: <repo>/taskfactory.toml)")
        p.add_argument("--base", default="HEAD", help="starting commit/branch for tasks (default HEAD)")

    p = sub.add_parser("init-sample", help="create the stand-in shopcart repo")
    p.add_argument("dest")
    p.set_defaults(fn=cmd_init_sample)

    p = sub.add_parser("drafts", help="validate + package hand-written drafts")
    p.add_argument("drafts")
    repo_args(p)
    p.add_argument("--out", default="out/tasks")
    p.add_argument("--no-mutants", action="store_true")
    p.set_defaults(fn=cmd_drafts)

    p = sub.add_parser("generate", help="generate tasks with an LLM")
    repo_args(p)
    p.add_argument("--out", default="out/tasks")
    p.add_argument("-n", type=int, default=5, help="number of proposals")
    p.add_argument("--max-repairs", type=int, default=2)
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("validate", help="re-validate an existing task package")
    p.add_argument("task")
    p.add_argument("--repo", required=True)
    p.add_argument("--config")
    p.add_argument("--no-mutants", action="store_true")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("report", help="rebuild SUMMARY.md for a task directory")
    p.add_argument("out")
    p.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
