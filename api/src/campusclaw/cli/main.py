# pyright: basic, reportMissingImports=false
"""Containerized management CLI."""

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from campusclaw.application.indexing import IndexWorker, aggregate_index_status
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
    indexer = subparsers.add_parser("indexer", help="process bounded material-index jobs")
    indexer.add_argument("--max-jobs", type=int, default=100)
    subparsers.add_parser("backfill", help="enqueue all ready materials for indexing")
    status_parser = subparsers.add_parser("index-status", help="show aggregate indexing status")
    status_parser.add_argument("--class-id", required=True, type=uuid.UUID)
    subparsers.add_parser("vector-rebuild", help="rebuild vectors from PostgreSQL chunks")
    subparsers.add_parser("qdrant-snapshot", help="create a server-side Qdrant snapshot")
    reconcile = subparsers.add_parser("reconcile-vectors", help="reconcile one class vector index")
    reconcile.add_argument("--class-id", required=True, type=uuid.UUID)
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

        if args.command == "indexer":
            results = IndexWorker(database, settings).run_until_empty(
                max_jobs=max(1, args.max_jobs)
            )
            searchable = sum(result.status == "searchable" for result in results)
            print(f"indexer complete: jobs={len(results)} searchable={searchable}")
            return
        if args.command == "backfill":
            count = IndexWorker(database, settings).backfill()
            print(f"index jobs enqueued: {count}")
            return
        if args.command == "vector-rebuild":
            count = IndexWorker(database, settings).rebuild_vectors()
            print(f"vectors rebuilt: {count}")
            return
        if args.command == "qdrant-snapshot":
            from campusclaw.application.vector import QdrantVectorStore

            QdrantVectorStore(settings).create_snapshot()
            print("qdrant snapshot created")
            return
        if args.command == "reconcile-vectors":
            report = IndexWorker(database, settings).reconcile_class(args.class_id)
            values = " ".join(f"{key}={report[key]}" for key in sorted(report))
            print("vector reconciliation: " + values)
            return
        if args.command == "index-status":
            status_result = aggregate_index_status(database, args.class_id)
            values = " ".join(f"{key}={status_result[key]}" for key in sorted(status_result))
            print("index status: " + values)
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
