from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path
from typing import Any

from agent.tools.base import ApprovalRequest, Tool, ToolContext, ToolExecutionResult, ToolIntent
from agent.tools.skills import SkillLibrary


SOURCE_GLOBS = (
    "*.py",
    "*.js",
    "*.jsx",
    "*.ts",
    "*.tsx",
    "*.rs",
    "*.go",
    "*.java",
    "*.kt",
    "*.swift",
    "*.rb",
)


class ListFilesTool:
    name = "list_files"
    description = (
        "Use this tool to inspect the file layout of a directory before answering questions about repo structure or choosing a file to read. "
        "Prefer it when the operator asks about architecture, modules, folders, or the overall codebase shape. "
        "It returns a ripgrep-backed file listing and may summarize large workspaces by top-level folders so the result stays navigable in a terminal. "
        "Do not use it when you already know the exact file to inspect or when a content search would answer the question more directly."
    )
    permission = "read"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to inspect. Defaults to the current workspace root.",
                    }
                },
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        target = arguments.get("path") or "."
        return f"rg --files {target}"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        raw = str(arguments.get("path") or ".")
        resolved = _resolve_path(context.root, raw)
        if _outside_workspace(context.root, resolved):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The agent wants to inspect files outside the current workspace.",
                message=f"Approval required to list files outside the workspace: {raw}. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        raw = str(arguments.get("path") or ".")
        target = _resolve_path(context.root, raw)
        if not target.exists():
            return f"Path not found: {raw}"
        if target.is_file():
            return target.name
        output = await _run_command(["rg", "--files", str(target)], cwd=context.root)
        lines = [line for line in output.splitlines() if line]
        if not lines:
            return "No files found."
        if target == context.root:
            buckets: dict[str, int] = {}
            for line in lines:
                top = line.split("/", 1)[0]
                buckets[top] = buckets.get(top, 0) + 1
            summary = ", ".join(f"{name}:{count}" for name, count in sorted(buckets.items()))
            return f"Top-level counts: {summary}\n---\n" + "\n".join(lines[:60])
        return "\n".join(lines[:80])


class SearchFilesTool:
    name = "search_files"
    description = (
        "Use this tool to search code and text with ripgrep when you need to locate where a symbol, phrase, route, command, or concept is implemented. "
        "Prefer it for questions like where something lives, where it is referenced, or which files mention a feature. "
        "The query can be a literal string or regex-style pattern, and the tool returns matching file paths and line numbers to guide the next step. "
        "Do not use it when the operator already named the exact file to read or when a directory listing would provide better initial orientation."
    )
    permission = "read"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The literal text or regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file path to search within. Defaults to the current workspace root.",
                    },
                },
                "required": ["query"],
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query", ""))
        target = str(arguments.get("path") or ".")
        return f'rg -n --hidden --smart-case "{query}" {target}'

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        raw = str(arguments.get("path") or ".")
        resolved = _resolve_path(context.root, raw)
        if _outside_workspace(context.root, resolved):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The agent wants to search outside the current workspace.",
                message=f"Approval required to search outside the workspace: {raw}. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Search query is empty."
        raw = str(arguments.get("path") or ".")
        target = _resolve_path(context.root, raw)
        if not target.exists():
            return f"Path not found: {raw}"
        return await _run_command(
            [
                "rg",
                "-n",
                "--hidden",
                "--smart-case",
                "--glob",
                "!.git/**",
                "--glob",
                "!__pycache__/**",
                query,
                str(target),
            ],
            cwd=context.root,
            truncate=120,
        )


class ReadFileTool:
    name = "read_file"
    description = (
        "Use this tool to read a specific file when the answer depends on the exact source text rather than a high-level search result. "
        "Prefer it after the operator names a file explicitly or after another tool has narrowed the problem to one or two candidate files. "
        "It supports optional line ranges so you can focus on the relevant region without flooding the transcript. "
        "Do not use it for broad discovery across many files or when a ripgrep search would answer the question faster."
    )
    permission = "read"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based starting line. Defaults to 1.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to return. Defaults to 160.",
                    },
                },
                "required": ["path"],
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        raw = str(arguments.get("path", ""))
        start = int(arguments.get("start_line", 1))
        max_lines = int(arguments.get("max_lines", 160))
        return f"read {raw}:{start}-{start + max_lines - 1}"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        raw = str(arguments.get("path", ""))
        resolved = _resolve_path(context.root, raw)
        if _outside_workspace(context.root, resolved):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The agent wants to read a file outside the current workspace.",
                message=f"Approval required to read outside the workspace: {raw}. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        raw = str(arguments.get("path", "")).strip()
        if not raw:
            return "File path is required."
        path = _resolve_path(context.root, raw)
        if not path.exists():
            return f"File not found: {raw}"
        if path.is_dir():
            return f"Path is a directory, not a file: {raw}"
        start_line = max(1, int(arguments.get("start_line", 1)))
        max_lines = max(1, min(int(arguments.get("max_lines", 160)), 400))
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start_index = start_line - 1
        excerpt = content[start_index : start_index + max_lines]
        rendered = "\n".join(
            f"{start_index + offset + 1:>4} {line}" for offset, line in enumerate(excerpt)
        )
        if start_index + max_lines < len(content):
            rendered += "\n... [truncated]"
        return rendered or "[empty file]"


