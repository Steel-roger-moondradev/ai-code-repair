# PatchPilot project and interview guide

## One-sentence description

PatchPilot is a bounded AI software-repair system that turns a GitHub issue
into a typed, validated, sandbox-tested, human-approved pull request.

## What the project does

PatchPilot accepts an HTTPS GitHub issue URL and runs a controlled workflow:

1. Fetch the issue and repository metadata.
2. Convert the issue into a structured problem analysis.
3. Retrieve a bounded set of relevant Python files with provenance and hashes.
4. Ask the model for a canonical typed patch proposal.
5. Validate paths, operations, original content, protected files, and patch size.
6. Generate a deterministic diff from trusted local content.
7. Apply the proposal only inside a disposable Docker workspace.
8. Run `python -m pytest -q` with no network access.
9. Ask a reviewer model to judge only the bounded evidence.
10. Wait for explicit human approval using the exact patch hash.
11. Create a workflow branch, commit the validated files, and open a PR.

The central design idea is that the model proposes, but deterministic code
validates, tests, persists, and publishes.

## Architecture

### API and contracts

FastAPI exposes health, GitHub, workflow, results, and approval endpoints.
Pydantic models define the canonical shapes for analysis, patch proposals,
validation, diffs, sandbox results, reviews, and workflow responses.

### Orchestration

LangGraph carries a shared `PatchPilotState` through explicit nodes. Status
transitions are centralized, terminal failures stop the graph, and repair
attempts are bounded.

### Repository safety

Repository access is rooted under `data/repositories`. File reads reject
traversal, symlink escapes, binary content, oversized files, and unsupported
paths. Patch validation never edits the source repository.

### Patch integrity

Every modification includes exact original content. The validator compares
that content with trusted repository evidence. A canonical SHA-256 patch hash
binds validation, diff, approval, and publication together.

### Sandbox

The proposed patch is applied to a disposable copy and tested in a separate
Docker container with no network, limited CPU/memory/processes, a read-only
workspace mount, and a fixed pytest command. The API never falls back to
running target code on the host.

### Persistence and audit

SQLite/SQLAlchemy stores workflow runs, bounded artifacts, statuses, patch
hashes, idempotency keys, and redacted audit events. Repeating an idempotency
key does not run a second workflow.

### Publication

Approval is a separate endpoint. The publisher uses a workflow-derived branch,
reads the current Git blob SHA before updating a file, and creates a PR. It
never writes directly to the default branch.

## Supported file scope

The current MVP is for small Python implementation changes:

- `.py` source files only.
- Usually one to a few files.
- Existing repositories with a reproducible `pytest` suite.
- No network or external service dependency during tests.
- No edits to tests, configuration, secrets, docs, CI, binaries, or generated
  files.

It is a good fit for a calculator bug, parser bug, validation bug, or small
pure-Python helper change. The demo target's divide issue is intentionally
representative.

## Explicit limitations

The MVP does not yet support JavaScript/TypeScript, frontend builds,
dependency-aware sandbox setup, arbitrary test commands, migrations, database
changes, documentation/configuration patches, or multi-language repositories.
It cannot rotate a cloud credential; an operator must revoke and replace
external secrets. It is not a replacement for a senior engineer, a full CI
system, or a security approval process.

A Chatbot issue asking for `.env.example`, documentation, secret rotation,
provider timeouts, and external API behavior is broader than this MVP. The
safe behavior is to reject or escalate it, not to loosen path validation.

## Why this is a strong AI engineering project

This is stronger than a basic chatbot demo because the model is inside a
verifiable software workflow. The project demonstrates:

- Structured output contracts instead of unbounded text.
- Retrieval grounded in repository evidence.
- Prompt-injection-aware boundaries.
- Exact content and hash verification.
- Sandboxed execution with explicit resource limits.
- Bounded retries and terminal failure handling.
- Human-in-the-loop approval.
- Idempotent side effects and audit history.
- A real GitHub integration and a working PR.

The strongest recruiter proof is the successful demo sequence:
GitHub issue -> evidence -> typed proposal -> deterministic diff -> Docker
tests -> reviewer -> approval -> PR.

## Resume wording

### AI engineering version

**PatchPilot — AI-assisted software repair workflow**

- Built a FastAPI/LangGraph system that converts GitHub issues into typed,
  evidence-grounded Python patch proposals and deterministic diffs.
- Added exact-content SHA-256 validation, prompt-injection-aware repository
  retrieval, bounded repair loops, and structured failure handling.
- Executed candidate patches in a network-isolated Docker sandbox and required
  human approval before idempotent GitHub PR publication.
- Added SQLite audit history, Pydantic contracts, offline test doubles, and a
  React/Vite mission-control console.

### Full-stack version

**PatchPilot — Full-stack AI code repair console**

- Developed a FastAPI backend with typed workflow APIs, GitHub integration,
  LangGraph orchestration, SQLite persistence, and Docker-based validation.
- Built a responsive React/Vite console for issue intake, live workflow stages,
  evidence review, diff inspection, patch-hash approval, and PR creation.
- Designed secure boundaries for path validation, secret redaction, CORS,
  idempotency, protected files, and human-controlled publishing.

## Interview questions and defensible answers

### Why not let the LLM edit files directly?

Because model output is untrusted. The model returns a typed proposal, while
deterministic validators enforce allowed paths, exact original content,
protected-file rules, size limits, and patch hashes.

### How do you prevent stale patches?

The proposal carries exact original content and trusted evidence hashes. The
validator compares the current repository content before sandboxing. Approval
also requires the exact persisted patch hash.

### How do you prevent code execution on the API host?

The API copies the repository into a disposable workspace and executes tests
only through a separate restricted Docker runner. If Docker is unavailable,
the workflow reports an infrastructure error rather than using a host
fallback.

### What happens if the model returns invalid JSON?

The node fails closed with a typed error. Narrow compatibility adapters handle
only known provider shapes; arbitrary malformed output is rejected.

### How do you handle prompt injection in an issue or source file?

Repository and issue text is treated as evidence, not instructions. Prompts
state this boundary, retrieval is bounded, and publication still requires
deterministic validation and human approval.

### Why is human approval required?

An automated test pass is evidence, not authorization. Approval creates an
explicit control point before any GitHub write.

### What would you build next?

Add dependency-manifest detection, project-specific test commands, safe
support for documentation/configuration changes, stronger secret scanning,
multi-language adapters, asynchronous job workers, webhooks, richer PR
comments, and deployment-level authentication/authorization.

## Honest project assessment

For an AI engineering resume, this is a strong portfolio project because it
shows practical LLM systems engineering, reliability, security boundaries, and
evaluation—not just prompt calling. For full-stack engineering, it is also
strong because it has a real API, persistence, frontend, external integration,
and end-to-end UX.

Its credibility depends on presenting the scope honestly: call it a
Python-only MVP, show the successful PR, show the safe failure, explain the
limitations, and do not claim production readiness or arbitrary repository
support.
