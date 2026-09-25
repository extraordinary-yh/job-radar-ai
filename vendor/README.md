# Vendored dependencies

## career-ops (`vendor/career-ops`)

[career-ops](https://github.com/career-ops-hq/career-ops) by Santiago Fernández de
Valderrama and contributors, MIT license (see `vendor/career-ops/LICENSE`). Pinned as a
git submodule to the tag `career-ops-v1.32.0`; upgrade deliberately:

```bash
cd vendor/career-ops && git fetch --tags && git checkout career-ops-v1.33.0 && cd ../.. && git add vendor/career-ops
```

job-radar calls a handful of its zero-token scripts from `jobradar/careerops.py` and
never runs its evaluation, CV, tracker, or dashboard code:

| Script | Used for |
|---|---|
| `plugins/h1b-sponsor/check.mjs` | H-1B / PERM filing tier per company from the DOL index |
| `linkedin-join.mjs` | first-degree LinkedIn connections at target companies (offline join of `Connections.csv`) |
| `liveness-api.mjs` | ATS API liveness rung for applied postings (no browser) |
| `detect-reposts.mjs` | repost clusters from our own seen history |
| `providers/*.mjs` | job sources behind the `careerops` adapter |
| `discover-ats.mjs` | resolve company names to scannable ATS boards |
| `jd-skill-gap.mjs` | JD keyword coverage against the rendered resume |

Their only npm dependency we need is `js-yaml`, installed from the repo root with
`npm ci --ignore-scripts` (their own `postinstall` would download a Chromium build we do not use).
The data root for these scripts is `data/careerops/` (set via `CAREER_OPS_ROOT`), so the
submodule checkout stays clean. The name "career-ops" is their trademark; job-radar does not
present itself as career-ops.
