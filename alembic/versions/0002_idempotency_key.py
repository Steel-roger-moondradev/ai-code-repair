"""add workflow idempotency keys"""

from alembic import op
import sqlalchemy as sa

revision = "0002_idempotency_key"
down_revision = "0001_workflow_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "idempotency_key" not in {
        column["name"] for column in inspector.get_columns("workflow_runs")
    }:
        with op.batch_alter_table("workflow_runs") as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
            batch.create_unique_constraint(
                "uq_workflow_runs_idempotency_key",
                ["idempotency_key"],
            )


def downgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_constraint("uq_workflow_runs_idempotency_key", type_="unique")
        batch.drop_column("idempotency_key")
