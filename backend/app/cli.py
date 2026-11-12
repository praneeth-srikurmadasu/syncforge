"""Administrative command-line tasks.

Super Admins cannot be created through the public API (that would let anyone grant
themselves platform-wide access). They are created by an operator with shell access:

    python -m app.cli create-superadmin --email admin@example.com --name "Platform Admin"

The password is prompted for (never passed on the command line, where it would end
up in shell history). If the email already belongs to a user, that user is promoted.

Local demo data (see app/seed.py):

    python -m app.cli seed-demo --admin-email you@example.com

The outbox relay (publishes integration events to the message broker; run one or more,
next to the Celery workers - see docs/09):

    python -m app.cli outbox-relay

Delete expired rows - revoked (logged-out) tokens past their expiry, and idempotency
records past IDEMPOTENCY_TTL_HOURS. Safe to run at any time; run it daily from a scheduler
(cron, Windows Task Scheduler, a Kubernetes CronJob):

    python -m app.cli purge-expired
"""

import argparse
import getpass
import logging
import sys
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.events.relay import OutboxRelay
from app.models import User
from app.reliability.idempotency import purge_expired
from app.repositories.users import RevokedTokenRepository, UserRepository
from app.schemas.auth import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.security.password_policy import password_problem
from app.security.passwords import hash_password
from app.seed import SeedError, seed_demo


def create_superadmin(
    session: Session, *, email: str, full_name: str, password: str | None
) -> User:
    """Create a Super Admin, or promote an existing user. Returns the user."""
    email = email.strip().lower()
    users = UserRepository(session)
    user = users.get_by_email(email)
    if user is not None:
        user.is_superadmin = True
        user.is_active = True
    else:
        if password is None or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            raise ValueError(
                f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters."
            )
        problem = password_problem(password, email)
        if problem:
            raise ValueError(problem)
        user = users.add(
            User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                is_superadmin=True,
            )
        )
    session.commit()
    return user


def purge_expired_rows(session: Session, *, now: datetime | None = None) -> tuple[int, int]:
    """Delete expired revoked tokens and idempotency records. Returns (tokens, records)."""
    now = now or datetime.now(UTC)
    tokens = RevokedTokenRepository(session).purge_expired(now)
    session.commit()
    records = purge_expired(session, now=now)
    logging.getLogger("syncforge.maintenance").info(
        "expired rows purged", extra={"revoked_tokens": tokens, "idempotency_records": records}
    )
    return tokens, records


def _prompt_password() -> str:
    limits = f"{PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters"
    password = getpass.getpass(f"Password ({limits}): ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords do not match.")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="Create or promote a Super Admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="Platform Admin")
    seed = commands.add_parser("seed-demo", help="Create the 'Acme Demo' organization")
    seed.add_argument("--admin-email", required=True, help="An already registered user")
    relay = commands.add_parser("outbox-relay", help="Publish outbox events to the broker")
    relay.add_argument("--once", action="store_true", help="Run one round, then exit")
    commands.add_parser(
        "purge-expired", help="Delete expired revoked tokens and idempotency records"
    )
    args = parser.parse_args(argv)

    if args.command == "seed-demo":
        return _seed_demo(args.admin_email)
    if args.command == "outbox-relay":
        return run_outbox_relay(once=args.once)
    if args.command == "purge-expired":
        with SessionLocal() as session:
            tokens, records = purge_expired_rows(session)
        print(f"Deleted {tokens} expired revoked token(s) and {records} idempotency record(s).")
        return 0

    with SessionLocal() as session:
        existing = UserRepository(session).get_by_email(args.email.strip().lower())
        try:
            password = None if existing else _prompt_password()
            user = create_superadmin(
                session, email=args.email, full_name=args.name, password=password
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    action = "Promoted existing user" if existing else "Created"
    print(f"{action} Super Admin {user.email} (id {user.id})")
    return 0


def _seed_demo(admin_email: str) -> int:
    with SessionLocal() as session:
        try:
            result = seed_demo(session, admin_email=admin_email)
        except SeedError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Created organization '{result.organization.name}' "
            f"(id {result.organization.id}) with {result.departments} departments and "
            f"{result.employees} employees. {admin_email} is its Organization Admin."
        )
    return 0


def run_outbox_relay(*, once: bool = False) -> int:
    """Poll the outbox until Ctrl+C. Each round commits on its own, so stopping is safe."""
    from app.workers.tasks import publish_event  # imports Celery only for this command

    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("syncforge.relay")
    logger.info(
        "outbox relay started",
        extra={"poll_interval_seconds": settings.outbox_poll_interval_seconds},
    )
    try:
        while True:
            try:
                with SessionLocal() as session:
                    OutboxRelay(session, publish_event, settings).run_once()
            except Exception:  # database briefly unavailable: log and keep polling
                logger.exception("outbox relay round failed")
            if once:
                return 0
            time.sleep(settings.outbox_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("outbox relay stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
