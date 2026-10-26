"""Shared outbound MCP transport: no ambient proxies, redirects, or retries."""

import httpx


def mcp_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(3.0),
        transport=httpx.AsyncHTTPTransport(trust_env=False, retries=0),
    )
