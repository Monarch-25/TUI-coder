from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog, Static

from agent.core.session import PlanStep, SessionState, StreamEntry, TodoItem


STATUS_SYMBOLS = {
    "done": "[green]✔[/green]",
    "running": "[yellow]→[/yellow]",
    "failed": "[red]✖[/red]",
    "pending": "[grey62]○[/grey62]",
    "retry": "[dark_orange]↻[/dark_orange]",
    "awaiting": "[cyan]?[/cyan]",
}

STREAM_STYLES = {
    "system": "#8ea0b5",
    "reasoning": "#7f8b99",
    "user": "bold #f2c572",
    "reply": "#edf3ff",
    "warning": "#ffb86b",
    "tool": "bold #62d6e8",
    "tool_output": "#b5c0cd",
}


class StatusBar(Static):
    def refresh_from_state(self, state: SessionState) -> None:
        table = Table.grid(expand=True)
        table.add_column(ratio=2)
        table.add_column(ratio=2)
        table.add_column(ratio=2)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=2)
        if state.pending_tool_approval is not None:
            approval = f"tool /approve ({state.pending_tool_approval.tool_name})"
        elif state.pending_approval:
            approval = "plan /approve"
        else:
            approval = "live"
        thinking = f"on:{state.thinking_budget_tokens}" if state.thinking_enabled else "off"
        table.add_row(
            f"[bold]Session[/bold] {state.session_id}",
            f"[bold]Model[/bold] {state.model}  [bold]Backend[/bold] {state.backend}",
            f"[bold]Thinking[/bold] {thinking}  [bold]Branch[/bold] {state.current_branch}",
            f"[bold]Tokens[/bold] {state.tokens:,}",
            f"[bold]Cache[/bold] {state.cache_hit_rate:.0%}",
            f"[bold]Cost[/bold] ${state.cost:.4f}  [bold]Mode[/bold] {approval}",
        )
        self.update(table)


class StreamPanel(RichLog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, auto_scroll=True, highlight=False, markup=False, wrap=True, **kwargs)

    def on_mount(self) -> None:
        self.border_title = "Transcript"

    def refresh_from_state(self, state: SessionState) -> None:
        was_at_end = self.is_vertical_scroll_end
        saved_scroll_y = self.scroll_y
        self.clear()
        renderables = [self._render_entry(entry) for entry in state.stream_entries]
        if not renderables:
            renderables = [Text("Waiting for input...", style="italic #94a3b8")]
        for renderable in renderables:
            self.write(renderable, scroll_end=False)
        if was_at_end:
            self.scroll_end(animate=False)
        else:
            self.scroll_to(y=saved_scroll_y, animate=False, immediate=True)

    def _render_entry(self, entry: StreamEntry) -> Text:
        prefix = {
            "system": "agent_reasoning> ",
            "reasoning": "agent_reasoning> ",
            "user": "operator> ",
            "reply": "agent> ",
            "warning": "agent_reasoning> ",
            "tool": "tool> ",
            "tool_output": "tool_output> ",
        }[entry.role]
        lines = entry.text.splitlines() or [""]
        body = Text()
        for index, line in enumerate(lines):
            leader = prefix if index == 0 else " " * len(prefix)
            body.append(leader + line, style=STREAM_STYLES[entry.role])
            if index != len(lines) - 1:
                body.append("\n")
        return body


class PlanPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "Plan"

    def refresh_from_state(self, state: SessionState) -> None:
        lines = []
        for step in state.plan_steps:
            symbol = STATUS_SYMBOLS[step.status]
            line = Text.from_markup(f"{symbol} {step.index}. {step.title}")
            if step.tool_hint:
                line.append(f"  [{step.tool_hint}]", style="italic #94a3b8")
            lines.append(line)
        if not lines:
            lines = [Text("Stage a prompt to render the plan IR.", style="italic #94a3b8")]
        self.update(Group(*lines))


class ExecutionPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "Execution"

    def refresh_from_state(self, state: SessionState) -> None:
        rows = []
        for step in state.plan_steps:
            rows.append(self._row(step))
        if not rows:
            rows = [Text("Execution timeline appears after /approve.", style="italic #94a3b8")]
        self.update(Group(*rows))

    def _row(self, step: PlanStep) -> Text:
        duration = f" ({step.duration:.2f}s)" if step.duration is not None else ""
        return Text.from_markup(f"{STATUS_SYMBOLS[step.status]} Step {step.index}: {step.title}{duration}")


class LogsPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "Logs"

    def refresh_from_state(self, state: SessionState) -> None:
        lines = []
        if not state.logs:
            lines.append(Text("Use /expand <n> after a plan is staged to inspect step logs.", style="italic #94a3b8"))
        for step, entries in sorted(state.logs.items()):
            marker = "▾" if step in state.expanded_logs else "▸"
            lines.append(Text(f"{marker} Step {step} logs", style="bold #f7c873"))
            if step in state.expanded_logs:
                for entry in entries[-6:]:
                    lines.append(Text(f"   {entry}", style="#d8dee9"))
        self.update(Group(*lines))


class TodoPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "Todo"

    def refresh_from_state(self, state: SessionState) -> None:
        lines = [self._line(item) for item in state.todo_items]
        if not lines:
            lines = [Text("No session todo items yet.", style="italic #94a3b8")]
        self.update(Group(*lines))

    def _line(self, item: TodoItem) -> Text:
        icon = "✔" if item.done else ("→" if item.active else "○")
        style = "green" if item.done else ("yellow" if item.active else "#d8dee9")
        return Text(f"{icon} {item.text}", style=style)


class VCSPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "VCS"

    def refresh_from_state(self, state: SessionState) -> None:
        lines = [
            Text(f"HEAD {state.head}", style="bold #7aa2f7"),
            Text(f"branch {state.current_branch}", style="#7dd3c7"),
        ]
        if state.uploaded_files:
            lines.append(Text("uploads " + ", ".join(state.uploaded_files[-3:]), style="#c0caf5"))
        for snapshot in state.snapshots[:5]:
            lines.append(Text(f"{snapshot.sha}  {snapshot.label}", style="#d8dee9"))
        self.update(Group(*lines))


class CommandPanel(Static):
    def on_mount(self) -> None:
        self.border_title = "Commands"

    def refresh_from_state(self, state: SessionState) -> None:
        del state
        lines = [
            Text("/help      command surface", style="#f7c873"),
            Text("/thinking  toggle Claude thinking", style="#f7c873"),
            Text("/plan ...  enter plan mode", style="#f7c873"),
            Text("/logs      toggle logs panel", style="#f7c873"),
            Text("/exit      quit the app", style="#f7c873"),
            Text("/approve   allow tool or plan", style="#f7c873"),
            Text("/model opus switch display model", style="#f7c873"),
            Text("/export    write session summary", style="#f7c873"),
        ]
        self.update(Group(*lines))
