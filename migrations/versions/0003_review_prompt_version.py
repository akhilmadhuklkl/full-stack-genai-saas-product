"""Record the prompt version used for each review."""

import sqlalchemy as sa
from alembic import op

revision = "0003_review_prompt_version"
down_revision = "0002_review_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("prompt_version", sa.String(length=20), nullable=False, server_default="v1"),
    )


def downgrade() -> None:
    op.drop_column("reviews", "prompt_version")
