from alembic import context
from app.db.models import Base
from app.db.session import get_engine


def run():
    if context.is_offline_mode():
        raise RuntimeError("Use online migrations against the configured SQLite database")
    with get_engine().connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


run()
