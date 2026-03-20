from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from agent.core.bedrock import BedrockClient, BedrockUnavailable
from agent.core.prompt import CONVERSATION_TOOL_NAMES
from agent.tools import ApprovalRequest, ToolIntent, ToolObservation, ToolRegistry

if TYPE_CHECKING:
    from agent.core.prompt import PromptLibrary
    from agent.core.session import SessionState


EmitFn = Callable[[str, str], Awaitable[None]]

STOP_WORDS = {
    "about",
    "agent",
    "and",
    "based",
    "build",
    "builder",
    "can",
    "code",
    "coder",
    "does",
    "explain",
    "file",
    "files",
    "for",
    "from",
    "have",
    "help",
    "how",
    "implement",
    "like",
    "mode",
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
    "works",
}

GREETINGS = {"hello", "hey", "heyy", "hi", "yo", "sup"}


@dataclass(frozen=True)
class PendingConversationTurn:
    query: str
    approval: ApprovalRequest
    pending_intent: ToolIntent
    remaining_actions: list[ToolIntent] = field(default_factory=list)
    observations: list[ToolObservation] = field(default_factory=list)


@dataclass(frozen=True)
class ConversationTurnResult:
    reply: str | None = None
    pending: PendingConversationTurn | None = None


class ConversationRuntime:
    def __init__(self, root: Path | None = None, registry: ToolRegistry | None = None) -> None:
        self.root = root or Path.cwd()
        self.registry = registry or ToolRegistry(self.root)

    def plan_actions(self, query: str) -> list[ToolIntent]:
        lowered = query.lower()
        if self._is_greeting(lowered):
            return []

        actions: list[ToolIntent] = []
        skill = self.registry.skills.match_for_query(query)
        if skill is not None:
            actions.append(
                ToolIntent(
                    "use_skill",
                    f"The request matches the `{skill.name}` skill pack, so I should load its constraints and helper scripts before answering.",
                    {"skill_name": skill.name, "goal": query},
                )
            )

        explicit_command = self._extract_explicit_command(query)
        if explicit_command:
            actions.append(
                ToolIntent(
                    "execute_command",
                    "The operator explicitly asked for command output, so I should run the command instead of paraphrasing it.",
                    {"command": explicit_command},
                )
            )

        file_mentions = self._extract_paths(query)
        directory_mentions = self._extract_directory_paths(query)

        if any(word in lowered for word in ("git", "branch", "status", "dirty", "diff")):
            actions.append(
                ToolIntent(
                    "git_status",
                    "Checking the repository state first keeps the answer grounded in the current checkout.",
                )
            )

        if any(word in lowered for word in ("repo", "repository", "codebase", "structure", "layout", "tree", "folder")):
            target = directory_mentions[0] if directory_mentions else "."
            actions.append(
                ToolIntent(
                    "list_files",
                    "Mapping the file layout first mirrors how strong coder TUIs build orientation before they explain the codebase.",
                    {"path": target},
                )
            )

        if file_mentions:
            for match in file_mentions[:2]:
                actions.append(
                    ToolIntent(
                        "read_file",
                        f"Reading {match} directly is the fastest way to answer a file-specific question without guessing.",
                        {"path": match},
                    )
                )
        else:
            target = directory_mentions[0] if directory_mentions else "."
            if any(
                phrase in lowered
                for phrase in ("function", "class", "definition", "entry point", "symbol", "architecture", "module")
            ):
                actions.append(
                    ToolIntent(
                        "list_code_definition_names",
                        "Listing top-level definitions gives a faster architectural map than opening large files immediately.",
                        {"path": target},
                    )
                )

            search_terms = self._extract_search_terms(query)
            if search_terms and any(
                word in lowered for word in ("find", "search", "where", "implemented", "reference", "usage", "uses")
            ):
                actions.append(
                    ToolIntent(
                        "search_files",
                        "Searching the workspace for the key terms shows where the relevant implementation lives.",
                        {"query": "|".join(search_terms[:4]), "path": target},
                    )
                )

        return self._dedupe(actions[:4])

    async def run_actions(
        self,
        *,
        query: str,
        actions: list[ToolIntent],
        emit: EmitFn,
        approved_first: bool = False,
        initial_observations: list[ToolObservation] | None = None,
    ) -> tuple[list[ToolObservation], PendingConversationTurn | None]:
        observations = list(initial_observations or [])
        approval_bypass = approved_first
        for index, action in enumerate(actions):
            await emit("reasoning", action.reason)
            await emit("tool", self.registry.display(action))
            result = await self.registry.execute_intent(action, approved=approval_bypass and index == 0)
            approval_bypass = False
            if result.needs_approval and result.approval is not None:
                await emit("warning", result.approval.message)
                return observations, PendingConversationTurn(
                    query=query,
                    approval=result.approval,
                    pending_intent=action,
                    remaining_actions=actions[index + 1 :],
                    observations=observations,
                )
            output = result.error or result.output or "[no output]"
            await emit("tool_output", output)
            observations.append(ToolObservation(action.name, result.display, output, action.arguments))
        return observations, None

    async def resume(self, pending: PendingConversationTurn, emit: EmitFn) -> tuple[list[ToolObservation], PendingConversationTurn | None]:
        actions = [pending.pending_intent, *pending.remaining_actions]
        return await self.run_actions(
            query=pending.query,
            actions=actions,
            emit=emit,
            approved_first=True,
            initial_observations=pending.observations,
        )

    def _extract_paths(self, query: str) -> list[str]:
        pattern = re.compile(r"([\w./~-]+\.(?:py|md|txt|json|toml|yaml|yml|tcss|js|jsx|ts|tsx|rs|go|java|kt|swift|pdf|docx|xlsx|csv|tsv))")
        return pattern.findall(query)

    def _extract_directory_paths(self, query: str) -> list[str]:
        candidates = re.findall(r"[\w./~-]+", query)
        matches: list[str] = []
        for candidate in candidates:
            if "." in Path(candidate).name and "/" not in candidate:
                continue
            path = Path(candidate).expanduser()
            if not path.is_absolute():
                path = self.root / path
            if path.exists() and path.is_dir():
                relative = path.resolve()
                try:
                    matches.append(relative.relative_to(self.root).as_posix() or ".")
                except ValueError:
                    matches.append(candidate)
        return matches[:2]

    def _extract_search_terms(self, query: str) -> list[str]:
        quoted = re.findall(r"[\"'`](.+?)[\"'`]", query)
        if quoted:
            return [token.strip() for token in quoted if token.strip()][:4]
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_./-]{2,}", query.lower())
        cleaned = [token.strip("./") for token in tokens if token not in STOP_WORDS]
        return cleaned[:6]

    def _extract_explicit_command(self, query: str) -> str | None:
        if match := re.search(r"`([^`]+)`", query):
            return match.group(1).strip()
        lowered = query.lower()
        prefixes = (
            "run ",
            "execute ",
            "show the output of ",
            "what does ",
        )
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return query[len(prefix) :].strip()
        return None

    def _is_greeting(self, lowered: str) -> bool:
        tokens = re.findall(r"[a-z]+", lowered)
        return len(tokens) <= 2 and all(token in GREETINGS for token in tokens)

    def _dedupe(self, actions: list[ToolIntent]) -> list[ToolIntent]:
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        unique: list[ToolIntent] = []
        for action in actions:
            key = (
                action.name,
                tuple(sorted((str(name), str(value)) for name, value in action.arguments.items())),
            )
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
    ) -> ConversationTurnResult:
        if self.bedrock.is_configured():
            try:
                reply = await self._handle_bedrock_turn(query=query, state=state, emit=emit)
                return ConversationTurnResult(reply=reply)
            except BedrockUnavailable as exc:
                state.backend = "local"
                await emit("reasoning", f"Bedrock fallback: {exc}")

        actions = self.runtime.plan_actions(query)
        observations, pending = await self.runtime.run_actions(query=query, actions=actions, emit=emit)
        if pending is not None:
            return ConversationTurnResult(pending=pending)
        reply = await self._answer(query=query, state=state, observations=observations)
        return ConversationTurnResult(reply=reply)

    async def resume_turn(
        self,
        *,
        pending: PendingConversationTurn,
        state: SessionState,
        emit: EmitFn,
    ) -> ConversationTurnResult:
        observations, next_pending = await self.runtime.resume(pending, emit)
        if next_pending is not None:
            return ConversationTurnResult(pending=next_pending)
        reply = await self._answer(query=pending.query, state=state, observations=observations)
        return ConversationTurnResult(reply=reply)

    async def _handle_bedrock_turn(
        self,
        *,
        query: str,
        state: SessionState,
        emit: EmitFn,
    ) -> str:
        state.backend = "bedrock"
        system_prompt = self.prompts.render("conversation_system", state)
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [{"type": "text", "text": query}],
            }
        ]
        tools = self.runtime.registry.anthropic_tools(CONVERSATION_TOOL_NAMES)
        while True:
            round_result = await self.bedrock.run_tool_round(
                system_prompt=system_prompt,
                messages=messages,
                state=state,
                tools=tools,
                on_reasoning=lambda text: emit("reasoning_stream", text),
            )
            if round_result.tool_calls:
                if round_result.text.strip():
                    await emit("reasoning", round_result.text.strip())
                tool_results: list[dict[str, str]] = []
                for call in round_result.tool_calls:
                    intent = ToolIntent(
                        name=call.name,
                        reason=round_result.text.strip() or f"Claude selected {call.name} to ground the next answer step.",
                        arguments=call.input,
                    )
                    await emit("tool", self.runtime.registry.display(intent))
                    result = await self.runtime.registry.execute_intent(intent)
                    if result.needs_approval and result.approval is not None:
                        await emit("warning", result.approval.message)
                        return (
                            "Claude requested an approval-gated tool during a live Bedrock turn. "
                            "This prototype can resume approval-gated tools only in local conversation mode right now."
                        )
                    output = result.error or result.output or "[no output]"
                    await emit("tool_output", output)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.tool_use_id,
                            "content": output,
                        }
                    )
                messages.append({"role": "assistant", "content": round_result.assistant_content()})
                messages.append({"role": "user", "content": tool_results})
                continue
            return round_result.text.strip()

    async def _answer(
        self,
        *,
        query: str,
        state: SessionState,
        observations: list[ToolObservation],
    ) -> str:
        del state
        return self._local_reply(query, observations)

    def _local_reply(self, query: str, observations: list[ToolObservation]) -> str:
        if not observations:
            return (
                "I can answer directly, inspect the repo with tools like `rg`, or ask for approval before leaving the workspace or running a broader command. "
                "If you want multi-step execution instead of conversation, use `/plan <request>`."
            )
        summary = []
        for observation in observations:
            first_line = observation.output.splitlines()[0] if observation.output else "[no output]"
            summary.append(f"{observation.display}: {first_line}")
        joined = "\n".join(f"- {line}" for line in summary)
        if "git" in query.lower() or "status" in query.lower():
            return f"I checked the repository state directly.\n{joined}"
        if any(word in query.lower() for word in ("repo", "repository", "structure", "layout")):
            return (
                "I grounded the answer by mapping the repo first and then drilling into the most relevant signals.\n"
                f"{joined}\n"
                "Point me at a file, directory, symbol, or command if you want a deeper pass."
            )
        return (
            "I grounded the answer with live tool output instead of guessing.\n"
            f"{joined}\n"
            "If you want, I can keep digging with a file path, symbol name, or explicit command."
        )
