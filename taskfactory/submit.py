"""Submission helpers: pick a diverse subset, run the Harbor self-check, assemble TeamName_Track1.zip."""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "vendor" / "organizer-kit" / "harness"


# ---- diverse selection --------------------------------------------------------

def _distance(a: dict, b: dict) -> float:
    """How different two packages are: category, each variation axis, files touched, requirement text."""
    d = float(a.get("category") != b.get("category"))
    ax_a, ax_b = a.get("axes") or {}, b.get("axes") or {}
    for k in set(ax_a) | set(ax_b):
        d += 0.5 * (1 - SequenceMatcher(None, str(ax_a.get(k, "")).lower(), str(ax_b.get(k, "")).lower()).ratio())
    fa, fb = set(a.get("source_files", [])), set(b.get("source_files", []))
    d += 1 - len(fa & fb) / max(1, len(fa | fb))
    d += 1 - SequenceMatcher(None, a["_req"], b["_req"]).ratio()
    return d


def select_diverse(tasks_dir: Path, k: int) -> list[str]:
    """Package ids of the k valid packages that maximise the minimum pairwise distance (exhaustive for
    small pools, greedy otherwise). Ties go to the stronger test suite (mutation score, F2P count)."""
    pool = []
    for meta_path in sorted(tasks_dir.glob("*/task.json")):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        if m.get("valid"):
            m["_req"] = (meta_path.parent / "requirements.md").read_text(encoding="utf-8").lower()
            pool.append(m)
    if len(pool) <= k:
        return [m["id"] for m in pool]
    strength = lambda m: (m.get("mutation_score") or 0) + len(m["fail_to_pass"]) / 1000

    def score(combo):
        return (min(_distance(a, b) for a, b in itertools.combinations(combo, 2)), sum(map(strength, combo)))

    if len(pool) <= 14:
        best = max(itertools.combinations(pool, k), key=score)
    else:
        best = [max(pool, key=strength)]
        while len(best) < k:
            rest = [m for m in pool if m not in best]
            best.append(max(rest, key=lambda m: (min(_distance(m, b) for b in best), strength(m))))
    return [m["id"] for m in best]


# ---- Harbor self-check (Python port of the organisers' selfcheck.sh, works on Windows) ---------------

