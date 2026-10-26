"""Ephemeral authorized auxiliary text, never part of persisted audit metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolText:
    tool_ref: str
    text: str
