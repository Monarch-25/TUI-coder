from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from agent.core.bedrock import BedrockClient, BedrockUnavailable

if TYPE_CHECKING:
    from agent.core.prompt import PromptLibrary
    from agent.core.session import SessionState


EmitFn = Callable[[str, str], Awaitable[None]]

STOP_WORDS = {
    "about",
    "agent",
    "and",
    "build",
    "builder",
    "can",
    "code",
    "coder",
    "does",
    "explain",
    "for",
    "from",
    "have",
    "help",
    "how",
    "implement",
    "like",
    "plan",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "those",
    "what",
    "where",
    "which",
    "with",
    "workflow",
}


@dataclass(frozen=True)
class ToolAction:
    name: str
    reason: str
    display: str
    payload: str | None = None


@dataclass(frozen=True)
class ToolObservation:
    name: str
    display: str
    output: str


class ConversationRuntime:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()

    def plan_actions(self, query: str) -> list[ToolAction]:
        lowered = query.lower()
        actions: list[ToolAction] = []
        file_mentions = self._extract_paths(query)
        if any(word in lowered for word in ("git", "branch", "status", "dirty", "diff")):
            actions.append(
                ToolAction(
                    name="git_status",
                    reason="Checking the repository state first keeps the answer grounded in the current workspace.",
                    display="git status --short --branch",
                )
            )
        if any(word in lowered for word in ("repo", "repository", "codebase", "structure", "files", "layout", "tree")):
            actions.append(
                ToolAction(
                    name="workspace_files",
                    reason="Inspecting the workspace structure first mirrors how coder TUIs ground their answers before suggesting next steps.",
                    display="rg --files",
                )
            )
        if file_mentions:
            for match in file_mentions[:2]:
                actions.append(
                    ToolAction(
                        name="read_file",
                        reason=f"Reading {match} directly is the fastest way to answer a file-specific question without guessing.",
                        display=f"read {match}",
                        payload=match,
                    )
                )
        else:
            terms = self._extract_search_terms(query)
            if terms:
                pattern = "|".join(terms[:3])
                actions.append(
                    ToolAction(
                        name="search_code",
                        reason="Searching the workspace for the request vocabulary shows where the relevant implementation or docs live.",
                        display=f'rg -n -S "{pattern}"',
                        payload=pattern,
                    )
                )
        return self._dedupe(actions[:3])

    async def run_actions(self, actions: list[ToolAction], emit: EmitFn) -> list[ToolObservation]:
        observations: list[ToolObservation] = []
        for action in actions:
            await emit("reasoning", action.reason)
            await emit("tool", action.display)
            output = await self._execute(action)
            await emit("tool_output", output)
            observations.append(ToolObservation(action.name, action.display, output))
        return observations

    async def _execute(self, action: ToolAction) -> str:
        if action.name == "git_status":
            return await self._run_command(["git", "status", "--short", "--branch"])
        if action.name == "workspace_files":
            return await self._workspace_files()
        if action.name == "search_code" and action.payload:
            return await self._run_command(
                ["rg", "-n", "-S", "--hidden", "--glob", "!__pycache__/**", action.payload, "."]
            )
        if action.name == "read_file" and action.payload:
            return await self._read_file(action.payload)
        return "Tool is not available in this prototype."

    async def _workspace_files(self) -> str:
        listing = await self._run_command(["rg", "--files"], truncate=None)
        files = [line for line in listing.splitlines() if line]
        if not files:
            return "No files found."
        buckets: dict[str, int] = {}
        for file_path in files:
            top = file_path.split("/", 1)[0]
            buckets[top] = buckets.get(top, 0) + 1
        summary = ", ".join(f"{name}:{count}" for name, count in sorted(buckets.items()))
        preview = "\n".join(files[:18])
        return f"Top-level counts: {summary}\n---\n{preview}"

    async def _read_file(self, raw_path: str) -> str:
        path = (self.root / raw_path).resolve()
        if self.root not in path.parents and path != self.root:
            return f"Refusing to read outside the workspace: {raw_path}"
        if not path.exists():
            return f"File not found: {raw_path}"
        lines = path.read_text(encoding="utf-8").splitlines()
        excerpt = "\n".join(f"{index + 1:>4} {line}" for index, line in enumerate(lines[:120]))
        if len(lines) > 120:
            excerpt += "\n... [truncated]"
        return excerpt or "[empty file]"

    async def _run_command(self, command: list[str], truncate: int | None = 20) -> str:
        def inner() -> str:
            completed = subprocess.run(
                command,
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
            )
            output = completed.stdout.strip() or completed.stderr.strip() or "[no output]"
            lines = output.splitlines()
            if truncate is not None and len(lines) > truncate:
                lines = lines[:truncate] + ["... [truncated]"]
            return "\n".join(lines)

        return await asyncio.to_thread(inner)

    def _extract_paths(self, query: str) -> list[str]:
        pattern = re.compile(r"([\w./-]+\.(?:py|md|txt|json|toml|yaml|yml|tcss))")
        return pattern.findall(query)

    def _extract_search_terms(self, query: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_-]{2,}", query.lower())
        return [token for token in tokens if token not in STOP_WORDS][:6]

    def _dedupe(self, actions: list[ToolAction]) -> list[ToolAction]:
        seen: set[tuple[str, str | None]] = set()
        unique: list[ToolAction] = []
        for action in actions:
            key = (action.name, action.payload)
            if key in seen:
                continue
            seen.add(key)
            unique.append(action)
        return unique


