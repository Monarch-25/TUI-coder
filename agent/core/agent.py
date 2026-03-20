from __future__ import annotations

import asyncio
from pathlib import Path

from agent.core.conversation import ConversationAgent, PendingConversationTurn
from agent.core.prompt import PromptLibrary
from agent.core.session import PlanStep, SessionState, Snapshot, StreamEntry, TodoItem, short_sha
from agent.tui.events import AgentEvent, EventBus, EventKind


class MockAgentOrchestrator:
    """Prototype orchestrator for conversation, staged planning, and mock execution."""

    def __init__(self, state: SessionState, bus: EventBus) -> None:
        self.state = state
        self.bus = bus
        self.prompts = PromptLibrary()
        self.conversation = ConversationAgent(self.prompts)
        self._pending_tool_turn: PendingConversationTurn | None = None
        self.state.active_prompt_names = self.prompts.active_prompt_names()

    async def handle_conversation_turn(self, query: str) -> None:
        await self._handle_direct_reply(query)

    async def stage_plan(self, query: str) -> None:
        self.state.pending_query = query
        self.state.last_query = query
        self.state.last_plan_query = query
        self.state.last_reply = None
        self.state.last_failed_step = None
        self.state.pending_tool_approval = None
        self._pending_tool_turn = None
        self.state.demo_failure_step = self._pick_failure_step(query)
        self.state.show_execution = False
        self.state.plan_steps = self._build_plan(query)
        self.state.logs = {
            step.index: [f"Prepared mock tool call: {step.tool_hint or 'planner'}"] for step in self.state.plan_steps
        }
        self.state.todo_items = [
            TodoItem("Understand operator intent", done=True),
            TodoItem("Review staged plan", active=True),
            TodoItem("Execute approved steps"),
        ]
        self.state.backend = "local"
        self.state.pending_approval = True

        self._append_stream("user", query)
        await self.bus.publish(AgentEvent(EventKind.THINKING, "Understanding request..."))
        await self._stream_text(
            "reasoning",
            f"Planning a local-only run for: {query}. The plan stays hidden unless you ask for /plan. No Bedrock calls are made in this prototype.",
        )
        await asyncio.sleep(0.15)
        await self.bus.publish(
            AgentEvent(
                EventKind.PLAN_READY,
                "Plan ready",
                {"step_count": len(self.state.plan_steps), "query": query},
            )
        )
        await self.bus.publish(
            AgentEvent(
                EventKind.AWAITING_APPROVAL,
                "Awaiting /approve or /reject",
                {"query": query},
            )
        )
        await self._stream_text(
            "reply",
            (
                f"I've staged a {len(self.state.plan_steps)}-step plan. "
                "Use /plan to inspect it or /approve to run it. "
                f"Active prompt stack: {', '.join(self.state.active_prompt_names[:3])}."
            ),
        )
        await self.bus.publish(AgentEvent(EventKind.REPLY, "Plan staged"))

    async def execute_staged_plan(self, *, retry_from_failed: bool = False) -> None:
        if not self.state.plan_steps:
            await self._stream_text("warning", "No staged plan is available. Submit a prompt first.")
            return
        if not retry_from_failed:
            self.state.pending_approval = False
        self.state.show_execution = True
        start_index = self.state.last_failed_step or 1
        if not retry_from_failed:
            start_index = 1

        active_todo = [
            TodoItem("Understand operator intent", done=True),
            TodoItem("Review staged plan", done=True),
            TodoItem("Execute approved steps", active=True),
        ]
        self.state.todo_items = active_todo

        for step in self.state.plan_steps:
            if step.index < start_index or step.status == "done":
                continue
            step.status = "running"
            await self.bus.publish(
                AgentEvent(EventKind.STEP_START, f"Step {step.index} started", {"step": step.index})
            )
            self.state.logs.setdefault(step.index, []).append("Dispatching mock activity to local executor.")
            await asyncio.sleep(0.25 + (step.index * 0.08))

            if self.state.demo_failure_step == step.index and not retry_from_failed:
                step.status = "failed"
                step.duration = 0.92 + (step.index * 0.11)
                self.state.last_failed_step = step.index
                self.state.logs[step.index].append("Synthetic failure injected to exercise /retry UX.")
                await self.bus.publish(
                    AgentEvent(
                        EventKind.STEP_FAILURE,
                        f"Step {step.index} failed",
                        {"step": step.index, "reason": "Synthetic retry path"},
                    )
                )
                await self._stream_text(
                    "warning",
                    f"Step {step.index} failed on purpose so the retry flow is visible. Use /retry to continue.",
                )
                return

            step.status = "done"
            step.duration = 0.61 + (step.index * 0.14)
            self.state.logs[step.index].append(
                f"Mock result ready in {step.duration:.2f}s using {step.tool_hint or 'planner'}."
            )
            await self.bus.publish(
                AgentEvent(EventKind.STEP_SUCCESS, f"Step {step.index} completed", {"step": step.index})
            )

        self.state.last_failed_step = None
        self.state.demo_failure_step = None
        self.state.tokens += 640 + (len(self.state.plan_steps) * 95)
        self.state.cost += 0.0045 + (len(self.state.plan_steps) * 0.0018)
        self.state.todo_items = [
            TodoItem("Understand operator intent", done=True),
            TodoItem("Review staged plan", done=True),
            TodoItem("Execute approved steps", done=True),
        ]

        snapshot = Snapshot(short_sha(), f"turn_{len(self.state.snapshots) + 1}")
        self.state.snapshots.insert(0, snapshot)
        reply = (
            "Prototype execution complete. The UI, approval gate, logs, VCS preview, and slash commands are wired. "
            "Model calls, Temporal activities, and real tools remain future phases."
        )
        self.state.last_reply = reply
        await self.bus.publish(AgentEvent(EventKind.SNAPSHOT, "Snapshot created", {"sha": snapshot.sha}))
        await self._stream_text("reply", reply)
        await self.bus.publish(AgentEvent(EventKind.REPLY, reply))

    async def retry_failed_step(self) -> None:
        if self.state.last_failed_step is None:
            await self._stream_text("warning", "No failed step is waiting for /retry.")
            return
        failed_step = next(
            (step for step in self.state.plan_steps if step.index == self.state.last_failed_step),
            None,
        )
        if failed_step is None:
            await self._stream_text("warning", "Retry target is missing from the current plan.")
            return
        failed_step.status = "retry"
        self.state.logs.setdefault(failed_step.index, []).append("Retry requested from the command bar.")
        await self.bus.publish(
            AgentEvent(EventKind.RETRY, f"Retrying step {failed_step.index}", {"step": failed_step.index})
        )
        await self.execute_staged_plan(retry_from_failed=True)

    async def simulate_upload(self, raw_path: str) -> None:
        path = Path(raw_path)
        label = path.name or raw_path
        if label not in self.state.uploaded_files:
            self.state.uploaded_files.append(label)

        self.state.todo_items = [
            TodoItem("Catalog uploaded context", done=True),
            TodoItem(f"Preview {label}", active=True),
            TodoItem("Stage prompt against uploaded inputs"),
        ]
        await self._stream_text("system", f"Ingesting: {label}")
        await asyncio.sleep(0.12)
        await self._stream_text("reasoning", f"Detected placeholder type for {label}; real parsing is deferred.")
        await asyncio.sleep(0.12)
        await self._stream_text("system", f"Document ready: {label} [mock]")
        await self.bus.publish(AgentEvent(EventKind.TODO_UPDATE, f"Upload ready: {label}", {"file": label}))

    async def reject_plan(self) -> None:
        if not self.state.pending_approval:
            await self._stream_text("warning", "There is no staged plan waiting for /reject.")
            return
        self.state.pending_approval = False
        self.state.show_execution = False
        self.state.plan_steps.clear()
        self.state.logs.clear()
        self.state.todo_items = [
            TodoItem("Capture revised intent", active=True),
            TodoItem("Stage a replacement plan"),
        ]
        await self._stream_text("warning", "Plan rejected. Submit a new prompt to restage the workflow.")

    def has_pending_tool_approval(self) -> bool:
        return self.state.pending_tool_approval is not None and self._pending_tool_turn is not None

    async def approve_pending_tool(self) -> None:
        pending = self._pending_tool_turn
        if pending is None or self.state.pending_tool_approval is None:
            await self._stream_text("warning", "There is no pending tool approval.")
            return
        self.state.pending_tool_approval = None
        await self._emit_entry(
            "reasoning",
            f"Approval granted for {pending.approval.tool_name}. Continuing the conversation turn.",
        )
        result = await self.conversation.resume_turn(pending=pending, state=self.state, emit=self._emit_conversation_signal)
        self._pending_tool_turn = result.pending
        self.state.pending_tool_approval = result.pending.approval if result.pending is not None else None
        if result.reply:
            self.state.last_reply = result.reply
            if not self._last_entry_has_text("reply", result.reply):
                await self._stream_text("reply", result.reply)
        await self.bus.publish(AgentEvent(EventKind.REPLY, result.reply or "Conversation turn complete"))

    async def reject_pending_tool(self) -> None:
        pending = self._pending_tool_turn
        if pending is None or self.state.pending_tool_approval is None:
            await self._stream_text("warning", "There is no pending tool approval.")
            return
        self.state.pending_tool_approval = None
        self._pending_tool_turn = None
        reply = (
            f"Stopped before running `{pending.approval.display}`. "
            "If you still want that access, approve it next time or narrow the request to files inside the workspace."
        )
        self.state.last_reply = reply
        await self._stream_text("warning", "Pending tool request denied.")
        await self._stream_text("reply", reply)
        await self.bus.publish(AgentEvent(EventKind.REPLY, reply))

    def toggle_log(self, step_number: int) -> bool:
        if step_number not in self.state.logs:
            return False
        if step_number in self.state.expanded_logs:
            self.state.expanded_logs.remove(step_number)
        else:
            self.state.expanded_logs.add(step_number)
        return True

    def clear_session(self) -> None:
        uploaded = list(self.state.uploaded_files)
        snapshots = list(self.state.snapshots[:2])
        flows = list(self.state.flows)
        branch = self.state.current_branch
        model = self.state.model
        backend = self.state.backend
        thinking_enabled = self.state.thinking_enabled
        thinking_budget_tokens = self.state.thinking_budget_tokens
        active_prompt_names = list(self.state.active_prompt_names)
        export_dir = self.state.export_dir
        self.state.__dict__.update(SessionState().__dict__)
        self.state.uploaded_files = uploaded
        self.state.snapshots = snapshots
        self.state.flows = flows
        self.state.current_branch = branch
        self.state.model = model
        self.state.backend = backend
        self.state.thinking_enabled = thinking_enabled
        self.state.thinking_budget_tokens = thinking_budget_tokens
        self.state.active_prompt_names = active_prompt_names
        self.state.export_dir = export_dir
        self.state.show_plan = False
        self.state.show_logs = False
        self.state.show_execution = False
        self.state.pending_tool_approval = None
        self._pending_tool_turn = None
        self.state.stream_entries = [
            StreamEntry("system", "Conversation cleared. Uploaded files and VCS preview were preserved."),
        ]
        self.state.todo_items = [
            TodoItem("Start a fresh prompt", active=True),
            TodoItem("Reuse uploaded context if needed"),
        ]

    def create_branch(self, name: str) -> None:
        self.state.current_branch = name
        self.state.snapshots.insert(0, Snapshot(short_sha(), f"branch:{name}"))

    async def _handle_direct_reply(self, query: str) -> None:
        self.state.pending_query = None
        self.state.last_query = query
        self.state.last_reply = None
        self.state.pending_approval = False
        self.state.pending_tool_approval = None
        self._pending_tool_turn = None
        self.state.show_execution = False
        self.state.plan_steps.clear()
        self.state.logs.clear()
        self.state.todo_items = [
            TodoItem("Understand operator intent", done=True),
            TodoItem("Answer directly in conversation mode", active=True),
        ]
        self.state.backend = "local"

        self._append_stream("user", query)
        await self.bus.publish(AgentEvent(EventKind.THINKING, "Conversation turn"))
        await self._emit_entry(
            "reasoning",
            (
                "Conversation mode is active. I can inspect the repo inline with tools like ripgrep, read files directly, and ask for approval before leaving the workspace or running a broader command."
            ),
        )
        result = await self.conversation.handle_turn(query=query, state=self.state, emit=self._emit_conversation_signal)
        self._pending_tool_turn = result.pending
        self.state.pending_tool_approval = result.pending.approval if result.pending is not None else None
        if result.reply:
            self.state.last_reply = result.reply
            if not self._last_entry_has_text("reply", result.reply):
                await self._stream_text("reply", result.reply)
        await self.bus.publish(AgentEvent(EventKind.REPLY, result.reply or "Conversation turn complete"))

    async def _emit_conversation_signal(self, kind: str, text: str) -> None:
        if kind == "reasoning_stream":
            self._append_stream_delta("reasoning", text)
            await self.bus.publish(AgentEvent(EventKind.TOKEN_STREAM, text, {"role": "reasoning"}))
            return
        if kind == "reply_stream":
            self._append_stream_delta("reply", text)
            await self.bus.publish(AgentEvent(EventKind.TOKEN_STREAM, text, {"role": "reply"}))
            return
        await self._emit_entry(kind, text)

    async def _emit_entry(self, role: str, text: str) -> None:
        self._append_stream(role, text)
        event_map = {
            "tool": EventKind.TOOL_START,
            "tool_output": EventKind.TOOL_OUTPUT,
        }
        event_kind = event_map.get(role, EventKind.THINKING)
        await self.bus.publish(AgentEvent(event_kind, text, {"role": role}))

    def _append_stream_delta(self, role: str, text: str) -> None:
        if not text:
            return
        if self.state.stream_entries and self.state.stream_entries[-1].role == role and self.state.stream_entries[-1].meta.get(
            "streaming"
        ):
            self.state.stream_entries[-1].text += text
            return
        self.state.stream_entries.append(StreamEntry(role=role, text=text, meta={"streaming": True}))

    def _last_entry_has_text(self, role: str, text: str) -> bool:
        if not self.state.stream_entries:
            return False
        entry = self.state.stream_entries[-1]
        return entry.role == role and entry.text.strip() == text.strip()

    async def _stream_text(self, role: str, text: str) -> None:
        self._append_stream(role, "")
        for character in text:
            self.state.stream_entries[-1].text += character
            await self.bus.publish(AgentEvent(EventKind.TOKEN_STREAM, character, {"role": role}))
            await asyncio.sleep(0.003)

    def _append_stream(self, role: str, text: str) -> None:
        self.state.stream_entries.append(StreamEntry(role=role, text=text))

    def _build_plan(self, query: str) -> list[PlanStep]:
        upload_step = None
        if self.state.uploaded_files:
            upload_step = PlanStep(
                index=1,
                title=f"Inspect uploaded context ({len(self.state.uploaded_files)} file{'s' if len(self.state.uploaded_files) != 1 else ''})",
                tool_hint="document_search",
                detail="Use staged workspace inputs to ground the next steps.",
            )

        steps: list[PlanStep] = []
        if upload_step is not None:
            steps.append(upload_step)

        next_index = len(steps) + 1
        steps.extend(
            [
                PlanStep(
                    index=next_index,
                    title="Map the operator request into a visible workflow",
                    tool_hint="planner",
                    detail=query,
                ),
                PlanStep(
                    index=next_index + 1,
                    title="Render plan, execution, and VCS state in the terminal",
                    tool_hint="todo_write",
                    detail="Drive the mock event bus for the UI panels.",
                ),
                PlanStep(
                    index=next_index + 2,
                    title="Summarize the current build state and future target",
                    tool_hint="flow_crystallize",
                    detail="Keep the operator aware of current scope versus later phases.",
                ),
            ]
        )
        return steps

    def _pick_failure_step(self, query: str) -> int | None:
        lowered = query.lower()
        if "retry" in lowered or "fail" in lowered:
            return 2
        return None
