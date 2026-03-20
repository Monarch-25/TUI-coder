from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Input

from agent.core.agent import MockAgentOrchestrator
from agent.core.session import SessionState, StreamEntry, initial_state
from agent.tui.commands import COMMAND_SUGGESTIONS, ParsedCommand, help_text, parse_command
from agent.tui.events import AgentEvent, EventBus, EventKind
from agent.tui.panels import CommandPanel, ExecutionPanel, LogsPanel, PlanPanel, StatusBar, StreamPanel, TodoPanel, VCSPanel


class WorkflowBuilderApp(App[None]):
    CSS_PATH = "agent.tcss"
    TITLE = "Workflow Builder"
    SUB_TITLE = "Agentic TUI prototype"
    BINDINGS = [
        Binding("ctrl+r", "rerun", "Re-run"),
        Binding("ctrl+l", "clear_session", "Clear"),
        Binding("ctrl+h", "show_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.state: SessionState = initial_state()
        self.bus = EventBus()
        self.orchestrator = MockAgentOrchestrator(self.state, self.bus)
        self._consumer_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status")
        with Horizontal(id="body"):
            with Vertical(id="main-column"):
                yield StreamPanel(id="stream")
                yield PlanPanel(id="plan")
                yield ExecutionPanel(id="execution")
                yield LogsPanel(id="logs")
            with Vertical(id="sidebar"):
                yield TodoPanel(id="todo")
                yield VCSPanel(id="vcs")
                yield CommandPanel(id="commands")
        yield Input(
            placeholder="Type a prompt for conversation, or use /plan <request> for plan mode.",
            suggester=SuggestFromList(COMMAND_SUGGESTIONS, case_sensitive=False),
            id="command-input",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self._consumer_task = asyncio.create_task(self._consume_events())
        self._refresh_all()

    async def on_unmount(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/"):
            try:
                command = parse_command(value)
            except ValueError as exc:
                self._append_stream("warning", str(exc))
                self._refresh_all()
                return
            await self._handle_command(command)
            return
        await self.orchestrator.handle_conversation_turn(value)

    async def action_rerun(self) -> None:
        if self.state.last_query:
            await self.orchestrator.handle_conversation_turn(self.state.last_query)
        else:
            self._append_stream("warning", "There is no last prompt to rerun yet.")
            self._refresh_all()

    async def action_clear_session(self) -> None:
        self.orchestrator.clear_session()
        self._refresh_all()

    async def action_show_help(self) -> None:
        self._append_stream("system", help_text())
        self._refresh_all()

    async def _consume_events(self) -> None:
        while True:
            event = await self.bus.next()
            await self._apply_event(event)

    async def _apply_event(self, event: AgentEvent) -> None:
        if event.kind == EventKind.THINKING:
            self.sub_title = event.message
        elif event.kind == EventKind.PLAN_READY:
            self.sub_title = "Plan staged"
        elif event.kind == EventKind.TOOL_START:
            self.sub_title = f"Tool: {event.message}"
        elif event.kind == EventKind.TOOL_OUTPUT:
            self.sub_title = "Tool output received"
        elif event.kind == EventKind.AWAITING_APPROVAL:
            self.sub_title = "Awaiting approval"
        elif event.kind == EventKind.STEP_START:
            self.sub_title = event.message
        elif event.kind == EventKind.STEP_SUCCESS:
            self.sub_title = event.message
        elif event.kind == EventKind.STEP_FAILURE:
            self.sub_title = event.message
            step_number = int(event.detail.get("step", 0))
            if step_number:
                self.state.expanded_logs.add(step_number)
        elif event.kind == EventKind.RETRY:
            self.sub_title = event.message
        elif event.kind == EventKind.SNAPSHOT:
            self.sub_title = f"Snapshot {event.detail.get('sha', '')}"
        elif event.kind == EventKind.REPLY:
            self.sub_title = "Idle"
        elif event.kind == EventKind.TODO_UPDATE:
            self.sub_title = event.message
        self._refresh_all(token_only=event.kind == EventKind.TOKEN_STREAM)

    async def _handle_command(self, command: ParsedCommand) -> None:
        match command.name:
            case "help":
                self._append_stream("system", help_text())
            case "plan":
                if command.args:
                    plan_query = " ".join(command.args)
                    await self.orchestrator.stage_plan(plan_query)
                    self.state.show_plan = True
                    return
                if not self.state.plan_steps:
                    self._append_stream("warning", "No staged plan yet. Use /plan <request> to enter plan mode.")
                else:
                    self.state.show_plan = not self.state.show_plan
                    state = "shown" if self.state.show_plan else "hidden"
                    self._append_stream("system", f"Plan panel {state}.")
            case "logs":
                self.state.show_logs = not self.state.show_logs
                state = "shown" if self.state.show_logs else "hidden"
                self._append_stream("system", f"Logs panel {state}.")
            case "thinking":
                self._handle_thinking_command(command.args)
            case "exit":
                self.exit()
                return
            case "upload":
                if not command.args:
                    self._append_stream("warning", "Usage: /upload <file>")
                else:
                    await self.orchestrator.simulate_upload(command.args[0])
                    return
            case "run":
                if self.state.pending_tool_approval is not None:
                    self._append_stream("warning", "A tool request is already waiting for /approve or /reject.")
                elif self.state.pending_approval:
                    self._append_stream("warning", "A plan is already waiting for /approve or /reject.")
                elif self.state.last_plan_query:
                    await self.orchestrator.stage_plan(self.state.last_plan_query)
                    self.state.show_plan = True
                    return
                else:
                    self._append_stream("warning", "No staged-plan query is available for /run. Use /plan <request> first.")
            case "approve":
                if self.orchestrator.has_pending_tool_approval():
                    await self.orchestrator.approve_pending_tool()
                    return
                if not self.state.pending_approval:
                    self._append_stream("warning", "There is no staged plan or tool request to approve.")
                else:
                    await self.orchestrator.execute_staged_plan()
                    return
            case "reject":
                if self.orchestrator.has_pending_tool_approval():
                    await self.orchestrator.reject_pending_tool()
                    return
                await self.orchestrator.reject_plan()
                return
            case "retry":
                await self.orchestrator.retry_failed_step()
                return
            case "expand":
                if not command.args:
                    self._append_stream("warning", "Usage: /expand <step-number>")
                else:
                    self._expand_logs(command.args[0])
            case "model":
                if len(command.args) != 1 or command.args[0] not in {"sonnet", "opus"}:
                    self._append_stream("warning", "Usage: /model sonnet|opus")
                else:
                    self.state.model = command.args[0]  # type: ignore[assignment]
                    self._append_stream("system", f"Displayed session model switched to {self.state.model}.")
            case "vcs":
                self._handle_vcs_command(command.args)
            case "cost":
                self._append_stream(
                    "system",
                    f"Tokens {self.state.tokens:,}  Cost ${self.state.cost:.4f}  Cache {self.state.cache_hit_rate:.0%}",
                )
            case "flows":
                flow_lines = "\n".join(f"- {flow}" for flow in self.state.flows) or "- none yet"
                self._append_stream("system", f"Visible flows:\n{flow_lines}")
            case "export":
                output_root = self._export_session()
                self._append_stream("system", f"Session exported to {output_root}")
            case "clear":
                self.orchestrator.clear_session()
            case _:
                self._append_stream("warning", f"Unknown command: /{command.name}. Use /help.")
        self._refresh_all()

    def _handle_vcs_command(self, args: list[str]) -> None:
        if not args or args[0] == "log":
            history = "\n".join(f"- {snap.sha} {snap.label}" for snap in self.state.snapshots[:8])
            self._append_stream("system", f"Snapshot history:\n{history}")
            return
        action = args[0]
        if action == "diff" and len(args) == 2:
            sha = args[1]
            self._append_stream(
                "system",
                f"Diff for {sha}\n- mock_plan.py added\n- state tracker updated\n- Bedrock integration still deferred",
            )
            return
        if action == "restore" and len(args) == 2:
            sha = args[1]
            self.state.snapshots.insert(0, self.state.snapshots.pop(next((i for i, snap in enumerate(self.state.snapshots) if snap.sha == sha), 0)))
            self._append_stream("system", f"Restored mock snapshot {sha}.")
            return
        if action == "branch" and len(args) == 2:
            self.orchestrator.create_branch(args[1])
            self._append_stream("system", f"Created and switched to branch {args[1]}.")
            return
        self._append_stream("warning", "Usage: /vcs log|diff <sha>|restore <sha>|branch <name>")

    def _expand_logs(self, raw_step: str) -> None:
        try:
            step_number = int(raw_step)
        except ValueError:
            self._append_stream("warning", "Step number must be an integer.")
            return
        if self.orchestrator.toggle_log(step_number):
            self._append_stream("system", f"Toggled logs for step {step_number}.")
        else:
            self._append_stream("warning", f"No logs recorded for step {step_number}.")

    def _handle_thinking_command(self, args: list[str]) -> None:
        if not args:
            mode = "on" if self.state.thinking_enabled else "off"
            self._append_stream(
                "system",
                f"Thinking mode is {mode}. Budget {self.state.thinking_budget_tokens} tokens. Backend {self.state.backend}.",
            )
            return
        action = args[0]
        if action == "on":
            self.state.thinking_enabled = True
            self._append_stream(
                "system",
                f"Thinking mode enabled. Bedrock Claude turns will request up to {self.state.thinking_budget_tokens} reasoning tokens.",
            )
            return
        if action == "off":
            self.state.thinking_enabled = False
            self._append_stream("system", "Thinking mode disabled.")
            return
        if action == "budget" and len(args) == 2:
            try:
                budget = int(args[1])
            except ValueError:
                self._append_stream("warning", "Thinking budget must be an integer.")
                return
            if budget < 1024:
                self._append_stream("warning", "Thinking budget must be at least 1024 tokens.")
                return
            self.state.thinking_budget_tokens = budget
            self._append_stream("system", f"Thinking budget set to {budget} tokens.")
            return
        self._append_stream("warning", "Usage: /thinking on|off|budget <tokens>")

    def _export_session(self) -> Path:
        self.state.export_dir.mkdir(parents=True, exist_ok=True)
        base = self.state.export_dir / f"session-{self.state.session_id}"
        markdown_path = base.with_suffix(".md")
        json_path = base.with_suffix(".json")

        markdown = [
            f"# Session {self.state.session_id}",
            "",
            f"- Model: `{self.state.model}`",
            f"- Backend: `{self.state.backend}`",
            f"- Branch: `{self.state.current_branch}`",
            f"- Tokens: `{self.state.tokens}`",
            f"- Cost: `${self.state.cost:.4f}`",
            f"- Thinking: `{'on' if self.state.thinking_enabled else 'off'}` ({self.state.thinking_budget_tokens})",
            "",
            "## Stream",
            "",
        ]
        for entry in self.state.stream_entries:
            markdown.append(f"- **{entry.role}** {entry.text}")
        markdown.extend(["", "## Plan", ""])
        for step in self.state.plan_steps:
            markdown.append(f"- Step {step.index} [{step.status}] {step.title}")
        markdown_path.write_text("\n".join(markdown), encoding="utf-8")

        payload = {
            "session_id": self.state.session_id,
            "model": self.state.model,
            "backend": self.state.backend,
            "branch": self.state.current_branch,
            "tokens": self.state.tokens,
            "cost": self.state.cost,
            "thinking_enabled": self.state.thinking_enabled,
            "thinking_budget_tokens": self.state.thinking_budget_tokens,
            "last_plan_query": self.state.last_plan_query,
            "pending_tool_approval": (
                {
                    "tool_name": self.state.pending_tool_approval.tool_name,
                    "display": self.state.pending_tool_approval.display,
                    "message": self.state.pending_tool_approval.message,
                }
                if self.state.pending_tool_approval is not None
                else None
            ),
            "active_prompt_names": self.state.active_prompt_names,
            "uploaded_files": self.state.uploaded_files,
            "stream_entries": [
                {
                    "role": entry.role,
                    "text": entry.text,
                    "meta": entry.meta,
                }
                for entry in self.state.stream_entries
            ],
            "plan_steps": [
                {
                    "index": step.index,
                    "title": step.title,
                    "status": step.status,
                    "duration": step.duration,
                }
                for step in self.state.plan_steps
            ],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return base

    def _append_stream(self, role: str, text: str) -> None:
        self.state.stream_entries.append(StreamEntry(role=role, text=text))

    def _refresh_all(self, *, token_only: bool = False) -> None:
        self.query_one("#status", StatusBar).refresh_from_state(self.state)
        self.query_one("#stream", StreamPanel).refresh_from_state(self.state)
        if token_only:
            return
        self.query_one("#plan", PlanPanel).display = self.state.show_plan
        self.query_one("#logs", LogsPanel).display = self.state.show_logs
        self.query_one("#execution", ExecutionPanel).display = self.state.show_execution
        self.query_one("#plan", PlanPanel).refresh_from_state(self.state)
        self.query_one("#execution", ExecutionPanel).refresh_from_state(self.state)
        self.query_one("#logs", LogsPanel).refresh_from_state(self.state)
        self.query_one("#todo", TodoPanel).refresh_from_state(self.state)
        self.query_one("#vcs", VCSPanel).refresh_from_state(self.state)
        self.query_one("#commands", CommandPanel).refresh_from_state(self.state)
