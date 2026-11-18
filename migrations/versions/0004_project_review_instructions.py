"""Add project-specific review instructions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_project_review_instructions"
down_revision = "0003_review_prompt_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("review_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "review_instructions")