def _grade(run_dir: Path) -> dict:
    found = sorted(run_dir.rglob("grading_details.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(found[-1].read_text(encoding="utf-8")) if found else {}


def _relaxed_copy(task: Path, tmp: Path, mode: str) -> Path:
    """Copy of a package with a different network_mode, for hosts whose kernel cannot enforce no-network
    (Docker Desktop's WSL2 kernel lacks CONFIG_NFT_FIB_INET). Everything else is byte-identical."""
    d = tmp / task.name
    shutil.copytree(task, d)
    toml = d / "task.toml"
    toml.write_bytes(toml.read_bytes().replace(b'network_mode = "no-network"', f'network_mode = "{mode}"'.encode()))
    return d


def selfcheck(task_dirs: list[Path], out_root: Path, log: Callable[[str], None] = print,
              network: str | None = None) -> bool:
    import tempfile
    harbor = shutil.which("harbor")
    if not harbor:
        raise RuntimeError("harbor CLI not on PATH (uv tool install harbor)")
    all_ok, lines = True, [f"# selfcheck output: {out_root}", ""]
    if network:
        lines += [f"# NOTE: run with network_mode={network} instead of no-network: this host's Docker kernel cannot",
                  "# enforce no-network. Packages are otherwise unchanged; the submitted task.toml keeps no-network.", ""]
    tmp = Path(tempfile.mkdtemp(prefix="tf-selfcheck-"))
    for task in task_dirs:
        iid = task.name
        if network:
            task = _relaxed_copy(task, tmp, network)
        res = {}
        for agent in ("oracle", "nop"):
            o = out_root / iid / agent
            o.mkdir(parents=True, exist_ok=True)
            r = subprocess.run([harbor, "run", "-p", str(task), "-a", agent, "-k", "1", "-o", str(o), "--no-delete", "-y"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
            (o / ".err").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
            res[agent] = _grade(o)
        lines.append(f"== {iid} ==")
        o, n = res["oracle"], res["nop"]
        if not o or not n:
            lines += [f"  FAIL  a baseline produced no grading (build/env crash). See {out_root / iid}/*/.err", ""]
            all_ok = False
            log("\n".join(lines[-3:]))
            continue
        for name, g in (("oracle", o), ("nop", n)):
            lines.append(f"  {name:<7} reward={g.get('reward')!s:<5} F2P={g.get('f2p_passed')}/{g.get('f2p_total')} "
                         f"P2P={g.get('p2p_passed')}/{g.get('p2p_total')}")
        ok = True
        if not (float(o.get("reward", 0)) == 1.0 and o.get("f2p_passed") == o.get("f2p_total")):
            lines.append("  x gold not 1.0 / F2P not full"); ok = False
        if n.get("f2p_total") and n.get("f2p_passed") == n.get("f2p_total"):
            lines.append("  x F2P already pass at base (tests don't detect the feature)"); ok = False
        if not (o.get("p2p_passed") == o.get("p2p_total") and n.get("p2p_passed") == n.get("p2p_total")):
            lines.append("  x P2P not full on oracle and/or nop (regression)"); ok = False
        lines += ["  mechanically sound" if ok else "  NOT sound", ""]
        all_ok &= ok
        log("\n".join(lines[-6:]))
    lines.append("ALL SOUND" if all_ok else "SOME NOT SOUND")
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "selfcheck.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return all_ok


# ---- bundle -------------------------------------------------------------------

def _kit(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KIT / script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def bundle(team: str, submission: Path, tasks_dir: Path, dest: Path, *, selfcheck_dir: Path | None = None,
           docs: list[Path] = (), log: Callable[[str], None] = print) -> Path:
    """Assemble dest/<team>_Track1/ and dest/<team>_Track1.zip from:
    - the pipeline source at HEAD (git archive, so only committed, non-secret files),
    - submission/generated_tasks + pipeline_run.json (from export-harbor),
    - evidence: self-check tables, organiser lint output, internal validation reports, model-call logs."""
    name = f"{team}_Track1"
    top = dest / name
    if top.exists():
        shutil.rmtree(top)
    top.mkdir(parents=True)

    archive = dest / "_pipeline.zip"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", "-o", str(archive), "HEAD"], check=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(top / "pipeline")
    archive.unlink()

    shutil.copytree(submission / "generated_tasks", top / "generated_tasks")
    shutil.copy2(submission / "pipeline_run.json", top / "pipeline_run.json")
    if (submission / "trajectory").is_dir():
        shutil.copytree(submission / "trajectory", top / "trajectory")
    for doc in docs:
        shutil.copy2(doc, top / doc.name)

    ev = top / "evidence"
    ev.mkdir()
    pkgs = sorted((top / "generated_tasks").iterdir())
    lint = _kit("check_structure.py", *map(str, pkgs))
    (ev / "check_structure.txt").write_text(lint.stdout + lint.stderr, encoding="utf-8")
    if selfcheck_dir and (selfcheck_dir / "selfcheck.txt").exists():
        shutil.copy2(selfcheck_dir / "selfcheck.txt", ev / "selfcheck.txt")
    # internal reports for exactly the exported packages (mutation results, curated P2P, provenance)
    for meta_path in sorted(tasks_dir.glob("*/task.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if any(p.name.endswith(meta["id"][-6:]) for p in pkgs):
            dst = ev / "validation" / meta["id"]
            dst.mkdir(parents=True)
            for f in ("task.json", "validation.json", "draft.json"):
                if (meta_path.parent / f).exists():
                    shutil.copy2(meta_path.parent / f, dst / f)
    for f in ("SUMMARY.md", "_llm_log.jsonl"):
        if (tasks_dir / f).exists():
            shutil.copy2(tasks_dir / f, ev / f)
    if (tasks_dir / "_rejected").is_dir():
        (ev / "rejected.txt").write_text("\n".join(sorted(p.name for p in (tasks_dir / "_rejected").iterdir())) + "\n",
                                         encoding="utf-8")

    v = _kit("validate_submission.py", str(top))
    (ev / "validate_submission.txt").write_text(v.stdout + v.stderr, encoding="utf-8")

    zpath = dest / f"{name}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(top.rglob("*")):
            if f.is_file():
                info = zipfile.ZipInfo.from_file(f, f.relative_to(dest).as_posix())
                if f.suffix == ".sh":
                    info.external_attr = 0o100755 << 16  # keep scripts executable for Linux graders
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, f.read_bytes())
    log(f"wrote {zpath} ({zpath.stat().st_size / 1e6:.1f} MB)")
    v = _kit("validate_submission.py", str(zpath))
    log(v.stdout + v.stderr)
    return zpath
