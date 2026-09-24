# pyright: basic, reportMissingImports=false
"""Containerized management CLI."""

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from campusclaw.application.seed import seed_demo
from campusclaw.config import get_settings
from campusclaw.domain.models import Class, User, UserRole
from campusclaw.domain.security import PasswordService
from campusclaw.persistence.database import Database


def provision_user(
    session: Session,
    *,
    account: str,
    class_name: str,
    role: UserRole,
    password: str,
    create_class: bool,
    password_service: PasswordService | None = None,
) -> User:
    """Create one user while selecting or idempotently creating its class."""
    normalized_account = account.strip()
    normalized_class = class_name.strip()
    if not normalized_account or not normalized_class:
        raise ValueError("account and class name must not be empty")

    school_class = session.scalar(select(Class).where(Class.name == normalized_class))
    if school_class is None:
        if not create_class:
            raise ValueError("class does not exist; pass --create-class to create it")
        school_class = Class(name=normalized_class)
        session.add(school_class)
        session.flush()

    if session.scalar(select(User.id).where(User.account == normalized_account)) is not None:
        raise ValueError("account already exists")

    hasher = password_service or PasswordService()
    user = User(
        account=normalized_account,
        password_hash=hasher.hash(password),
        role=role.value,
        class_id=school_class.id,
    )
    session.add(user)
    session.flush()
    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="campusclaw")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-user", help="provision one teacher or student")
    create.add_argument("--account", required=True)
    create.add_argument("--class-name", required=True)
    create.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    create.add_argument("--create-class", action="store_true")
    subparsers.add_parser("seed-demo", help="idempotently initialize demo data")
    return parser


def app(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    database = Database(settings.DATABASE_URL)
    try:
        if args.command == "seed-demo":
            result = seed_demo(database, settings)
            if not result.enabled:
                print("demo seed disabled; no changes made")
            else:
                print(
                    "demo seed complete: "
                    f"classes={result.classes} users={result.users} materials={result.materials}"
                )
            return

        if args.command != "create-user":
            parser.error("unsupported command")
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if not password or password != confirmation:
            parser.error("passwords must be non-empty and match")
        with database.transaction() as session:
            user = provision_user(
                session,
                account=args.account,
                class_name=args.class_name,
                role=UserRole(args.role),
                password=password,
                create_class=args.create_class,
            )
        print(f"created {user.role} account {user.account} in class {args.class_name}")
    except (ValueError, IntegrityError) as exc:
        print(f"operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        database.dispose()


if __name__ == "__main__":
    app()
