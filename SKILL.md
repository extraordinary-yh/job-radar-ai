---
name: job-radar-ai
description: Configure job searches, run scans, review fit from verified experience, and record feedback.
---
# Job Radar AI agent workflow

## Session start
Read AGENTS.md, local preferences, experience, resume, feedback, and `uv run jobradar status`.
On first use, run the initializer and help the user replace fictional examples. Ask for missing constraints; never infer eligibility or credentials.

## Daily run
Run `uv run jobradar run`. Report failures explicitly. Read the candidate file, perform fit review, then re-render.
Give the user a clickable path to `reports/<date>.html` and explain top matches with concrete evidence.
A generated report is local; do not claim publishing occurred without checking the destination.

## Fit review
Compare each posting to actual experience, not just keywords. Skills is 0–40: 36–40 for demonstrated core work,
26–35 for strong overlap with one gap, 16–25 for transferable experience, 6–15 for weak overlap, 0–5 for none.
Do not double-penalize years of experience. Record unknowns honestly. Only use IDs from the candidate file.
Write `data/reviews/<date>.json`:
```json
{"date":"YYYY-MM-DD","reviews":[{"id":"company:123","skills":30,"yoe_match":"match","experience_match":"strong","reason":"Relevant API ownership; domain experience is unverified.","gaps":["domain knowledge"],"tags":["backend"]}]}
```
Run `uv run jobradar render --date YYYY-MM-DD --review data/reviews/YYYY-MM-DD.json`.
Review the rendered explanation. Scores are preferences, not hiring probabilities.

## Feedback
Use `uv run jobradar serve` for the local board at `http://127.0.0.1:8766/`. Wait for “Saved on this computer” after a change. Failed saves retain a recoverable draft; retry instead of assuming persistence. A static report keeps drafts until imported.
Record user verdicts with `jobradar feedback`. Change ranking rules only from actual preferences.
Run `uv run jobradar eval` before and after a ranking change. Save the reason locally.
Record applied status only after a confirmed submission. Never apply or send outreach as part of a scan.

## Add a company
Add public board configuration in `config/companies.yaml`. Use an existing adapter when possible.
For a new parser, add a small public or synthetic fixture and a regression test. Never save authenticated responses.

## Repair an adapter
Reproduce with `uv run jobradar run --company KEY`. Inspect ignored raw responses, repair the parser,
run its tests, and repeat the affected live fetch. Do not silently hide failures.

## Session end
Verify changes with `uv run pytest -q`; inspect the report and give the local link.
Keep profile, records, and report output local. Run the privacy check before publishing code.
