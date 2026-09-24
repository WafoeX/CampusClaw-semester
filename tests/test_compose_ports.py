#!/usr/bin/env python3
"""Running-Compose port acceptance checks and mutation regression tests."""

from __future__ import annotations

import json
import os
import subprocess
from typing import cast

JsonObject = dict[str, object]


def parse_compose_ps(output: str) -> list[JsonObject]:
    """Accept both Compose's JSON array and its newline-delimited JSON output."""
    payload = output.strip()
    if not payload:
        return []
    if payload.startswith("["):
        parsed = json.loads(payload)
        assert isinstance(parsed, list)
        return cast(list[JsonObject], parsed)
    return [cast(JsonObject, json.loads(line)) for line in payload.splitlines()]


def published_ports(containers: list[JsonObject]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for container in containers:
        service = container.get("Service")
        if not isinstance(service, str):
            continue
        raw_ports = container.get("Publishers")
        if not isinstance(raw_ports, list):
            continue
        ports = cast(list[JsonObject], raw_ports)
        exposed = [
            published
            for item in ports
            if isinstance(published := item.get("PublishedPort"), int) and published > 0
        ]
        if exposed:
            result.setdefault(service, []).extend(exposed)
    return {service: sorted(set(ports)) for service, ports in result.items()}


def assert_only_web_gateway(ports: dict[str, list[int]], web_port: int = 8080) -> None:
    assert set(ports) == {"web"}, ports
    assert ports["web"] == [web_port], ports


def test_port_assertion_rejects_api_mapping() -> None:
    import pytest

    with pytest.raises(AssertionError):
        assert_only_web_gateway({"web": [8080], "api": [8000]})


def test_port_assertion_rejects_database_mapping() -> None:
    import pytest

    with pytest.raises(AssertionError):
        assert_only_web_gateway({"web": [8080], "db": [5432]})


def main() -> None:
    project = os.getenv("COMPOSE_PROJECT_NAME")
    command = ["docker", "compose"]
    if project:
        command.extend(["-p", project])
    command.extend(["ps", "--format", "json"])
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    assert_only_web_gateway(
        published_ports(parse_compose_ps(completed.stdout)),
        web_port=int(os.getenv("WEB_PORT", "8080")),
    )
    print("running Compose port boundary passed")


if __name__ == "__main__":
    main()
