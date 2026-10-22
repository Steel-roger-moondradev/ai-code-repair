"""SQLite persistence for workflow runs, bounded artifacts, and audit events."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import AuditEvent, Base, WorkflowArtifact, WorkflowRun
from app.schemas.workflow import WorkflowStatus, transition_status

SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)
ALLOWED_ARTIFACTS = {"proposal", "diff", "validation", "sandbox_result", "review", "pull_request"}


class PersistenceError(RuntimeError):
    """Raised for explicit workflow persistence failures."""


class PersistenceService:
    """Short-lived-session repository for restart-safe workflow history."""

    def __init__(self, settings: Settings | None = None, *, database_url: str | None = None):
        self.settings = settings or get_settings()
        url = database_url or self.settings.database_url
        if not url.startswith("sqlite:///"):
            raise PersistenceError("only SQLite database URLs are supported")
        database_path = url.removeprefix("sqlite:///")
        if database_path != ":memory:":
            path = Path(database_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def create_run(
        self,
        workflow_id: str,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        now = _now()
        run = WorkflowRun(
            id=workflow_id,
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            status=WorkflowStatus.QUEUED.value,
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
        )
        try:
            with self.session_factory.begin() as session:
                session.add(run)
                session.add(
                    AuditEvent(
                        workflow_id=workflow_id,
                        event_type="workflow_created",
                        metadata_json=_json({"stage": "create"}),
                        created_at=now,
                    )
                )
        except SQLAlchemyError as exc:
            raise PersistenceError("workflow creation failed") from exc
        return self.get_run(workflow_id)

    def find_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            run = session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.idempotency_key == idempotency_key
                )
            )
            if run is None:
                return None
            return _run_payload(run, [], [])

    def update_status(
        self,
        workflow_id: str,
        target: WorkflowStatus,
        *,
        patch_hash: str | None = None,
        stage: str = "workflow",
    ) -> dict[str, Any]:
        try:
            with self.session_factory.begin() as session:
                run = session.get(WorkflowRun, workflow_id)
                if run is None:
                    raise PersistenceError("unknown workflow ID")
                current = WorkflowStatus(run.status)
                if current != target:
                    transition_status(current, target)
                run.status = target.value
                run.updated_at = _now()
                if patch_hash is not None:
                    run.patch_hash = patch_hash
                session.add(
                    AuditEvent(
                        workflow_id=workflow_id,
                        event_type="status_changed",
                        metadata_json=_json({"stage": stage, "status": target.value}),
                        created_at=_now(),
                    )
                )
        except PersistenceError:
            raise
        except (SQLAlchemyError, ValueError) as exc:
            raise PersistenceError("workflow status update failed") from exc
        return self.get_run(workflow_id)

    def save_artifact(
        self,
        workflow_id: str,
        artifact_type: str,
        payload: Any,
        *,
        patch_hash: str | None = None,
    ) -> None:
        if artifact_type not in ALLOWED_ARTIFACTS:
            raise PersistenceError("unsupported artifact type")
        try:
            with self.session_factory.begin() as session:
                if session.get(WorkflowRun, workflow_id) is None:
                    raise PersistenceError("unknown workflow ID")
                session.add(
                    WorkflowArtifact(
                        workflow_id=workflow_id,
                        artifact_type=artifact_type,
                        payload=_json(payload),
                        patch_hash=patch_hash,
                        created_at=_now(),
                    )
                )
        except PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PersistenceError("artifact save failed") from exc

    def append_audit_event(self, workflow_id: str, event_type: str, metadata: dict[str, Any]) -> None:
        try:
            with self.session_factory.begin() as session:
                if session.get(WorkflowRun, workflow_id) is None:
                    raise PersistenceError("unknown workflow ID")
                session.add(
                    AuditEvent(
                        workflow_id=workflow_id,
                        event_type=event_type,
                        metadata_json=_json(metadata),
                        created_at=_now(),
                    )
                )
        except PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PersistenceError("audit event save failed") from exc

    def get_run(self, workflow_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None:
                raise PersistenceError("unknown workflow ID")
            artifacts = session.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.workflow_id == workflow_id)
                .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
            ).all()
            events = session.scalars(
                select(AuditEvent)
                .where(AuditEvent.workflow_id == workflow_id)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
            return _run_payload(run, artifacts, events)

    def list_runs(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise PersistenceError("page must be positive and page_size must be between 1 and 100")
        with self.session_factory() as session:
            total = len(session.scalars(select(WorkflowRun.id)).all())
            rows = session.scalars(
                select(WorkflowRun)
                .order_by(WorkflowRun.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "items": [_run_payload(run, [], []) for run in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json(value: Any) -> str:
    return json.dumps(_scrub(_to_json(value)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _to_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEY.search(str(key)) else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _run_payload(
    run: WorkflowRun,
    artifacts: list[WorkflowArtifact],
    events: list[AuditEvent],
) -> dict[str, Any]:
    return {
        "workflow_id": run.id,
        "owner": run.owner,
        "repo": run.repo,
        "issue_number": run.issue_number,
        "status": run.status,
        "created_at": run.created_at.isoformat() + "Z",
        "updated_at": run.updated_at.isoformat() + "Z",
        "patch_hash": run.patch_hash,
        "idempotency_key": run.idempotency_key,
        "artifacts": [
            {
                "type": item.artifact_type,
                "payload": json.loads(item.payload),
                "patch_hash": item.patch_hash,
                "created_at": item.created_at.isoformat() + "Z",
            }
            for item in artifacts
        ],
        "audit_events": [
            {
                "event_type": item.event_type,
                "metadata": json.loads(item.metadata_json),
                "created_at": item.created_at.isoformat() + "Z",
            }
            for item in events
        ],
    }
