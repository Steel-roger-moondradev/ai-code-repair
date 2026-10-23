# PatchPilot security boundary

PatchPilot v1 accepts only exact HTTPS GitHub issue URLs and only changes
validated Python paths. Issue text, comments, source files, test output, and
model output are untrusted data; they cannot authorize tools or override
workflow policy.

## Controls

- Repository paths are root-contained, traversal-checked, symlink-checked, and
  bounded.
- Patch proposals use strict Pydantic schemas, exact original-content matching,
  protected test/config paths, file limits, byte limits, and deterministic
  SHA-256 hashes.
- Validation does not write to the source repository.
- Sandbox execution uses a disposable copy, a fixed `python -m pytest -q`
  command, no network, bounded resources, no shell, no credentials, and no
  Docker socket.
- Workflow requests have bounded issue URLs and request bodies, persisted
  idempotency keys, explicit status transitions, and bounded pagination.
- Human approval requires the exact current patch hash. Pull requests use a
  workflow-derived branch and never target the default branch directly.
- Logs contain workflow IDs, node names, statuses, durations, and safe error
  categories only. Tokens, raw environments, source snapshots, and model
  output are not logged.

## Limitations

Docker is defense in depth, not proof that arbitrary code is perfectly safe.
The host Docker daemon remains a privileged infrastructure dependency and
should be isolated from public API deployments. GitHub write tests are mocked
in this repository; live credentials and repository permissions are not
verified. SQLite is intended for the local MVP, not high-concurrency
multi-instance deployment.
