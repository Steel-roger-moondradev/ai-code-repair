"""Safe structured workflow logging helpers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("patchpilot.workflow")


def log_stage(
    *,
    workflow_id: str,
    node: str,
    status: str,
    duration_ms: int | None = None,
    error_category: str | None = None,
) -> None:
    """Emit bounded workflow metadata without payloads, secrets, or source."""

    fields: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node": node,
        "status": status,
    }
    if duration_ms is not None:
        fields["duration_ms"] = max(0, duration_ms)
    if error_category is not None:
        fields["error_category"] = error_category
    logger.info("workflow_stage %s", fields)
