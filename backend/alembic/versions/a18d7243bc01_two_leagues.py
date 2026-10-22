"""Add league scope without rewriting existing Premier League rows."""

import sqlalchemy as sa

from alembic import op

revision = "a18d7243bc01"
down_revision = "fdeead65fb74"
branch_labels = None
depends_on = None
TABLES = ("teams", "import_runs", "matches", "squad_values", "season_ratings")


def upgrade():
    for table in TABLES:
        op.add_column(
            table, sa.Column("league", sa.String(10), nullable=False, server_default="epl")
        )
        op.create_index(f"ix_{table}_league", table, ["league"])


def downgrade():
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_league", table_name=table)
        op.drop_column(table, "league")
