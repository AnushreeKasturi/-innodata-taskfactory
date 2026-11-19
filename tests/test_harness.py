import copy
import json
import tomllib
from pathlib import Path

import pytest

from taskfactory.config import load_config
from taskfactory.edits import EditError, apply_edits
from taskfactory.generate import generate_one
from taskfactory.gitutil import rev_parse
from taskfactory.llm import extract_json
from taskfactory.mutate import generate_mutants
from taskfactory.package import build_patches
from taskfactory.sample import init_sample
from taskfactory.validate import validate

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "shopcart.toml")


def drafts(name: str) -> list[dict]:
    return tomllib.loads((ROOT / "drafts" / name).read_text(encoding="utf-8"))["tasks"]


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return init_sample(tmp_path_factory.mktemp("repo") / "shopcart")


# ---- unit -------------------------------------------------------------------

def test_mutants_target_only_added_lines():
    base = "def f(x):\n    return 1\n"
    final = "def f(x):\n    if x > 3:\n        return 2\n    return 1\n"
    muts = generate_mutants(base, final)
    descs = [m.description for m in muts]
    assert any("> -> >=" in d for d in descs)
    assert any("n -> n+1" in d and "x > 3" in d for d in descs)
    assert any(m.kind == "missing_behaviour" and m.text == base for m in muts)
    assert all("return 1`" not in d for d in descs)  # unchanged line is never mutated


def test_mutants_skip_comments_strings_and_imports():
    final = 'import os\n# if a < b\nx = "a < b"\n'
    assert [m for m in generate_mutants("", final) if m.kind == "wrong_behaviour"] == []


def test_apply_edits(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    apply_edits(tmp_path, [{"path": "a.py", "search": "y = 2\n", "replace": "y = 3\n"},
                           {"path": "pkg/new.py", "search": "", "replace": "z = 0\n"}])
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 3\n"
    assert (tmp_path / "pkg/new.py").exists()
    with pytest.raises(EditError, match="not found"):
        apply_edits(tmp_path, [{"path": "a.py", "search": "nope", "replace": ""}])
    with pytest.raises(EditError, match="invalid path"):
        apply_edits(tmp_path, [{"path": "../evil.py", "search": "", "replace": ""}])


def test_apply_edits_preserves_crlf(tmp_path):
    (tmp_path / "w.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    apply_edits(tmp_path, [{"path": "w.py", "search": "b = 2\n", "replace": "b = 5\nc = 6\n"}])
    assert (tmp_path / "w.py").read_bytes() == b"a = 1\r\nb = 5\r\nc = 6\r\n"


def test_extract_json_from_fenced_reply():
    assert extract_json('Sure!\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_test_file_classification():
    assert CFG.is_test("tests/test_cart.py")
    assert CFG.is_test("pkg/tests/helpers.py")
    assert CFG.is_test("src/cart.test.ts")
    assert not CFG.is_test("shopcart/cart.py")


def test_build_patches_rejects_misplaced_edits(repo):
    bad = copy.deepcopy(drafts("shopcart.toml")[1])
    bad["test_edits"][0]["path"] = "shopcart/test_helpers_in_src.txt"
    with pytest.raises(EditError, match="misplaced"):
        build_patches(repo, CFG, rev_parse(repo), bad)


# ---- integration: real test runs in throwaway worktrees ------------------------

def _validate(repo, draft, mutants=True):
    base = rev_parse(repo)
    src, tests = build_patches(repo, CFG, base, draft)
    return validate(repo, CFG, base, src, tests, draft["requirements"], mutants=mutants)


def test_good_draft_is_valid(repo):
    report = _validate(repo, drafts("shopcart.toml")[1])
    assert report["valid"], report["checks"]
    assert len(report["fail_to_pass"]) == 10
    assert len(report["pass_to_pass"]) == 18
    assert report["mutation"]["score"] >= CFG.mutation_threshold


def test_tests_that_ignore_the_feature_are_rejected(repo):
    report = _validate(repo, drafts("negative_examples.toml")[0], mutants=False)
    failed = {c["name"] for c in report["checks"] if not c["ok"]}
    assert not report["valid"]
    assert {"has_fail_to_pass", "new_tests_need_feature"} <= failed


def test_regressions_are_rejected(repo):
    report = _validate(repo, drafts("negative_examples.toml")[1], mutants=False)
    failed = {c["name"] for c in report["checks"] if not c["ok"]}
    assert not report["valid"]
    assert "no_regressions" in failed


class FakeLLM:
    """Replays canned replies: a broken first draft, then a repaired one."""
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_json(self, system, user, purpose=""):
        self.calls.append((purpose, user))
        return self.replies.pop(0)


def test_repair_loop_recovers_from_bad_edit(repo, tmp_path):
    good = drafts("shopcart.toml")[1]
    broken = copy.deepcopy(good)
    broken["source_edits"][0]["search"] = "this text is not in the file\n"
    llm = FakeLLM([broken, good])
    proposal = {"title": good["title"], "category": good["category"],
                "files_to_read": ["shopcart/catalog.py", "shopcart/cart.py"], "files_to_change": []}
    d = generate_one(llm, repo, CFG, rev_parse(repo), proposal, tmp_path, max_repairs=1, log=lambda s: None)
    meta = json.loads((d / "task.json").read_text())
    assert meta["valid"] and meta["provenance"]["attempts"] == 2
    assert [p for p, _ in llm.calls] == ["implement", "repair"]
    assert "search block not found" in llm.calls[1][1]  # the error was fed back to the model
