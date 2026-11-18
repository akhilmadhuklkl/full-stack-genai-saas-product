"""Add persistent token revocation."""

import sqlalchemy as sa
from alembic import op

revision = "0006_revoked_tokens"
down_revision = "0005_review_job_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_revoked_tokens_token_hash", "revoked_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_token_hash", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
