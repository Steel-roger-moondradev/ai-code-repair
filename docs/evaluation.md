# PatchPilot evaluation

The repeatable fixture corpus is under
`backend/tests/fixtures/evaluation/`. Each case contains an `issue.json`,
synthetic Python source, and an `expected.json` outcome. Fixtures contain no
real repositories, credentials, or private data.

The evaluation test measures actual fixture outcomes for:

- Fixture coverage.
- Expected terminal-state agreement.
- Patch-validation rejection rate.
- Proposal schema validity.
- Safe-failure count.
- End-to-end fixture execution time.

The full unit suite separately covers retrieval, sandbox behavior, repair
success, reviewer decisions, approval gates, stale hashes, idempotency, URL
validation, traversal, symlink handling, oversized requests, provider errors,
and malformed model output.

These metrics are local test measurements, not production reliability claims.
Live GitHub, Groq, and Docker execution remains unverified unless explicitly
run with controlled credentials and infrastructure.
