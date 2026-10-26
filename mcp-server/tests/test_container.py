"""Opt-in built-image checks; no existing application containers are touched."""

import io
import json
import os
import secrets
import subprocess
import tarfile
from collections.abc import Iterator
from typing import Any

import pytest

IMAGE = os.environ.get("MCP_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="Set MCP_TEST_IMAGE to a built demo image")


def docker(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


@pytest.mark.parametrize("token", [None, "", "   "])
def test_image_refuses_missing_runtime_token(token: str | None) -> None:
    assert IMAGE is not None
    args = ["run", "--rm", "--network", "none"]
    environment = dict(os.environ)
    if token is not None:
        environment["MCP_AUTH_TOKEN"] = token
        args += ["-e", "MCP_AUTH_TOKEN"]
    result = docker(*args, IMAGE, env=environment, timeout=20)
    assert result.returncode != 0
    assert "MCP runtime credential is required" in result.stderr


@pytest.fixture
def running_image() -> Iterator[tuple[str, str]]:
    assert IMAGE is not None
    token = secrets.token_hex(32)
    result = docker(
        "run",
        "-d",
        "--network",
        "none",
        "-e",
        "MCP_AUTH_TOKEN",
        IMAGE,
        env=dict(os.environ, MCP_AUTH_TOKEN=token),
        timeout=20,
    )
    assert result.returncode == 0
    container = result.stdout.strip()
    try:
        yield container, token
    finally:
        assert docker("rm", "-f", container).returncode == 0


def test_built_image_health_protocol_and_secret_boundaries(running_image: tuple[str, str]) -> None:
    assert IMAGE is not None
    container, token = running_image
    # Execute from inside its own network namespace; no host port or data mounts.
    script = """
import json, os, time, urllib.request
url = "http://127.0.0.1:8090"
for attempt in range(50):
    try:
        assert json.load(urllib.request.urlopen(url + "/health"))["status"] == "ok"
        break
    except OSError:
        time.sleep(0.1)
else:
    raise AssertionError("health unavailable")
headers = {"Content-Type": "application/json"}
headers["Authorization"] = "Bearer " + os.environ["MCP_AUTH_TOKEN"]
calls = [("tools/list", {}), ("tools/call", {
    "name": "unit_convert", "arguments": {"question": "将 100 cm 转换为 m"}
})]
for method, params in calls:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url + "/mcp", data=body, headers=headers)
    payload = json.load(urllib.request.urlopen(request))
    assert "result" in payload
    if method == "tools/call":
        assert "1 m" in payload["result"]["content"][0]["text"]
"""
    result = docker("exec", container, "python", "-c", script, timeout=20)
    assert result.returncode == 0, "built image protocol check failed"
    assert token not in docker("logs", container).stdout
    assert token not in docker("logs", container).stderr
    assert token not in docker("history", "--no-trunc", IMAGE).stdout
    config: list[dict[str, Any]] = json.loads(docker("image", "inspect", IMAGE).stdout)
    assert not any(v.startswith("MCP_AUTH_TOKEN=") for v in config[0]["Config"]["Env"])
    archive = subprocess.run(
        ["docker", "image", "save", IMAGE], capture_output=True, check=True
    ).stdout
    # Check the uncompressed layer members as well as metadata, not just manifest bytes.
    with tarfile.open(fileobj=io.BytesIO(archive)) as image:
        for member in image:
            stream = image.extractfile(member) if member.isfile() else None
            if stream is not None:
                assert token.encode() not in stream.read(), "runtime token found in image layer"
