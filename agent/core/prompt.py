from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from agent.tools import ToolRegistry

if TYPE_CHECKING:
    from agent.core.session import SessionState


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CONVERSATION_TOOL_NAMES = (
    "list_files",
    "search_files",
    "read_file",
    "list_code_definition_names",
    "git_status",
    "execute_command",
    "use_skill",
)
PLANNER_TOOL_NAMES = (
    "list_files",
    "search_files",
    "read_file",
    "list_code_definition_names",
    "git_status",
    "use_skill",
)
EXECUTION_TOOL_NAMES = (
    "list_files",
    "search_files",
    "read_file",
    "list_code_definition_names",
    "git_status",
    "execute_command",
    "use_skill",
)


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
    UtilityDefinition("/approve", "Approve a pending tool request or a staged plan."),
    UtilityDefinition("/reject", "Reject a pending tool request or a staged plan."),
    UtilityDefinition("/retry", "Retry the last failed step in a staged execution."),
    UtilityDefinition("/upload <file>", "Stage a local file for the session as simulated context."),
    UtilityDefinition("/vcs ...", "Inspect mock snapshot history, diffs, restore, and branching."),
    UtilityDefinition("/export", "Write the session summary to markdown and JSON."),
    UtilityDefinition("list_files", "Inspect the current repo layout with ripgrep before answering repo questions."),
    UtilityDefinition("search_files", "Search the current workspace with ripgrep before answering code questions."),
    UtilityDefinition("read_file", "Read a file directly from the workspace to answer file-specific questions."),
    UtilityDefinition("list_code_definition_names", "Map top-level classes and functions without reading full files first."),
    UtilityDefinition("git_status", "Inspect the local repository state before answering git-aware questions."),
    UtilityDefinition("execute_command", "Run a command when inspection needs shell output. Read-only commands can be auto-approved; broader commands ask first."),
    UtilityDefinition("use_skill", "Load a local skill pack like pdf, docx, or xlsx when the task is document-specific."),
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
        self.registry = ToolRegistry()

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
        skills = self.registry.skills.list()
        return {
            "session_id": session_id,
            "model": model,
            "branch": branch,
            "snapshot_head": snapshot,
            "uploaded_files": uploaded_files,
            "live_utilities": self._format_utility_block(LIVE_UTILITIES),
            "planned_utilities": self._format_utility_block(PLANNED_UTILITIES),
            "prompt_stack": ", ".join(self.active_prompt_names()),
            "approval_policy": self._approval_policy(),
            "thinking_policy": self._thinking_policy(state),
            "conversation_tools_xml": self._format_tools_xml(CONVERSATION_TOOL_NAMES),
            "planner_tools_xml": self._format_tools_xml(PLANNER_TOOL_NAMES),
            "execution_tools_xml": self._format_tools_xml(EXECUTION_TOOL_NAMES),
            "skills_xml": self._format_skills_xml(skills),
            "tool_selection_policy": self._tool_selection_policy(),
            "mode_routing_policy": self._mode_routing_policy(),
        }

    def _format_utility_block(self, utilities: tuple[UtilityDefinition, ...]) -> str:
        return "\n".join(f"- {utility.name}: {utility.description}" for utility in utilities)

    def _format_tools_xml(self, names: tuple[str, ...]) -> str:
        blocks: list[str] = []
        for name in names:
            tool = self.registry.get(name)
            if tool is None:
                continue
            schema = tool.schema()
            blocks.append(
                "\n".join(
                    [
                        f'<tool name="{tool.name}" permission="{tool.permission}">',
                        f"<description>{tool.description}</description>",
                        "<inputs>",
                        self._format_input_properties(schema.get("input_schema", {}).get("properties", {})),
                        "</inputs>",
                        "</tool>",
                    ]
                )
            )
        return "\n".join(blocks) if blocks else "<toolset>none</toolset>"

    def _format_input_properties(self, properties: dict[str, object]) -> str:
        if not properties:
            return "  <input name=\"none\">No parameters.</input>"
        lines: list[str] = []
        for name, meta in properties.items():
            description = ""
            if isinstance(meta, dict):
                description = str(meta.get("description", "")).strip()
            lines.append(f'  <input name="{name}">{description or "No description."}</input>')
        return "\n".join(lines)

    def _format_skills_xml(self, skills: list[object]) -> str:
        if not skills:
            return "<skills><skill name=\"none\">No local skills are currently available.</skill></skills>"
        lines = ["<skills>"]
        for skill in skills:
            name = getattr(skill, "name", "unknown")
            description = getattr(skill, "description", "No description provided.")
            lines.append(f'  <skill name="{name}">{description}</skill>')
        lines.append("</skills>")
        return "\n".join(lines)

    def _approval_policy(self) -> str:
        return "\n".join(
            [
                "- No YOLO mode. Never assume broad or destructive permission.",
                "- Read-only repo tools inside the workspace may run inline in conversation mode.",
                "- Reads/searches outside the workspace must pause and wait for /approve or /reject.",
                "- Non-allowlisted shell commands must pause and wait for /approve or /reject.",
                "- Multi-step execution, file writes, and workflow mutation belong behind /plan <request> and then /approve.",
                "- If approval is denied, report the denial honestly and continue with a narrower safe path when possible.",
            ]
        )

    def _thinking_policy(self, state: SessionState | None) -> str:
        enabled = state.thinking_enabled if state else False
        budget = state.thinking_budget_tokens if state else 2048
        return "\n".join(
            [
                f"- Thinking mode is currently {'enabled' if enabled else 'disabled'} for this session.",
                f"- Configured thinking budget: {budget} tokens.",
                "- Use extended thinking only when the task is complex, ambiguous, or tool-planning heavy.",
                "- Do not force heavy thinking for greetings, direct factual questions, or straightforward repo lookups.",
                "- If backend thinking is unavailable, keep agent_reasoning concise and operational instead of fabricating hidden chain-of-thought.",
            ]
        )

    def _tool_selection_policy(self) -> str:
        return "\n".join(
            [
                "- Use the minimum sufficient tool set for the current turn.",
                "- Prefer orientation tools before deep reads when the repo area is still unclear.",
                "- Prefer search_files before execute_command for code lookup tasks.",
                "- Prefer read_file after search_files or when the operator names a specific file.",
                "- Use use_skill when the task clearly matches a specialized local skill.",
                "- Before every tool call, emit one short agent_reasoning line explaining why that tool is next.",
            ]
        )

    def _mode_routing_policy(self) -> str:
        return "\n".join(
            [
                "- Default to conversation mode for plain prompts.",
                "- Route to plan mode only when the operator explicitly uses /plan <request> or clearly asks for staged executable work.",
                "- In conversation mode, ground answers with read-only tools when useful and stay in the transcript.",
                "- In plan mode, produce an approval-ready plan and wait for operator control rather than auto-switching into execution.",
            ]
        )
