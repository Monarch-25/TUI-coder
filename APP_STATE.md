# Workflow Builder UI State

## Current Scope

- The repository now spans Phase 1 and the beginning of the tool-backed Phase 2: a Textual TUI with a real conversation transcript architecture, a live coder-style tool registry, and a Bedrock conversation adapter with tool schema support plus a safe local fallback.
- The TUI exposes a coder-style operator flow: conversation-first stream, inline reasoning/tool use/tool output, in-stream tool approvals, optional plan/log inspection, approval-gated execution, todo sidebar, VCS sidebar, and slash-command input.
- Bedrock-backed Claude conversation is now wired at the architecture level with fine-grained tool-streaming request support, but it only activates when `boto3` is available and AWS Bedrock is configured in the environment.
- The roadmap still keeps ingestion after the conversation/planner loop.

## Implemented UX

- Plain prompts now stay in conversation mode by default and can use inline repo tools before answering.
- Plan mode is explicit: `/plan <request>` stages a plan, reveals the plan panel, and pauses behind the mock approval gate.
- `/approve`, `/reject`, `/retry`, `/plan`, `/logs`, `/expand`, `/model`, `/vcs ...`, `/cost`, `/flows`, `/export`, `/clear`, `/exit`, and `/help` are wired into local state changes.
- `/thinking on`, `/thinking off`, and `/thinking budget <n>` are now available and stored in session state.
- The input bar now autocompletes slash commands from the built-in command surface.
- `/upload <file>` simulates document ingestion so the UI can show the intended operator journey before real parsers exist.
- Session export writes markdown and JSON summaries to `exports/`.
- The default screen is stream-first: `operator>`, `agent_reasoning>`, `tool>`, `tool_output>`, and `agent>` lines live in one transcript. Execution stays hidden until plan approval.
- The conversation transcript is now scrollable instead of being a fixed static panel.
- If Bedrock thinking mode is enabled and AWS is configured later, thinking deltas are meant to stream into `agent_reasoning>` while final text streams into `agent>`.
- The live conversation tool subset now includes `list_files`, `search_files`, `read_file`, `list_code_definition_names`, `git_status`, `execute_command`, and `use_skill`.
- Tool permissions now pause the turn inline when the agent wants to leave the workspace or run a non-allowlisted command. `/approve` and `/reject` resume or deny that tool request.
- The system prompt stack now uses XML-structured sections, conditional tool/skill blocks, and an explicit no-YOLO approval policy.

## Current State

- Package scaffold: `agent/` with `cli.py`, `core/`, and `tui/`.
- TUI implementation: [`agent/tui/app.py`](/Users/mozart/Documents/workflow_builder/agent/tui/app.py)
- Mock orchestrator: [`agent/core/agent.py`](/Users/mozart/Documents/workflow_builder/agent/core/agent.py)
- Conversation runtime: [`agent/core/conversation.py`](/Users/mozart/Documents/workflow_builder/agent/core/conversation.py)
- Bedrock streaming adapter: [`agent/core/bedrock.py`](/Users/mozart/Documents/workflow_builder/agent/core/bedrock.py)
- Prompt registry and renderer: [`agent/core/prompt.py`](/Users/mozart/Documents/workflow_builder/agent/core/prompt.py)
- Prompt pack: [`agent/prompts/conversation_system.md`](/Users/mozart/Documents/workflow_builder/agent/prompts/conversation_system.md)
- Tool registry: [`agent/tools/registry.py`](/Users/mozart/Documents/workflow_builder/agent/tools/registry.py)
- Skill loader: [`agent/tools/skills.py`](/Users/mozart/Documents/workflow_builder/agent/tools/skills.py)
- Session state model: [`agent/core/session.py`](/Users/mozart/Documents/workflow_builder/agent/core/session.py)
- Slash-command parsing: [`agent/tui/commands.py`](/Users/mozart/Documents/workflow_builder/agent/tui/commands.py)
- Visual styling: [`agent/tui/agent.tcss`](/Users/mozart/Documents/workflow_builder/agent/tui/agent.tcss)
- Verification status: imports pass, the Textual app boots in headless test mode, and the command/prompt/conversation/tool tests pass.

## Future Target

- Phase 2: replace the remaining mock execution/planning behavior with validated Bedrock planner/executor/tool-use loops.
- Phase 3: real document and audio ingestion with persistent storage.
- Phase 4+: tool runtime, reflection loop, Temporal workflow wrapping, VCS store, and crystallized flow replay.

## Progress Log

- Read `rules.md` and `plan.md` to align the prototype with the requested architecture.
- Chose a real Textual shell instead of a static mockup so the slash-command UX is already interactive.
- Added a local-only event bus and a mock orchestrator to preserve the planner/executor contract without paid API calls.
- Added this tracker so current scope and the next implementation targets remain explicit in the repo.
- Verified the shell after `textual` became available in the `torch` environment.
- Refined the UX so plan and logs are opt-in panels and execution only appears after approval.
- Added slash-command autocomplete to the input bar.
- Added a multi-prompt scaffold for conversation, planning, execution, summarization, and next-step suggestions.
- Started a direct conversation path for informational turns while keeping execution behind approval for actionable work.
- Refactored the stream into a typed coder transcript with inline reasoning, tool calls, tool output, and assistant replies.
- Added read-only conversation tools for workspace listing, search, file reads, and git status.
- Added `/thinking` command handling plus a Bedrock Claude streaming adapter that can request extended thinking when AWS is configured.
- Removed implicit plan routing from normal prompts so the default UX is pure conversation unless the operator explicitly enters `/plan`.
- Replaced the static conversation widget with a scrollable transcript panel so long sessions can be reviewed.
- Replaced the ad hoc conversation helpers with a real tool registry, including ripgrep-backed search, file reads, code-definition listing, git status, safe command execution, and skill loading.
- Added in-stream tool approval so parent-directory access and broader commands pause on `/approve` or `/reject` instead of getting stuck.
- Added Bedrock-facing tool schemas plus fine-grained tool-streaming payload support so Claude can be wired into the same transparent tool runtime later.
- Refined the transcript palette and status line to distinguish operator, reasoning, tool, tool output, and approval state more clearly.
- Reworked the prompt stack to use XML-tagged sections, stronger tool-selection/approval/thinking policies, and conditional skill/tool exposure inspired by the Cline task architecture.
- Expanded tool descriptions for Anthropic/Bedrock tool use so the model has clearer guidance on when to use each tool and when not to.
- Updated the Bedrock round-trip container to preserve assistant content blocks, including thinking blocks, when tool use is in play.
