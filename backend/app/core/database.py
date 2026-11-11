"""SQLAlchemy engine and session management.

Synchronous SQLAlchemy is used deliberately: FastAPI runs sync endpoints in a
thread pool, and the same session code will be reused by Celery workers (Phase 5),
which are synchronous.
"""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

engine: Engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,  # transparently replaces connections dropped by the server
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    return engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    with SessionLocal() as session:
        yield session


def check_database(target: Engine) -> None:
    """Raise if the database cannot execute a trivial query."""
    with target.connect() as connection:
        connection.execute(text("SELECT 1"))
