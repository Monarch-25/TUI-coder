from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.session import SessionState


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class UtilityDefinition:
    name: str
    description: str
    availability: str = "live"


@dataclass(frozen=True)
class PromptSpec:
    name: str
    filename: str
    purpose: str
    upstream_reference: str


LIVE_UTILITIES: tuple[UtilityDefinition, ...] = (
    UtilityDefinition("/plan", "Reveal the hidden plan panel for the current turn."),
    UtilityDefinition("/logs", "Reveal the hidden logs panel for the current turn."),
    UtilityDefinition("/thinking on|off|budget <n>", "Toggle Bedrock Claude thinking mode or set the reasoning-token budget."),
    UtilityDefinition("/approve", "Approve a staged plan and begin execution."),
    UtilityDefinition("/reject", "Reject a staged plan and clear it."),
    UtilityDefinition("/retry", "Retry the last failed step in a staged execution."),
    UtilityDefinition("/upload <file>", "Stage a local file for the session as simulated context."),
    UtilityDefinition("/vcs ...", "Inspect mock snapshot history, diffs, restore, and branching."),
    UtilityDefinition("/export", "Write the session summary to markdown and JSON."),
    UtilityDefinition("workspace_files", "Inspect the current repo layout with a read-only workspace listing."),
    UtilityDefinition("workspace_search", "Search the current workspace with ripgrep before answering code questions."),
    UtilityDefinition("workspace_read", "Read a file directly from the workspace to answer file-specific questions."),
    UtilityDefinition("git_status", "Inspect the local repository state before answering git-aware questions."),
)


PLANNED_UTILITIES: tuple[UtilityDefinition, ...] = (
    UtilityDefinition("document_search", "Search indexed document chunks without sending full files to the model.", "planned"),
    UtilityDefinition("sql_query", "Query extracted tables and structured datasets.", "planned"),
    UtilityDefinition("todo_write", "Update the live session todo list.", "planned"),
    UtilityDefinition("snapshot_create", "Create a VCS-style snapshot after meaningful work.", "planned"),
    UtilityDefinition("table_extract", "Extract table structure from loaded documents.", "planned"),
    UtilityDefinition("summarize", "Summarize source material or prior turns for memory.", "planned"),
)


PROMPT_SPECS: tuple[PromptSpec, ...] = (
    PromptSpec(
        name="conversation_system",
        filename="conversation_system.md",
        purpose="Default terminal conversation behavior and honesty contract.",
        upstream_reference="https://github.com/Piebald-AI/claude-code-system-prompts",
    ),
    PromptSpec(
        name="planner_system",
        filename="planner_system.md",
        purpose="Structured planning prompt for approval-gated execution.",
        upstream_reference="https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-plan-mode-enhanced.md",
    ),
    PromptSpec(
        name="executor_system",
        filename="executor_system.md",
        purpose="Execution prompt for approved plans and live tool reporting.",
        upstream_reference="https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-explore.md",
    ),
    PromptSpec(
        name="conversation_summary",
        filename="conversation_summary.md",
        purpose="Prompt for compressing completed turns into memory-safe summaries.",
        upstream_reference="https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-conversation-summarization.md",
    ),
    PromptSpec(
        name="next_prompt_suggestion",
        filename="next_prompt_suggestion.md",
        purpose="Prompt for proposing the next useful operator action.",
        upstream_reference="https://github.com/Piebald-AI/claude-code-system-prompts",
    ),
)


class PromptLibrary:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or PROMPTS_DIR

    def specs(self) -> tuple[PromptSpec, ...]:
        return PROMPT_SPECS

    def active_prompt_names(self) -> list[str]:
        return [spec.name for spec in PROMPT_SPECS]

    def render(self, prompt_name: str, state: SessionState | None = None) -> str:
        spec = next(spec for spec in PROMPT_SPECS if spec.name == prompt_name)
        template = Template((self.prompts_dir / spec.filename).read_text(encoding="utf-8"))
        return template.safe_substitute(self._context(state))

    def render_all(self, state: SessionState | None = None) -> dict[str, str]:
        return {spec.name: self.render(spec.name, state) for spec in PROMPT_SPECS}

    def describe(self) -> list[str]:
        return [f"{spec.name}: {spec.purpose}" for spec in PROMPT_SPECS]

    def _context(self, state: SessionState | None) -> dict[str, str]:
        uploaded_files = ", ".join(state.uploaded_files) if state and state.uploaded_files else "none"
        session_id = state.session_id if state else "preview"
        model = state.model if state else "sonnet"
        branch = state.current_branch if state else "main"
        snapshot = state.head if state else "none"
        return {
            "session_id": session_id,
            "model": model,
            "branch": branch,
            "snapshot_head": snapshot,
            "uploaded_files": uploaded_files,
            "live_utilities": self._format_utility_block(LIVE_UTILITIES),
            "planned_utilities": self._format_utility_block(PLANNED_UTILITIES),
            "prompt_stack": ", ".join(self.active_prompt_names()),
        }

    def _format_utility_block(self, utilities: tuple[UtilityDefinition, ...]) -> str:
        return "\n".join(f"- {utility.name}: {utility.description}" for utility in utilities)
