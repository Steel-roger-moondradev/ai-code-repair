# PatchPilot

PatchPilot is a Python 3.12 backend for a bounded, reviewable software-repair
workflow. The current implementation analyzes GitHub issues, proposes and
validates Python patches, generates deterministic diffs, and executes fixed
pytest commands in disposable Docker workspaces.

This is a Python-only MVP. It does not claim cross-language support,
production-grade security, high throughput, or verified live pull-request
creation.

## MVP scope: what files it supports

PatchPilot is designed for small, reviewable changes in Python repositories.
The supported success path is:

- An HTTPS GitHub **issue** URL.
- A checked-out Python repository under `data/repositories/<owner>/<repo>`.
- Existing `.py` source files, normally with a small `pytest` suite.
- A patch that creates or modifies up to the configured number of Python files.
- A fixed, offline Docker test command: `python -m pytest -q`.
- Human approval before a branch, commit, and pull request are published.

The patch security boundary intentionally allows only `.py` paths. It rejects
absolute paths, traversal, symlinks, duplicate paths, test files, test
directories, and project configuration files such as `pyproject.toml`,
`setup.py`, and `conftest.py`. This makes the MVP appropriate for isolated
implementation bugs such as the calculator demo, not arbitrary repository
maintenance.

### Files and projects that are outside the MVP contract

The current release does **not** reliably support:

- JavaScript, TypeScript, Java, Go, Rust, or other non-Python source changes.
- `.env`, `.env.example`, YAML, TOML, JSON, Markdown, Dockerfile, or CI edits.
- Issues requiring dependency installation, migrations, database changes, or
  frontend builds.
- Projects without a reproducible `pytest` command.
- Tests that need network access, cloud credentials, paid APIs, or services
  outside the sandbox.
- Secret rotation. PatchPilot can remove a secret from source, but revoking
  and replacing the external credential must be done by an operator.
- Large refactors, broad multi-module redesigns, binary files, generated
  artifacts, or changes to protected tests/configuration.

For a broader issue, PatchPilot should fail closed or request human review;
do not weaken the validator to make an unsupported issue pass. See the full
scope and interview guide in
[`docs/project-guide.md`](docs/project-guide.md).

## Architecture

```text
GitHub issue URL
        |
        v
FastAPI request -> LangGraph PatchPilotState
        |                  |
        |                  +--> issue analysis -> repository retrieval
        |                                         |
        |                                         v
        |                              typed patch -> validation -> diff
        |                                                        |
        |                                                        v
        |                                      separate Docker sandbox
        |                                                        |
        |                                                        v
        |                                      evidence reviewer -> approval
        |                                                        |
        +---------------- SQLite history/audit <----------------+
                                                                 |
                                                                 v
                                                     idempotent GitHub PR
```

The shared state in `backend/app/agents/state.py` and the Pydantic schemas in
`backend/app/schemas/` are the canonical output contracts. Nodes return
typed, bounded results; persistence stores serialized artifacts and audit
events.

## Technology choices

- FastAPI and Pydantic provide typed HTTP boundaries and validation.
- LangGraph provides explicit node transitions and bounded repair routing.
- HTTPX provides injectable, offline-testable GitHub access.
- Exact retrieval is deterministic and repository-scoped; optional semantic
  retrieval is isolated behind a provider interface.
- SQLAlchemy and Alembic provide SQLite history and explicit migrations.
- Docker is used as a separate, restricted test runner rather than executing
  target code in the API process.

## Prerequisites

- Python 3.12
- PowerShell

The API image is pinned to `python:3.12-slim`. The local verification
environment for this workspace used Python 3.14.3 because Python 3.12 was not
installed; the container build and smoke test use the documented Python 3.12
runtime.

## Setup

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

The application does not require GitHub or Groq credentials to start. Keep
`.env` local and never commit secrets.

## Frontend console

The React/Vite console lives in `frontend/`. It is a mission-control view of
the same workflow: launch an issue analysis, watch the evidence stages, inspect
the deterministic diff, and approve a passing patch before PR publication.

Run the API first, then start the frontend from a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/health` to the local
FastAPI server on port 8000. For a deployed frontend, configure the API origin
and allow that origin through `CORS_ALLOWED_ORIGINS`.

## Run

```powershell
$env:PYTHONPATH = "backend"
python -m uvicorn app.main:app --app-dir backend --reload
```

The API is available at `http://127.0.0.1:8000`. Open `/health` and `/docs`.

## Test

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -v
```

The automated tests are offline and use fakes for GitHub, Groq, Docker, and
repository operations.

## Workflow history

Workflow runs and bounded artifacts are stored in the configured SQLite
database. Apply the tracked schema migration with:

```powershell
$env:PYTHONPATH = "backend"
python -m alembic upgrade head
```

History endpoints:

- `GET /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}`
- `GET /api/v1/workflows/{workflow_id}/proposal`
- `GET /api/v1/workflows/{workflow_id}/results`
- `POST /api/v1/workflows/{workflow_id}/approve`

Create a workflow:

```powershell
$body = @{
  issue_url = "https://github.com/octo/repo/issues/42"
  idempotency_key = "demo-42"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/workflows `
  -ContentType "application/json" -Body $body
```

Poll the returned `workflow_id` with
`GET /api/v1/workflows/{workflow_id}`. Approval requires the persisted patch
hash from `GET /api/v1/workflows/{workflow_id}/proposal`; no PR is created
without the explicit approval request.

Approval requires the exact current `expected_patch_hash` from the persisted
validated proposal. The server creates a workflow-derived branch and publishes
only validated Python changes; it never writes directly to the default branch.

Workflow creation uses `POST /api/v1/workflows` and accepts an optional
`idempotency_key`. Repeating a request with the same key returns the original
workflow ID without executing a second workflow. The legacy
`POST /api/v1/workflows/issue-analysis` path maps to the same handler.
Requests include an `X-Request-ID` response header; callers may provide their
own request ID using the same header.

## Sandbox image

Build the restricted test image from the repository root:

```powershell
docker build -f backend/sandbox/Dockerfile -t patchpilot-sandbox:latest .
```

The application never falls back to host test execution when Docker is
unavailable; it returns an explicit infrastructure error instead.

## Containerized API

The root `Dockerfile` builds a minimal non-root API image. It excludes `.env`,
repositories, workspaces, indexes, local databases, tests, and documentation
from the image through `.dockerignore`. For local API development:

```powershell
Copy-Item .env.example .env
docker compose build
docker compose up
```

The Compose service persists only the application data volume and deliberately
does not mount the host Docker socket. The sandbox remains a separate
container launched through the configured runner; Docker-in-Docker and
production socket access are not assumed to be safe or supported. If Docker
execution is unavailable, workflow execution reports a sandbox infrastructure
error rather than running target tests on the API host.

Set `CORS_ALLOWED_ORIGINS` to a comma-separated allowlist of exact origins when
browser access is required. It is empty by default, so cross-origin access is
disabled. Configure secrets through the deployment environment or an ignored
`.env` file, never in Compose YAML.

## Verification and limitations

The verified local baseline is documented in
[`docs/evaluation.md`](docs/evaluation.md). Automated tests use offline fakes
for external services. A controlled success demo and a safe-failure demo are
documented in [`docs/demo.md`](docs/demo.md); live GitHub writes, hosted
deployment, and provider capability are intentionally not claimed unless
executed with controlled infrastructure.
