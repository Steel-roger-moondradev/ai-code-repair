"""create workflow history tables"""

from alembic import op
import sqlalchemy as sa

revision = "0001_workflow_history"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workflow_runs" not in inspector.get_table_names():
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner", sa.String(length=100), nullable=False),
            sa.Column("repo", sa.String(length=100), nullable=False),
            sa.Column("issue_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("patch_hash", sa.String(length=64), nullable=True),
        )
    if "workflow_artifacts" not in inspector.get_table_names():
        op.create_table(
            "workflow_artifacts",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
            sa.Column("workflow_id", sa.String(length=64), nullable=False),
            sa.Column("artifact_type", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("patch_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_workflow_artifacts_workflow_id" not in {
        index["name"] for index in inspector.get_indexes("workflow_artifacts")
    }:
        op.create_index("ix_workflow_artifacts_workflow_id", "workflow_artifacts", ["workflow_id"])
    if "audit_events" not in inspector.get_table_names():
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
            sa.Column("workflow_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_audit_events_workflow_id" not in {
        index["name"] for index in inspector.get_indexes("audit_events")
    }:
        op.create_index("ix_audit_events_workflow_id", "audit_events", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_workflow_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_workflow_artifacts_workflow_id", table_name="workflow_artifacts")
    op.drop_table("workflow_artifacts")
    op.drop_table("workflow_runs")
