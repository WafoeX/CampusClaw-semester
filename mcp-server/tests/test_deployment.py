"""Compose/static credential boundary checks, never reading the local .env."""

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def test_compose_mcp_internal_network_and_runtime_only_credentials() -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    config: dict[str, Any] = json.loads(result.stdout)
    services = config["services"]
    demo, api = services["mcp-demo"], services["api"]
    assert not demo.get("ports") and not demo.get("volumes")
    assert "8090" in demo["expose"]
    assert set(demo["networks"]) == {"data"}
    assert "data" in api["networks"] and config["networks"]["data"]["internal"] is True
    assert "mcp-demo" not in api.get("depends_on", {})
    assert json.loads(api["environment"]["MCP_APPROVED_SERVERS"]) == {
        "http://mcp-demo:8090": "MCP_AUTH_TOKEN",
    }
    assert api["environment"]["MCP_AUTH_TOKEN"] == demo["environment"]["MCP_AUTH_TOKEN"]
    assert not demo["build"].get("args")
    assert "MCP_AUTH_TOKEN" not in (ROOT / "mcp-server/Dockerfile").read_text()
    ignore = (ROOT / "mcp-server/.dockerignore").read_text().splitlines()
    assert ignore[0] == "*" and not any(line.startswith("!.env") for line in ignore)


def test_environment_template_and_frontend_never_embed_mcp_credentials() -> None:
    template = (ROOT / ".env.example").read_text().splitlines()
    assert "MCP_AUTH_TOKEN=" in template
    for path in (ROOT / "frontend/src").rglob("*"):
        if path.is_file():
            assert b"MCP_AUTH_TOKEN" not in path.read_bytes(), "MCP runtime variable in frontend"
    tracked = subprocess.run(
        ["git", "ls-files", ".env", ".env.*"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert set(tracked) <= {".env.example"}
