#!/usr/bin/env python3
"""Static Compose acceptance checks for the internal API/database boundary."""

import json
import subprocess


def main() -> None:
    completed = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(completed.stdout)["services"]
    published = {
        name: service.get("ports", [])
        for name, service in services.items()
        if service.get("ports")
    }
    assert set(published) == {"web"}, published
    assert published["web"], "web must publish the gateway port"
    assert "api" not in published and "db" not in published
    assert set(services["api"]["networks"]) == {"gateway", "data"}
    assert set(services["db"]["networks"]) == {"data"}
    assert services["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["api"]["depends_on"]["seed"]["condition"] == (
        "service_completed_successfully"
    )
    print("compose boundary checks passed")


if __name__ == "__main__":
    main()
