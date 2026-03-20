from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

ModelName = Literal["sonnet", "opus"]
BackendName = Literal["local", "bedrock"]
StepStatus = Literal["pending", "running", "done", "failed", "retry", "awaiting"]
StreamRole = Literal["system", "reasoning", "user", "reply", "warning", "tool", "tool_output"]


def short_id() -> str:
    return uuid4().hex[:6]


def short_sha() -> str:
    return uuid4().hex[:7]


@dataclass
class StreamEntry:
    role: StreamRole
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TodoItem:
    text: str
    done: bool = False
    active: bool = False


@dataclass
class Snapshot:
    sha: str
    label: str


@dataclass
class PlanStep:
    index: int
    title: str
    tool_hint: str | None = None
    status: StepStatus = "pending"
    duration: float | None = None
    detail: str = ""


@dataclass
class SessionState:
    session_id: str = field(default_factory=short_id)
    model: ModelName = "sonnet"
    backend: BackendName = "local"
    tokens: int = 0
    cache_hit_rate: float = 0.91
    cost: float = 0.0
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 2048
    current_branch: str = "main"
    uploaded_files: list[str] = field(default_factory=list)
    stream_entries: list[StreamEntry] = field(default_factory=list)
    todo_items: list[TodoItem] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    plan_steps: list[PlanStep] = field(default_factory=list)
    logs: dict[int, list[str]] = field(default_factory=dict)
    expanded_logs: set[int] = field(default_factory=set)
    flows: list[str] = field(default_factory=list)
    active_prompt_names: list[str] = field(default_factory=list)
    pending_query: str | None = None
    last_query: str | None = None
    last_reply: str | None = None
    pending_approval: bool = False
    last_failed_step: int | None = None
    demo_failure_step: int | None = None
    show_plan: bool = False
    show_logs: bool = False
    show_execution: bool = False
    export_dir: Path = field(default_factory=lambda: Path("exports"))

    @property
    def head(self) -> str:
        return self.snapshots[0].sha if self.snapshots else "none"


def initial_state() -> SessionState:
    state = SessionState()
    state.todo_items = [
        TodoItem("Shape the terminal UX", done=True),
        TodoItem("Wire slash-command flow", active=True),
        TodoItem("Document current state and future phases"),
    ]
    state.snapshots = [
        Snapshot(short_sha(), "prototype_boot"),
        Snapshot(short_sha(), "layout_sketch"),
    ]
    state.flows = ["ui/demo-shell", "ui/approval-gate-preview"]
    state.active_prompt_names = [
        "conversation_system",
        "planner_system",
        "executor_system",
        "conversation_summary",
        "next_prompt_suggestion",
    ]
    state.stream_entries = [
        StreamEntry(
            "system",
            "Workflow Builder booted. Conversation can use inline read-only workspace tools today, and Bedrock-backed Claude turns can attach when the environment is configured.",
        ),
        StreamEntry(
            "reasoning",
            "Type a prompt to talk with the agent or stage a plan. Read-only workspace inspection can appear inline in the stream, and /thinking toggles Bedrock thinking mode for future live Claude turns.",
        ),
    ]
    return state
