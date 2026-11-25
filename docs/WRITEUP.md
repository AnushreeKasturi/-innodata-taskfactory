# Variation strategy: Coding Task Factory (Track 1)

**Repository:** `pallets/click` at 8.5.1 (`cf19179e8e2fd54c601378cec9e0d21bb12b6fb1`). **Output:** Harbor task packages.

## 1. The problem with "generate 5 tasks"
If you ask a model for five feature ideas for a CLI library, you get five variations of one idea: a new
option type, another option type, a third option type. The renaming changes, but the behaviour being tested
stays the same. This pipeline treats variation as a constraint it enforces at three points: what gets
proposed, what survives validation, and which five are submitted.

## 2. Axes the pipeline moves along
Every proposal must state a value for each of the brief's four axes. The proposal prompt shows the current
batch and every task already generated, and requires that new proposals differ on several axes.

| Axis | Values offered to the proposer (Click-specific) |
|---|---|
| **Capability:** which part of Click's job is extended | parsing, types/conversion, help/formatting, context/state, invocation/dispatch, testing utilities (`CliRunner`), shell completion |
| **Behavioural shape:** what kind of change | validation/rejection, value transformation, new output, ordering/precedence rule, state transition, error reporting |
| **Integration depth:** how much of the code it touches | a single function, one class plus its callers, or across two or more modules |
| **Interaction rules:** what it must combine with | defaults, environment variables, `multiple=True`, clamping, prompts, command chaining, … |

On top of the axes, each proposal belongs to one of seven **behaviour categories**:

- business rule
- validation
- state interaction
- query/aggregation
- configuration
- lifecycle
- error handling

The categories steer the kind of logic: "a new option that changes existing behaviour with a backward-compatible default" is a different engineering problem from "graceful handling of a currently unhandled failure mode". The prompt asks for a different category per proposal where possible.

Why this gives substantive rather than cosmetic variation: two tasks that differ in capability *and*
behavioural shape exercise different modules, different test strategies and different failure modes for
the solver. A rename cannot satisfy that constraint.

## 3. How the pipeline decides what to generate
1. **Grounding.** The proposer sees a map of the repository at the base commit: modules, public classes and
   functions, and their docstrings. It must name existing files to change. The `grounded` gate rejects
   tasks whose reference implementation only adds new files without extending existing modules.
2. **Novelty against live upstream.** The prompt includes the subject of every upstream commit after the base
   commit (`8.5.1..origin/main`), with the instruction not to overlap any of them. After generation, the
   `novel_vs_upstream` gate parses every name the reference defines and fails the task if upstream `main`
   already defines it in the same file.
3. **Hardness by construction.** Proposals must list 4–8 concrete rules, including precedence between the
   new feature and existing options, boundary cases and error behaviour. Several interacting rules are
   where hurried implementations go wrong. This is what we expect to make the benchmark model fail without
   making the task unfair.
4. **De-duplication.** A new proposal is dropped if its title and summary are more than 75% similar to an
   existing or already-kept task.
5. **Generate until enough are valid** (`generate --target 5`). Rejected drafts are kept with their reasons
   (`_rejected/`). They show up in reliability, and the repair loop is visible in `attempts`.
6. **Pick the most different five** (`export-harbor --limit 5`). From all valid packages, the pipeline chooses
   the five that maximise the *minimum* pairwise distance. That distance combines four things:
   - whether the category differs
   - how different each axis value is
   - the overlap of source files touched (Jaccard)
   - how dissimilar the requirement texts are

   Maximising the minimum distance stops one near-duplicate pair from slipping in.

## 4. Why the tasks stay fair as they get harder
Variation and hardness only count if each task is still a fair test. Every package passes these gates
before export, each run against real Click tests in throwaway git worktrees:

| Gate | What it guarantees |
|---|---|
| base suite runs | the environment is healthy at `base_commit` |
| fail_to_pass | new tests fail at base (tests that already passed at base are excluded) |
| reference passes, twice | the gold scores 1.0 and the result is deterministic |
| no_regressions + curated P2P | the 4 existing test files most related to the change (IDF-weighted name overlap) stay green |
| mutation score ≥ 0.6 | when one hunk of the reference is reverted, or one operator/boundary/constant is flipped, the tests notice; mutants that only break imports are not counted |
| interface_disclosed | every new name the tests call appears in the requirements, so the spec is implementable blind |
| hygiene | no authoring or AI giveaways in any file the solver or grader sees |

Tests are written against observable behaviour only: return values, exception types, output text and exit
codes through Click's public API and `CliRunner`. Every asserted string must also appear in the
requirements. When a gate fails, the failure text (failing test ids, surviving mutants, missing names)
goes back to the model for repair, up to 2 rounds.

## 5. What is working, and what is not finished
- **Working:**
  - Generation, validation, repair, Harbor export (lint-clean), diverse selection, the self-check runner
    and submission bundling.
  - 12 harness tests.
  - The end-to-end path on Click, verified with a hand-written smoke draft.
- **Evidence in this ZIP:**
  - `evidence/selfcheck.txt` (harbor oracle and nop results per package)
  - `evidence/validation/` (our gate reports and mutation results)
  - `evidence/_llm_log.jsonl`, which logs every model call with token usage and backs `pipeline_run.json`
  - `evidence/SUMMARY.md` (category mix, files touched, text similarity)
- **Limitations:**
  - Some mutants cannot change behaviour, hence the 0.6 threshold.
  - The interface check works on tokens, so it warns rather than rejects.
  - Novelty is checked against names defined upstream, not semantics. The proposer's view of the upstream
    log covers the semantic side.

## 6. Team contributions
| Member | Contribution |
|---|---|
| _name_ | _fill in_ |
| _name_ | _fill in_ |
| _name_ | _fill in_ |
