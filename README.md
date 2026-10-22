# PatchPilot

PatchPilot is a Python 3.12 backend for a bounded, reviewable software-repair
workflow. The current implementation analyzes GitHub issues, proposes and
validates Python patches, generates deterministic diffs, and executes fixed
pytest commands in disposable Docker workspaces.

## Prerequisites

- Python 3.12
- PowerShell

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

## Sandbox image

Build the restricted test image from the repository root:

```powershell
docker build -f backend/sandbox/Dockerfile -t patchpilot-sandbox:latest .
```

The application never falls back to host test execution when Docker is
unavailable; it returns an explicit infrastructure error instead.
