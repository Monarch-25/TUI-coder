from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

ModelName = Literal["sonnet", "opus"]
StepStatus = Literal["pending", "running", "done", "failed", "retry", "awaiting"]
StreamRole = Literal["system", "reasoning", "user", "reply", "warning"]


def short_id() -> str:
    return uuid4().hex[:6]


def short_sha() -> str:
    return uuid4().hex[:7]


@dataclass
class StreamEntry:
    role: StreamRole
    text: str


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
    tokens: int = 0
    cache_hit_rate: float = 0.91
    cost: float = 0.0
    current_branch: str = "main"
    uploaded_files: list[str] = field(default_factory=list)
    stream_entries: list[StreamEntry] = field(default_factory=list)
    todo_items: list[TodoItem] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    plan_steps: list[PlanStep] = field(default_factory=list)
    logs: dict[int, list[str]] = field(default_factory=dict)
    expanded_logs: set[int] = field(default_factory=set)
    flows: list[str] = field(default_factory=list)
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
    state.stream_entries = [
        StreamEntry(
            "system",
            "Workflow Builder prototype booted. This shell is local-only and uses mock agent events.",
        ),
        StreamEntry(
            "reasoning",
            "Type a prompt to stage a plan. Use /plan or /logs only when you want those hidden panels, then /approve to execute.",
        ),
    ]
    return state
