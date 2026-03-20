from __future__ import annotations

import shlex
from dataclasses import dataclass


COMMAND_HELP: dict[str, str] = {
    "/upload <file>": "Stage a local document or audio file for the mock session.",
    "/run": "Restage the last prompt so you can replay the UX.",
    "/plan": "Toggle the hidden plan panel.",
    "/logs": "Toggle the hidden logs panel.",
    "/exit": "Exit the TUI.",
    "/approve": "Approve the staged plan and begin mock execution.",
    "/reject": "Drop the staged plan and wait for a new prompt.",
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
    "/plan",
    "/reject",
    "/retry",
    "/run",
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
    lines.append("Tip: the default view is stream-first. Use /plan or /logs only when you want those panels.")
    lines.append("Tip: include the word 'retry' in a prompt if you want to exercise the /retry path.")
    return "\n".join(lines)
