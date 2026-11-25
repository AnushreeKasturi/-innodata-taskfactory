# Coding Task Factory: Track 1 submission

| Path | Contents |
|---|---|
| `pipeline/` | pipeline source at the submitted commit (see `pipeline/README.md` for full instructions) |
| `generated_tasks/` | the 5 Harbor packages, raw pipeline output with no hand edits |
| `pipeline_run.json` | per-task model, wall time, model calls, attempts and tokens |
| `evidence/selfcheck.txt` | harbor oracle and nop soundness table for every package |
| `evidence/check_structure.txt` | organiser structure lint output |
| `evidence/validation/<id>/` | our gate report per package: F2P/P2P, mutation results, provenance |
| `evidence/_llm_log.jsonl` | every model call (prompt, response, token usage), which backs `pipeline_run.json` |
| `evidence/SUMMARY.md` | category mix, files touched, requirement-text similarity |
| `WRITEUP.md` | variation strategy and team contributions |

## Reproduce
```bash
cd pipeline
# target repo
git clone https://github.com/pallets/click.git work/click && git -C work/click checkout -b base 8.5.1
python -m venv work/click/.venv
work/click/.venv/bin/python -m pip install -e work/click "pytest==9.2.0"     # Windows: .venv/Scripts/python

# model access (OpenAI-compatible endpoint): put these in .env or the environment
#   TF_LLM_API_KEY=...  TF_LLM_MODEL=...  TF_LLM_BASE_URL=...
python -m taskfactory generate --repo work/click --config configs/click.toml --base base -n 6 --target 5 --out out/click
python -m taskfactory export-harbor out/click --config configs/click.toml --dest submission/generated_tasks --limit 5
python -m taskfactory selfcheck submission/generated_tasks --out sc          # needs Docker + `uv tool install harbor`
python -m taskfactory bundle --team <TeamName>                               # writes dist/<TeamName>_Track1.zip
```
Requires Python ≥ 3.11 and git. The pipeline itself has no third-party dependencies. The target repo needs
`pytest==9.2.0`. Generation temperature defaults to 0.4, so reruns produce comparable but not identical tasks.
Every package can be re-checked on its own: `python -m taskfactory validate out/click/<id> --repo work/click --config configs/click.toml`.
