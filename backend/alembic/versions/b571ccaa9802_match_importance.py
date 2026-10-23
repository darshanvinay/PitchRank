"""Match stage and neutral venue; reuse existing match/rating/history tables."""

import sqlalchemy as sa

from alembic import op

revision = "b571ccaa9802"
down_revision = "a18d7243bc01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "matches", sa.Column("stage", sa.String(20), nullable=False, server_default="domestic")
    )
    op.add_column("matches", sa.Column("neutral", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("matches", "neutral")
    op.drop_column("matches", "stage")