class ListCodeDefinitionNamesTool:
    name = "list_code_definition_names"
    description = (
        "Use this tool to build a high-level structural map of a codebase by listing top-level definitions such as classes, functions, interfaces, enums, and related constructs. "
        "Prefer it when the operator asks about architecture, entry points, modules, or where responsibilities are split, especially before opening large files. "
        "It is a lighter-weight alternative to reading entire source files and helps identify the most relevant file or symbol to inspect next. "
        "Do not use it when the task requires exact implementation details that only a full file read can provide."
    )
    permission = "read"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory or file path to inspect. Defaults to the current workspace root.",
                    }
                },
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        target = str(arguments.get("path") or ".")
        return f"list definitions in {target}"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        raw = str(arguments.get("path") or ".")
        resolved = _resolve_path(context.root, raw)
        if _outside_workspace(context.root, resolved):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The agent wants to inspect definitions outside the current workspace.",
                message=f"Approval required to inspect definitions outside the workspace: {raw}. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        raw = str(arguments.get("path") or ".")
        target = _resolve_path(context.root, raw)
        if not target.exists():
            return f"Path not found: {raw}"
        command = [
            "rg",
            "-n",
            "-e",
            r"^\s*(async\s+def|def|class|export\s+(async\s+)?function|function|interface|type|enum|const\s+\w+\s*=\s*(async\s*)?\(|fn|struct|impl|func)\b",
        ]
        if target.is_dir():
            for glob in SOURCE_GLOBS:
                command.extend(["-g", glob])
        command.append(str(target))
        output = await _run_command(command, cwd=context.root, truncate=160)
        return output


class GitStatusTool:
    name = "git_status"
    description = (
        "Use this tool to inspect the current git branch and working tree state before answering questions about repo status, diffs, or whether the workspace is clean. "
        "Prefer it when the operator asks about branch context, dirty files, pending changes, or snapshot safety. "
        "It returns a concise `git status --short --branch` view that works well in the transcript without overwhelming the operator. "
        "Do not use it for historical analysis such as commit inspection when another git command would be more appropriate."
    )
    permission = "read"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": {}},
        }

    def display(self, arguments: dict[str, Any]) -> str:
        del arguments
        return "git status --short --branch"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        del arguments, context
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        del arguments
        return await _run_command(["git", "status", "--short", "--branch"], cwd=context.root, truncate=80)


class ExecuteCommandTool:
    name = "execute_command"
    description = (
        "Use this tool to run a shell command when file reads and searches are not enough, or when the operator explicitly asks for command output. "
        "Prefer it for build status checks, test output, git inspection, or other environment-dependent information that cannot be inferred safely from files alone. "
        "Inside this product, only read-only allowlisted commands in the workspace should proceed automatically; broader or riskier commands must pause for operator approval. "
        "Do not use this tool for file editing, package installation, destructive actions, or any command that would silently cross the app's approval boundary."
    )
    permission = "exec"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to run. Prefer read-only inspection commands in conversation mode.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the command. Defaults to the current workspace root.",
                    },
                },
                "required": ["command"],
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        return str(arguments.get("command", "")).strip() or "[empty command]"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        command = str(arguments.get("command", "")).strip()
        cwd_raw = str(arguments.get("cwd") or ".")
        cwd = _resolve_path(context.root, cwd_raw)
        if _outside_workspace(context.root, cwd):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The command would run outside the current workspace.",
                message=f"Approval required to run a command outside the workspace: {cwd_raw}. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        if not _is_auto_approved_command(command):
            return ApprovalRequest(
                tool_name=self.name,
                display=self.display(arguments),
                reason="The command is not in the read-only auto-allowlist.",
                message=f"Approval required to run `{command}`. Use /approve to allow once or /reject to deny.",
                arguments=arguments,
            )
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "Command is empty."
        cwd = _resolve_path(context.root, str(arguments.get("cwd") or "."))
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"Invalid command: {exc}"
        if not argv:
            return "Command is empty."
        return await _run_command(argv, cwd=cwd, truncate=160)


