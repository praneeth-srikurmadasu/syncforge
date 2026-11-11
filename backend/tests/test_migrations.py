"""Migration tests: models match migrations, and migrations apply and roll back cleanly."""

from alembic import command
from sqlalchemy import inspect

from app.core.database import engine
from app.models import Base
from tests.conftest import alembic_config

# Every table defined by the models.
MODEL_TABLES = set(Base.metadata.tables)


def _tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def test_models_and_migrations_are_in_sync() -> None:
    # Fails if a model was changed without a matching migration.
    command.check(alembic_config())


def test_downgrade_to_base_and_upgrade_to_head() -> None:
    config = alembic_config()

    command.downgrade(config, "base")
    assert MODEL_TABLES.isdisjoint(_tables())

    command.upgrade(config, "head")
    assert MODEL_TABLES <= _tables()
