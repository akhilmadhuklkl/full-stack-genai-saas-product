"""Add review job execution metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0005_review_job_metadata"
down_revision = "0004_project_review_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("review_jobs", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("review_jobs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_jobs", "heartbeat_at")
    op.drop_column("review_jobs", "started_at")
    op.drop_column("review_jobs", "attempt_count")