class ConversationAgent:
    def __init__(
        self,
        prompts: PromptLibrary,
        bedrock: BedrockClient | None = None,
        runtime: ConversationRuntime | None = None,
    ) -> None:
        self.prompts = prompts
        self.bedrock = bedrock or BedrockClient()
        self.runtime = runtime or ConversationRuntime()

    async def handle_turn(
        self,
        *,
        query: str,
        state: SessionState,
        emit: EmitFn,
    ) -> str:
        actions = self.runtime.plan_actions(query)
        observations = await self.runtime.run_actions(actions, emit)
        return await self._answer(query=query, state=state, observations=observations, emit=emit)

    async def _answer(
        self,
        *,
        query: str,
        state: SessionState,
        observations: list[ToolObservation],
        emit: EmitFn,
    ) -> str:
        system_prompt = self.prompts.render("conversation_system", state)
        observation_block = self._format_observations(observations)
        user_prompt = (
            "Operator query:\n"
            f"{query}\n\n"
            "Read-only workspace observations:\n"
            f"{observation_block}\n\n"
            "Respond in a terminal-friendly way. Explain concrete findings first, then suggest the next useful action if relevant."
        )
        if self.bedrock.is_configured():
            state.backend = "bedrock"
            try:
                return await self._stream_bedrock_reply(system_prompt, user_prompt, state, emit)
            except BedrockUnavailable as exc:
                state.backend = "local"
                await emit("reasoning", f"Bedrock fallback: {exc}")
        else:
            state.backend = "local"
            if state.thinking_enabled:
                await emit(
                    "reasoning",
                    "Thinking mode is enabled and will be sent to Bedrock once AWS credentials are configured. Using the local fallback for this turn.",
                )
        return self._local_reply(query, observations)

    async def _stream_bedrock_reply(
        self,
        system_prompt: str,
        user_prompt: str,
        state: SessionState,
        emit: EmitFn,
    ) -> str:
        reply_chunks: list[str] = []
        async for delta in self.bedrock.stream_conversation(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            state=state,
        ):
            await emit(f"{delta.kind}_stream", delta.text)
            if delta.kind == "reply":
                reply_chunks.append(delta.text)
        return "".join(reply_chunks).strip()

    def _format_observations(self, observations: list[ToolObservation]) -> str:
        if not observations:
            return "- No workspace tools were needed."
        blocks = []
        for observation in observations:
            blocks.append(
                f"- Tool: {observation.display}\n"
                f"  Output:\n{self._indent(observation.output, '    ')}"
            )
        return "\n".join(blocks)

    def _local_reply(self, query: str, observations: list[ToolObservation]) -> str:
        if not observations:
            return (
                "I can answer directly or inspect the workspace with read-only tools. "
                "If you want execution instead of analysis, ask for a concrete implementation task and I'll stage a plan."
            )
        summary = []
        for observation in observations:
            first_line = observation.output.splitlines()[0] if observation.output else "[no output]"
            summary.append(f"{observation.display}: {first_line}")
        joined = "\n".join(f"- {line}" for line in summary)
        if "codebase" in query.lower() or "structure" in query.lower():
            return (
                "I inspected the workspace directly. The immediate structure signals are below, which is the same grounding step strong coder TUIs surface before they answer.\n"
                f"{joined}\n"
                "If you want, I can now drill into a specific file, subsystem, or slash-command flow."
            )
        if "git" in query.lower() or "status" in query.lower():
            return f"I checked the repository state directly.\n{joined}"
        return (
            "I grounded the answer with read-only workspace inspection instead of guessing.\n"
            f"{joined}\n"
            "If you want deeper analysis, point me at a file, symbol, or workflow."
        )

    def _indent(self, text: str, prefix: str) -> str:
        return "\n".join(prefix + line for line in text.splitlines())
