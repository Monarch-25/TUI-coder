from __future__ import annotations

import shlex
from dataclasses import dataclass


COMMAND_HELP: dict[str, str] = {
    "/upload <file>": "Stage a local document or audio file for the mock session.",
    "/run": "Restage the most recent explicit plan-mode request.",
    "/plan <request>": "Enter plan mode explicitly for a request and reveal the plan panel.",
    "/plan": "Toggle the hidden plan panel after a plan has been staged.",
    "/logs": "Toggle the hidden logs panel.",
    "/thinking on|off|budget <n>": "Toggle Bedrock Claude thinking mode or set its token budget.",
    "/exit": "Exit the TUI.",
    "/approve": "Approve a pending tool request or the staged plan.",
    "/reject": "Reject a pending tool request or drop the staged plan.",
    "/retry": "Retry the last failed step if the demo injected a failure.",
    "/expand <n>": "Toggle log expansion for step n.",
    "/model sonnet|opus": "Switch the displayed session model.",
    "/vcs log": "Show snapshot history in the stream panel.",
    "/vcs diff <sha>": "Show a placeholder diff for a snapshot.",
    "/vcs restore <sha>": "Mark a snapshot as restored in the session stream.",
    "/vcs branch <name>": "Create a mock branch and move HEAD there.",
    "/cost": "Show cumulative mock token and cost counters.",
    "/flows": "List prototype flows currently visible to the operator.",
    "/export": "Write a markdown and json summary of the current mock session.",
    "/clear": "Clear the conversation while keeping uploaded files.",
    "/help": "Show the available slash commands.",
}

COMMAND_SUGGESTIONS: tuple[str, ...] = (
    "/approve",
    "/clear",
    "/cost",
    "/exit",
    "/export",
    "/flows",
    "/help",
    "/logs",
    "/model sonnet",
    "/model opus",
    "/plan ",
    "/plan",
    "/reject",
    "/retry",
    "/run",
    "/thinking",
    "/thinking budget ",
    "/thinking off",
    "/thinking on",
    "/upload ",
    "/vcs branch ",
    "/vcs diff ",
    "/vcs log",
    "/vcs restore ",
    "/expand ",
)


@dataclass(slots=True)
class ParsedCommand:
    name: str
    args: list[str]
    raw: str


def parse_command(raw: str) -> ParsedCommand:
    if not raw.startswith("/"):
        raise ValueError("Command input must start with '/'.")
    parts = shlex.split(raw)
    if not parts:
        raise ValueError("Empty command.")
    return ParsedCommand(parts[0][1:], parts[1:], raw)


def help_text() -> str:
    lines = ["Slash commands available in this prototype:"]
    for command, description in COMMAND_HELP.items():
        lines.append(f"{command:<22} {description}")
    lines.append("Tip: plain prompts always stay in conversation mode. Use /plan <request> when you explicitly want planning.")
    lines.append("Tip: inline conversation turns can show reasoning, tool calls, tool output, and approval prompts without opening the logs panel.")
    lines.append("Tip: the conversation tool set now includes `rg`-style search, file reads, code-definition listing, safe shell commands, and local skill packs.")
    lines.append("Tip: include the word 'retry' in a prompt if you want to exercise the /retry path.")
    return "\n".join(lines)
