# Configure your scanner

1. Run `uv sync` and `uv run python scripts/init_workspace.py`.
2. Edit `profile/preferences.yaml`: candidate experience, title patterns, locations, skill weights, experience caps, exclusions, and salary floor. The default is a fictional early-career software profile, not a universal recommendation.
3. Replace `profile/resume.md` and `profile/experience.md` with your own evidence. Keep contact details out of these ranking documents.
4. Edit `config/companies.yaml`. Greenhouse, Lever, and Ashby use public board slugs. Other adapters have query/location settings. Start with a few companies.
5. Run `uv run jobradar run`. Open `reports/index.html` with `uv run jobradar open`.
6. Ask your agent to review `data/candidates/<date>.json`, save fit reviews to `data/reviews/<date>.json`, and re-render with `uv run jobradar render --date YYYY-MM-DD --review data/reviews/YYYY-MM-DD.json`.

Feedback: `uv run jobradar feedback add --job company:id --verdict good --note "why"`. For an actual submission, use `uv run jobradar feedback stage --job company:id --stage applied`. Preparing a resume is not a submission. `uv run jobradar eval` checks ranking against your verdicts.

The deterministic score works without a model. Until reviewed, the skills score is a keyword estimate. An agent review replaces only that component; experience and other constraints remain separate.

## Saving board

After a scan, run `uv run jobradar serve` and open `http://127.0.0.1:8766/`. Selections and stage changes save to the local ledger; wait for **Saved on this computer**. Old static-report drafts can be pasted into the recovery box and retried. The server binds to loopback and requires a per-server token for writes.

Starter publishing settings use `feedback_mode: local`, `local_board_url: http://127.0.0.1:8766/`, and an empty `pinned_jobs` list. Existing workspaces can add these to `config/publish.yaml`. Set pins to real job IDs from your own snapshots.

An optional macOS login service is available with `uv run python scripts/install_local_board.py`; run it only if you want a persistent service. Other systems can keep `jobradar serve` running manually.

The career-ops Eightfold adapter now reads structured posting descriptions and dates. Netflix level and Los Gatos normalization are covered by fixtures; configure boards for your own search.
