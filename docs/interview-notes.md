# Technical interview notes

## Workflow state

LangGraph nodes exchange the single `PatchPilotState` TypedDict. Pydantic
models define issue data, analysis, patch proposals, validation, diffs,
sandbox results, reviews, approval requests, and API responses. Status changes
are centralized so a failed infrastructure or test stage cannot become
successful.

## Retrieval and provenance

Exact search is deterministic and repository-scoped. Results are bounded by
file size, result count, and context size and include path and line
provenance. Semantic retrieval is optional and does not replace the exact
fallback.

## Patch integrity

Patch proposals are strict typed models. Validation rejects unsafe paths,
symlinks, duplicate files, protected tests/configuration, content mismatches,
oversized patches, and unsupported operations. The canonical SHA-256 hash is
calculated from normalized proposal data and is required again for approval.
Diffs are generated locally and the source repository is not modified.

## Execution and repair

Tests run only through the fixed Docker runner in a disposable workspace with
no network, credentials, host socket, or host execution fallback. Reviewer
evidence controls a bounded repair loop; retrying regenerates and revalidates
the complete patch rather than mutating an approved artifact.

## Persistence and idempotency

SQLite stores workflow runs, bounded artifacts, and audit events. Alembic
migrations define the schema. Request idempotency prevents duplicate workflow
creation, while PR publication checks existing artifacts before retrying a
write.

## Trade-offs

The MVP supports Python repositories only. SQLite is suitable for local
demonstration, not high-concurrency deployment. Docker is defense in depth,
not a perfect arbitrary-code boundary. Live provider behavior and hosted
deployment require separate controlled verification.
