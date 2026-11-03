from alembic import context
import sqlalchemy as sa

from app.db import settings

config = context.config
# no ORM models: the schema is written as SQL in versions/ and is the single description of the database
target_metadata = None


def run_migrations_online():
    engine = sa.create_engine(settings.url("owner"))
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
