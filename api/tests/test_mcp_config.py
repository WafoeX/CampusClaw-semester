"""Deployment-only MCP approval and secret boundaries."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from campusclaw.application.mcp_transport import mcp_http_client
from campusclaw.config import Settings, normalize_mcp_origin
from tests.test_config import BASE


def settings(**values: object) -> Settings:
    return Settings.model_validate(BASE | values)


def test_demo_approval_and_runtime_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    config = settings(MCP_AUTH_TOKEN="synthetic-mcp-secret")
    assert config.approved_mcp_origin("http://MCP-DEMO:8090/") == "http://mcp-demo:8090"
    credential = config.mcp_credential("http://mcp-demo:8090")
    assert credential is not None
    assert credential.get_secret_value() == "synthetic-mcp-secret"
    assert "synthetic-mcp-secret" not in repr(config)
    assert "synthetic-mcp-secret" not in config.model_dump_json()


@pytest.mark.parametrize("token", [None, "", "   "])
def test_missing_credential_does_not_disable_api(token: str | None) -> None:
    assert settings(MCP_AUTH_TOKEN=token).mcp_credential("http://mcp-demo:8090") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8090",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "https://example.com",
        "http://mcp-demo:8090.evil",
        "file:///etc/passwd",
        "http://user:synthetic-secret@mcp-demo:8090",
        "http://mcp-demo:8090/mcp",
        "http://mcp-demo:8090?secret=synthetic-secret",
        "http://mcp-demo:8090#fragment",
        "http://mcp-demo:8090?",
        "http://mcp-demo:8090#",
        " http://mcp-demo:8090",
        "http://mcp-demo:8090\\evil",
        "http://mcp-demo:8090\n",
        "http://mcp-demo:bad",
    ],
)
def test_unapproved_and_malformed_origins_are_safe(url: str) -> None:
    with pytest.raises(ValueError) as caught:
        settings().approved_mcp_origin(url)
    assert "synthetic-secret" not in str(caught.value)
    assert url not in str(caught.value)


@pytest.mark.parametrize(
    "mapping",
    [
        {"http://secret:synthetic-secret@mcp-demo:8090": "MCP_AUTH_TOKEN"},
        {"http://mcp-demo:8090": "synthetic-secret"},
        {"http://mcp-demo:8090": "TOKEN", "http://MCP-DEMO:8090/": "OTHER_TOKEN"},
    ],
)
def test_bad_mapping_is_rejected_without_inputs(mapping: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as caught:
        settings(MCP_APPROVED_SERVERS=mapping)
    assert "synthetic-secret" not in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_deployment_can_explicitly_map_another_runtime_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COURSE_MCP_TOKEN", "synthetic-alternate-secret")
    config = settings(MCP_APPROVED_SERVERS={"https://COURSE.internal:443/": "COURSE_MCP_TOKEN"})
    assert config.MCP_APPROVED_SERVERS == {"https://course.internal": "COURSE_MCP_TOKEN"}
    credential = config.mcp_credential("https://course.internal")
    assert credential is not None
    assert credential.get_secret_value() == "synthetic-alternate-secret"
    assert "synthetic-alternate-secret" not in repr(config)
    assert normalize_mcp_origin("http://[::1]:8090/") == "http://[::1]:8090"


def test_transport_ignores_proxy_environment_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy:1234")
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy:1234")

    async def check() -> None:
        async with mcp_http_client() as client:
            assert client.follow_redirects is False
            assert client.trust_env is False
            assert client.timeout == httpx.Timeout(3.0)

    asyncio.run(check())
