"""Nullable historical UCL metadata; existing matches and ratings stay intact."""

import sqlalchemy as sa

from alembic import op

revision = "c618b7a320ef"
down_revision = "b571ccaa9802"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("matches", sa.Column("ucl_detail", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("matches", "ucl_detail")
