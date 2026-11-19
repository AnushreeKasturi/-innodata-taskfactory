# Coding Task Factory

Innodata AI Hackathon, Track 1. Turns a working repository into **feature-development task
packages** for evaluating AI coding systems. It also proves that each package is solvable and
that its tests actually check the feature.

```
repo @ base commit
   │
   ├─ propose ──► diverse feature ideas (forced across 7 behaviour categories, near-duplicates dropped)
   │
   ├─ implement ─► requirements.md + reference implementation + hidden tests (search/replace edits)
   │
   ├─ validate ──► 1. original suite runs                     (baseline)
   │               2. tests WITHOUT the feature  → must fail   (fail_to_pass)
   │               3. tests WITH the reference   → all pass, twice (no regressions, deterministic)
   │               4. mutants of the reference   → tests must catch them
   │               5. every new name the tests use is stated in the requirements
   │
   ├─ repair ────► failures (edit errors, failing tests, surviving mutants) go back to the model
   │
   └─ package ───► out/<task-id>/  task.json · requirements.md · reference.patch · tests.patch · validation.json
                   rejected drafts → out/_rejected/ with the reason
```

## Why these checks
| Judging criterion | How it is evidenced |
|---|---|
| Working, repeatable | `validate` re-runs any package from its patches in a fresh git worktree |
| Validity | fail→pass and pass→pass sets come from real test runs. A test that passes without the feature is flagged. A package with any regression is rejected |
| Tests catch wrong code | Mutation testing on the lines the reference added. *Missing behaviour* = revert one hunk. *Wrong behaviour* = flip one operator/constant/boundary. Mutants that only break the build are reported separately and not counted |
| Meaningful variation | Proposals are forced across categories (business rule, validation, state interaction, aggregation, configuration, lifecycle, error handling). `SUMMARY.md` reports the category mix, files touched and how similar the requirement texts are |
| Fair tasks | The interface check fails a task whose tests call new names the requirements never mention |

## Quick start
```bash
python -m taskfactory init-sample work/shopcart            # stand-in repo until the official one is out

# offline: validate the hand-written example drafts (no model needed)
python -m taskfactory drafts drafts/shopcart.toml --repo work/shopcart --config configs/shopcart.toml --out out/tasks

# with a model (any OpenAI-compatible endpoint; see .env.example)
export TF_LLM_API_KEY=... TF_LLM_MODEL=... TF_LLM_BASE_URL=...
python -m taskfactory generate --repo work/shopcart --config configs/shopcart.toml -n 5 --out out/tasks

python -m taskfactory validate out/tasks/<task-id> --repo work/shopcart --config configs/shopcart.toml
python -m taskfactory report out/tasks
```
Needs only Python ≥ 3.11 and git. The target repo needs its own test toolchain.

## Adapting to a new repository
Write a config TOML. The only required key is `test_cmd`, which must write JUnit XML to `{junit}` and
accept test files in `{tests}`:
```toml
[repo]
test_cmd = "python -m pytest -q -p no:cacheprovider --continue-on-collection-errors --junitxml={junit} {tests}"
# test_cmd = "npx jest --ci --reporters=default --reporters=jest-junit {tests}"   # with JEST_JUNIT_OUTPUT_FILE={junit}
setup_cmd = "pip install -e ."   # run once in each fresh checkout
```

## Transparency
- Every model call is logged to `out/<dir>/_llm_log.jsonl` (prompt, response, token usage).
- `task.json → provenance` records the generator (`llm` or `manual-draft`), model, number of
  repair attempts, and whether a human edited the package.
- Known limitations:
  - Some mutants are *equivalent* (they can't change behaviour), so the threshold is 0.6, not 1.0.
  - The interface check is token-based, so it reports warnings rather than rejecting tasks.
  - Mutation operators are text-level. They work across languages but are tuned for C-like and Python syntax.

## Layout
`taskfactory/` holds the pipeline (`validate.py` is the core), `drafts/` holds hand-written example and
must-reject drafts, `examples/shopcart/` is the stand-in repo, and `tests/` is the harness's own test suite.
