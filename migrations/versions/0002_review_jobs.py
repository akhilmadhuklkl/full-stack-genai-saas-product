"""Add persistent review jobs for asynchronous processing."""

import sqlalchemy as sa
from alembic import op

revision = "0002_review_jobs"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id"),
    )
    op.create_index("ix_review_jobs_review_id", "review_jobs", ["review_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_review_jobs_review_id", table_name="review_jobs")
    op.drop_table("review_jobs")
