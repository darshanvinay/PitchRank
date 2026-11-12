"""Add optional Understat xG without modifying existing matches or ratings."""

import sqlalchemy as sa

from alembic import op

revision = "d903a741bc21"
down_revision = "c618b7a320ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "match_xg",
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), primary_key=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("home_xg", sa.Float(), nullable=False),
        sa.Column("away_xg", sa.Float(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("archive_url", sa.String(1000), nullable=False),
        sa.Column("archive_sha256", sa.String(64), nullable=False),
        sa.Column("provider_date", sa.Date(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "external_id"),
        sa.CheckConstraint("home_xg >= 0 AND away_xg >= 0"),
    )


def downgrade():
    op.drop_table("match_xg")
