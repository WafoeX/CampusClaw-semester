"""The finite, non-executable public tool-reference grammar."""

import re

REFERENCE = re.compile(r"[a-z][a-z0-9_]{0,199}@[a-z][a-z0-9-]{0,62}")


def validate_tool_references(tools: list[str]) -> list[str]:
    if len(tools) > 8 or len(tools) != len(set(tools)):
        raise ValueError("invalid tool reference count")
    if any(tool != "knowledge_search" and REFERENCE.fullmatch(tool) is None for tool in tools):
        raise ValueError("invalid tool reference")
    return tools
