"""Shared test fixtures.

Tests run against a separate database (default: syncforge_test) so they never
touch development data. At the start of every test run the schema is rebuilt
from the Alembic migrations, which also proves the migrations work.

Each test gets a database session inside a transaction that is rolled back at the
end, so tests are isolated from each other and leave no data behind.
"""

import os

# Must be set before the app (and its database engine) is imported.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "syncforge_test")
# A fixed, test-only signing key so tests never depend on the developer's .env.
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-not-for-real-use-0123456789"

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False  # keep pytest's log capture intact
    return config


def _ensure_test_database() -> None:
    settings = get_settings()
    admin_url = settings.database_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": settings.postgres_db},
            ).scalar()
            if not exists:
                # Identifier comes from our own config, not user input.
                conn.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
    finally:
        admin_engine.dispose()


def _rebuild_schema() -> None:
    from app.core.database import engine

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    _ensure_test_database()
    _rebuild_schema()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session whose work is rolled back after the test.

    join_transaction_mode="create_savepoint" means code under test can call
    session.commit() normally - it commits a savepoint, and the outer
    transaction is still rolled back at the end.
    """
    from app.core.database import engine

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    from app.core.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
