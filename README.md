# PatchPilot

PatchPilot is a Python 3.12 backend foundation for a bounded, reviewable
software-repair workflow. Day 1 provides configuration, a FastAPI application,
and health checks only. Later workflow features are intentionally not included.

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

The Day 1 tests are offline and do not call GitHub, Groq, Docker, or create a
database.
