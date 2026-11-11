"""Administrative command-line tasks.

Super Admins cannot be created through the public API (that would let anyone grant
themselves platform-wide access). They are created by an operator with shell access:

    python -m app.cli create-superadmin --email admin@example.com --name "Platform Admin"

The password is prompted for (never passed on the command line, where it would end
up in shell history). If the email already belongs to a user, that user is promoted.

Local demo data (see app/seed.py):

    python -m app.cli seed-demo --admin-email you@example.com
"""

import argparse
import getpass
import sys

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
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


def _prompt_password() -> str:
    password = getpass.getpass("Password (12-128 characters): ")
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
    args = parser.parse_args(argv)

    if args.command == "seed-demo":
        return _seed_demo(args.admin_email)

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


if __name__ == "__main__":
    sys.exit(main())
