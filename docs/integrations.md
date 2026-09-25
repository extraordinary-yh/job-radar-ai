# Optional integrations

## career-ops

Core scanning works without Node. For optional ATS discovery, sponsorship datasets, connection joins, and liveness checks:

```bash
git submodule update --init
npm ci --ignore-scripts
uv run jobradar h1b --install
```

This is an optional external dependency. See `vendor/README.md`. Connection exports belong only under ignored `data/`.

## Reports and notifications

`config/publish.yaml` starts with empty destinations. Configure your own report repository and Pages URL, set `JOBRADAR_PASSPHRASE` locally, then use `jobradar publish` to inspect an encrypted build before `jobradar publish --push`. Use a strong passphrase: public ciphertext can be downloaded. No automatic publish workflow is enabled.

For Telegram, supply `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` locally. Inspect with `jobradar notify --dry-run` before sending. Report feedback writeback requires an explicit repository target and token; prefer local feedback or a private workspace repository.

## Study Planner AI

Set `JOBRADAR_ROOT` to this checkout in the planner's environment. It reads job snapshots and feedback locally; it does not submit applications or change scanner records.