class UseSkillTool:
    name = "use_skill"
    description = (
        "Use this tool to load one of the local skill packs when the task falls into a specialized domain such as PDF, DOCX, or spreadsheet work. "
        "Prefer it when the operator mentions a file type or deliverable that has dedicated instructions, helper scripts, or constraints captured in a skill. "
        "The tool returns the skill summary, nearby reference docs, and available bundled scripts so the agent can follow those instructions in later steps. "
        "Do not use it for general coding questions that are already well served by the standard repo tools."
    )
    permission = "skill"

    def __init__(self, library: SkillLibrary) -> None:
        self.library = library

    def schema(self) -> dict[str, Any]:
        available = ", ".join(self.library.available_names()) or "none"
        return {
            "name": self.name,
            "description": f"{self.description} Available skills: {available}.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": f"Skill to activate. Use one of: {available}.",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Short description of the current task so the skill summary can focus on it.",
                    },
                },
                "required": ["skill_name"],
            },
        }

    def display(self, arguments: dict[str, Any]) -> str:
        name = str(arguments.get("skill_name", ""))
        return f"use_skill {name}"

    def approval_request(self, arguments: dict[str, Any], context: ToolContext) -> ApprovalRequest | None:
        del arguments, context
        return None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> str:
        del context
        skill_name = str(arguments.get("skill_name", "")).strip()
        goal = str(arguments.get("goal", "")).strip() or None
        if skill_name == "auto":
            match = self.library.match_for_query(goal or "")
            if match is None:
                return self.library.summarize("missing-skill", goal)
            skill_name = match.name
        return self.library.summarize(skill_name, goal)


class ToolRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.skills = SkillLibrary()
        tools: list[Tool] = [
            ListFilesTool(),
            SearchFilesTool(),
            ReadFileTool(),
            ListCodeDefinitionNamesTool(),
            GitStatusTool(),
            ExecuteCommandTool(),
            UseSkillTool(self.skills),
        ]
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def tool_names(self) -> list[str]:
        return list(self._tools)

    def anthropic_tools(self, names: tuple[str, ...] | list[str] | None = None) -> list[dict[str, Any]]:
        selected = names or tuple(self._tools)
        return [self._tools[name].schema() for name in selected if name in self._tools]

    def display(self, intent: ToolIntent) -> str:
        tool = self.get(intent.name)
        if tool is None:
            return intent.name
        return tool.display(intent.arguments)

    async def execute_intent(self, intent: ToolIntent, *, approved: bool = False) -> ToolExecutionResult:
        tool = self.get(intent.name)
        if tool is None:
            return ToolExecutionResult(
                tool_name=intent.name,
                display=intent.name,
                error=f"Tool is not registered: {intent.name}",
            )
        context = ToolContext(root=self.root)
        display = tool.display(intent.arguments)
        if not approved:
            approval = tool.approval_request(intent.arguments, context)
            if approval is not None:
                return ToolExecutionResult(tool_name=tool.name, display=display, approval=approval)
        try:
            output = await tool.execute(intent.arguments, context)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            return ToolExecutionResult(tool_name=tool.name, display=display, error=str(exc))
        return ToolExecutionResult(tool_name=tool.name, display=display, output=output)


def _resolve_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _outside_workspace(root: Path, target: Path) -> bool:
    return root != target and root not in target.parents


async def _run_command(argv: list[str], *, cwd: Path, truncate: int | None = 80) -> str:
    def inner() -> str:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        output = completed.stdout.strip() or completed.stderr.strip() or "[no output]"
        if completed.returncode != 0:
            output = f"[exit {completed.returncode}]\n{output}"
        lines = output.splitlines()
        if truncate is not None and len(lines) > truncate:
            lines = lines[:truncate] + ["... [truncated]"]
        return "\n".join(lines)

    return await asyncio.to_thread(inner)


def _is_auto_approved_command(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    if any(token in stripped for token in ("&&", "||", ";", ">", "<", "$(", "`")):
        return False
    try:
        argv = shlex.split(stripped)
    except ValueError:
        return False
    if not argv:
        return False
    base = argv[0]
    if base in {"rg", "ls", "pwd", "cat", "head", "tail", "sed", "find", "stat", "wc", "tree"}:
        return True
    if base != "git" or len(argv) < 2:
        return False
    safe_subcommands = {
        "branch",
        "describe",
        "diff",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    }
    if argv[1] not in safe_subcommands:
        return False
    if argv[1] == "branch" and argv[2:] not in ([], ["--show-current"]):
        return False
    return True
