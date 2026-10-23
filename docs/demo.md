# Controlled demo procedure

This procedure is safe to run against a repository and GitHub account that you
control. It is not a claim that a live PR was created for this workspace.

## Success path

1. Create `.env` from `.env.example` and provide only the required controlled
   GitHub/Groq credentials.
2. Apply migrations:

   ```powershell
   $env:PYTHONPATH = "backend"
   python -m alembic upgrade head
   ```

3. Start the API and verify `GET /health`.
   For the sandboxed success path, ensure Docker is available and the
   restricted sandbox image has been built; the API never runs target tests on
   the host as a fallback.
4. Submit a known Python issue using the workflow request shown in the
   README.
5. Read the returned `workflow_id`, poll the workflow, and inspect its persisted analysis, relevant-file
   evidence, typed proposal, validation result, deterministic diff, sandbox
   result, and reviewer result.
6. Copy the exact `patch_hash` from the proposal and submit it to the approval
   endpoint.
7. Verify the returned pull-request artifact and audit event. Never use a
   token in a request body or log capture.

The automated suite verifies this sequence with mocked GitHub publication and
does not require a live write.

## Safe-failure path

Use a malformed proposal, a traversal path such as `../outside.py`, or a fake
sandbox timeout. Expected behavior is a typed validation/infrastructure
failure, no successful terminal status, and no pull-request artifact. The
existing tests cover each case without executing target code on the host.

## Evidence and redaction

Capture only `/health`, bounded API responses, status transitions, and safe
structured logs. Redact tokens, private repository names, source snapshots,
environment values, and unbounded model output before sharing evidence.
