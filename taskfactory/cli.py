"""Command line entry point: python -m taskfactory <command> ..."""
from __future__ import annotations

import argparse
import os
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


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from .env into the environment (existing variables win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _log(msg: str) -> None:
    print(msg, flush=True)


def _common(args):
    repo = Path(args.repo).resolve()
    cfg = load_config(Path(args.config) if args.config else repo / "taskfactory.toml", repo)
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
    valid = lambda: len(list(out.glob("*/task.json")))
    rounds = 0
    while True:
        rounds += 1
        generate(llm, repo, cfg, base, out, args.n, max_repairs=args.max_repairs, log=_log)
        if not args.target or valid() >= args.target or rounds >= args.max_rounds:
            break
        _log(f"{valid()}/{args.target} valid after round {rounds}; proposing more")
    _log(summarize(out))
    return 0


def cmd_validate(args) -> int:
    """Re-run validation for an existing package from its patches (reproducibility check)."""
    d = Path(args.task)
    meta, req, src, tests = load_package(d)
    repo = Path(args.repo).resolve()
    cfg = load_config(Path(args.config) if args.config else repo / "taskfactory.toml", repo)
    report = validate(repo, cfg, meta["base_commit"], src, tests, req, mutants=not args.no_mutants, log=_log)
    for c in report["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["severity"] == "error" else "warn")
        _log(f"  [{mark}] {c['name']} {c['detail']}")
    _log(f"fail_to_pass={len(report['fail_to_pass'])} pass_to_pass={len(report['pass_to_pass'])} "
         f"mutation={report['mutation']['killed']}/{report['mutation']['total']}")
    _log("VALID" if report["valid"] else "INVALID")
    return 0 if report["valid"] else 1


def cmd_export_harbor(args) -> int:
    import subprocess
    from .config import load_harbor_config
    from .harbor import export_task, pipeline_run
    hcfg = load_harbor_config(Path(args.config))
    tasks, dest = Path(args.tasks), Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    exported = {}
    metas = sorted(tasks.glob("*/task.json"))
    if args.limit:
        from .submit import select_diverse
        keep = set(select_diverse(tasks, args.limit))
        metas = [m for m in metas if m.parent.name in keep]
        _log(f"selected {len(metas)} most mutually different packages: {sorted(keep)}")
    for old in dest.iterdir():
        if old.is_dir() and (old / "task.toml").exists():
            import shutil
            shutil.rmtree(old)  # only what this run exports ends up in the submission
    for meta in metas:
        d = export_task(meta.parent, hcfg, dest)
        exported[meta.parent.name] = d
        _log(f"exported {d}")
    run = pipeline_run(tasks, exported, args.pipeline)
    out = Path(args.run_log) if args.run_log else dest.parent / "pipeline_run.json"
    out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    _log(f"wrote {out} ({len(run['tasks'])} tasks)")
    lint = Path(__file__).resolve().parent.parent / "vendor" / "organizer-kit" / "harness" / "check_structure.py"
    if lint.exists() and exported:
        _log("organiser lint (check_structure.py):")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, str(lint), *map(str, exported.values())], env=env).returncode
    return 0


def cmd_selfcheck(args) -> int:
    from .submit import selfcheck
    tasks = [Path(t) for t in args.tasks]
    if len(tasks) == 1 and not (tasks[0] / "task.toml").exists():
        tasks = sorted(p.parent for p in tasks[0].glob("*/task.toml"))
    return 0 if selfcheck(tasks, Path(args.out), log=_log, network=args.network) else 1


def cmd_bundle(args) -> int:
    from .submit import bundle
    bundle(args.team, Path(args.submission), Path(args.tasks), Path(args.dest),
           selfcheck_dir=Path(args.selfcheck) if args.selfcheck else None,
           docs=[Path(d) for d in args.doc], log=_log)
    return 0


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
    p.add_argument("--target", type=int, default=0, help="keep proposing until this many packages are valid")
    p.add_argument("--max-rounds", type=int, default=3)
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("validate", help="re-validate an existing task package")
    p.add_argument("task")
    p.add_argument("--repo", required=True)
    p.add_argument("--config")
    p.add_argument("--no-mutants", action="store_true")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("export-harbor", help="export valid packages as Harbor tasks + pipeline_run.json")
    p.add_argument("tasks", help="directory of validated packages (output of drafts/generate)")
    p.add_argument("--config", required=True, help="config TOML with a [harbor] section")
    p.add_argument("--dest", default="submission/generated_tasks")
    p.add_argument("--run-log", help="where to write pipeline_run.json (default: next to --dest)")
    p.add_argument("--pipeline", default="taskfactory/0.3")
    p.add_argument("--limit", type=int, default=0, help="export only the N most mutually different packages")
    p.set_defaults(fn=cmd_export_harbor)

    p = sub.add_parser("selfcheck", help="organiser self-check: harbor oracle (=1.0) and nop (=0.0) per package")
    p.add_argument("tasks", nargs="+", help="Harbor package dirs, or one directory containing them")
    p.add_argument("--out", default="sc")
    p.add_argument("--network", choices=["public"], help="run a copy with this network_mode (for hosts that cannot enforce no-network)")
    p.set_defaults(fn=cmd_selfcheck)

    p = sub.add_parser("bundle", help="assemble <Team>_Track1/ + zip and run the organiser submission validator")
    p.add_argument("--team", required=True)
    p.add_argument("--submission", default="submission", help="dir holding generated_tasks/ + pipeline_run.json")
    p.add_argument("--tasks", default="out/click", help="internal packages (for validation reports + model logs)")
    p.add_argument("--selfcheck", default="sc", help="selfcheck output dir")
    p.add_argument("--doc", action="append", default=["docs/WRITEUP.md", "docs/SUBMISSION_README.md"])
    p.add_argument("--dest", default="dist")
    p.set_defaults(fn=cmd_bundle)

    p = sub.add_parser("report", help="rebuild SUMMARY.md for a task directory")
    p.add_argument("out")
    p.set_defaults(fn=cmd_report)

    load_dotenv()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # organiser tools print unicode marks
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
