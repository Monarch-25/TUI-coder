from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol


ToolPermission = Literal["read", "exec", "write", "skill", "network"]


@dataclass(frozen=True)
class ToolIntent:
    name: str
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolObservation:
    name: str
    display: str
    output: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    display: str
    reason: str
    message: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    display: str
    output: str | None = None
    approval: ApprovalRequest | None = None
    error: str | None = None

    @property
    def needs_approval(self) -> bool:
        return self.approval is not None


@dataclass(frozen=True)
class ToolContext:
    root: Path


class Tool(Protocol):
    name: str
    description: str
    permission: ToolPermission

    def schema(self) -> dict[str, Any]:
        ...

    def display(self, arguments: dict[str, Any]) -> str:
        ...

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        ...

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        ...
