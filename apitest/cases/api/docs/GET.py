import re

from apitest.clients import Context
from apitest.scenarios import AGENT, PASSWORD, SKILL, Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    skill = s.skill()
    agent = s.agent()
    docs = context.client.request("GET", "/api/docs")
    checks.require(
        docs.status_code == 200
        and docs.headers.get("content-type", "").startswith("text/html")
        and 'id="swagger-ui"' in docs.text,
        "response.media_type",
    )
    assets = re.findall(r'(?:src|href)="([^"]+)"', docs.text)
    checks.require(
        len(assets) >= 3 and all(path.startswith("/api/docs/") for path in assets),
        "response.fields",
    )
    texts = [docs.text, str(s.document)]
    for path in assets:
        response = context.client.request("GET", path)
        checks.require(response.status_code == 200 and bool(response.content), "response.status")
        texts.append(response.text)
    init = context.client.request("GET", "/api/docs/init.js")
    checks.require(
        "url: '/api/openapi.json'" in init.text
        and "validatorUrl: null" in init.text
        and "persistAuthorization: false" in init.text,
        "response.fields",
    )
    # Exercise the exact same-origin request/header contract used by Swagger try-out.
    # Actual browser UI control interaction is verified separately, not claimed here.
    token = s.token("teacher.alpha")
    response = context.client.http.get(
        "/api/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://gateway:8080",
            "Referer": "http://gateway:8080/api/docs",
        },
    )
    headers = [
        value
        for key, value in response.request.headers.multi_items()
        if key.lower() == "authorization"
    ]
    checks.require(
        response.status_code == 200
        and response.json() == s.identity("teacher.alpha")
        and headers == [f"Bearer {token}"],
        "auth.identity",
    )
    combined = "\n".join(texts)
    checks.require(
        all(
            value not in combined
            for value in (
                token,
                PASSWORD,
                SKILL["instructions"],
                AGENT["system_prompt"],
                skill["name"],
                agent["name"],
                "apitest-only-signing-key",
                "postgresql://",
                "postgresql+psycopg://",
                "ALPHA_FERN",
                "BETA_CRYSTAL",
            )
        ),
        "safe",
    )
    s.verify_resource(skill, "skills")
    s.verify_resource(agent, "agents")


OPERATION = Operation("GET", "/api/docs", run)
