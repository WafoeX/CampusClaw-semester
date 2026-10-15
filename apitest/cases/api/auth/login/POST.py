from datetime import datetime

from apitest.clients import Context
from apitest.scenarios import PASSWORD, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    before = context.database.rows(
        "SELECT id, account, role, class_id, is_active, created_at FROM users ORDER BY account"
    )
    for account, role in (("teacher.alpha", "teacher"), ("student.alpha", "student")):
        result = s.call(
            "POST", "/api/auth/login", account=None, body={"account": account, "password": PASSWORD}
        )
        checks.require(
            set(result)
            == {
                "access_token",
                "token_type",
                "expires_at",
                "user_id",
                "account",
                "role",
                "class_id",
            },
            "response.fields",
        )
        checks.require(
            result["token_type"] == "bearer"
            and len(result["access_token"].split(".")) == 3
            and datetime.fromisoformat(result["expires_at"]).tzinfo is not None,
            "response.values",
        )
        row = next(row for row in before if row["account"] == account)
        checks.require(
            result["role"] == role
            and result["account"] == account
            and result["user_id"] == str(row["id"])
            and result["class_id"] == str(row["class_id"]),
            "auth.identity",
        )
        status, identity = context.client.json("GET", "/api/auth/me", token=result["access_token"])
        checks.require(
            status == 200
            and identity
            == {key: result[key] for key in ("user_id", "account", "role", "class_id")},
            "auth.identity",
        )
    unknown = s.call(
        "POST",
        "/api/auth/login",
        account=None,
        body={"account": context.fixtures.name("unknown"), "password": PASSWORD},
        status=401,
    )
    wrong = s.call(
        "POST",
        "/api/auth/login",
        account=None,
        body={"account": "teacher.alpha", "password": "wrong-synthetic-password"},
        status=401,
    )
    checks.require(unknown == wrong, "auth.indistinguishable")
    checks.require(
        before
        == context.database.rows(
            "SELECT id, account, role, class_id, is_active, created_at FROM users ORDER BY account"
        ),
        "database.unchanged",
    )


OPERATION = Operation("POST", "/api/auth/login", run)
