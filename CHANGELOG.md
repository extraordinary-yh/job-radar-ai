# Changelog

## 2026-10-14

- Added persistent local feedback, recovery, pinned jobs, historical application metadata, and Eightfold/Netflix parsing updates.
- Preserved independent setup and fictional examples; excluded personal profiles, records, session content and private history.
- Expanded privacy checks to untracked files, new private state directories and symlinks.

## 0.1.0

- Initial independent public template, with fresh history, fictional examples, a local demo, an agent runbook, and private workspace defaults.
- Extracted reusable functionality and tests; removed predecessor profiles, records, deployment targets, and machine paths.
- Verification results are recorded in docs/verification.md.

Validation: full local suite and clean staged-file export; 270 passed, 5 optional sidecar tests skipped; all 275 pass with the sidecar installed. Offline demo and screenshot inspection passed. Gitleaks and private-identifier checks returned zero findings.
