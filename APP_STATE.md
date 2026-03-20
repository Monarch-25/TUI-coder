# Workflow Builder UI State

## Current Scope

- The repository currently implements Phase 1 only: a local Textual shell that previews the user experience for the agentic application.
- Bedrock calls are intentionally absent, per `rules.md`. All agent activity is mocked through a local event bus and a fake orchestrator.
- The TUI exposes the operator flow the plan describes: a conversation-first stream, optional plan/log inspection, approval-gated execution, todo sidebar, VCS sidebar, and slash-command input.

## Implemented UX

- Prompt submission stages a plan but keeps it hidden until `/plan`, then pauses behind an approval gate.
- `/approve`, `/reject`, `/retry`, `/plan`, `/logs`, `/expand`, `/model`, `/vcs ...`, `/cost`, `/flows`, `/export`, `/clear`, `/exit`, and `/help` are wired into local state changes.
- The input bar now autocompletes slash commands from the built-in command surface.
- `/upload <file>` simulates document ingestion so the UI can show the intended operator journey before real parsers exist.
- Session export writes markdown and JSON summaries to `exports/`.
- The default screen is stream-first: `operator>`, `agent_reasoning>`, and `agent>` lines only. Execution stays hidden until approval.

## Current State

- Package scaffold: `agent/` with `cli.py`, `core/`, and `tui/`.
- TUI implementation: [`agent/tui/app.py`](/Users/mozart/Documents/workflow_builder/agent/tui/app.py)
- Mock orchestrator: [`agent/core/agent.py`](/Users/mozart/Documents/workflow_builder/agent/core/agent.py)
- Session state model: [`agent/core/session.py`](/Users/mozart/Documents/workflow_builder/agent/core/session.py)
- Slash-command parsing: [`agent/tui/commands.py`](/Users/mozart/Documents/workflow_builder/agent/tui/commands.py)
- Visual styling: [`agent/tui/agent.tcss`](/Users/mozart/Documents/workflow_builder/agent/tui/agent.tcss)
- Verification status: imports pass, the Textual app boots in headless test mode, and the lightweight command-parser tests pass.

## Future Target

- Phase 2: real document and audio ingestion with persistent storage.
- Phase 3: Bedrock-backed planner and executor loop, replacing the mock event producer.
- Phase 4+: tool runtime, reflection loop, Temporal workflow wrapping, VCS store, and crystallized flow replay.

## Progress Log

- Read `rules.md` and `plan.md` to align the prototype with the requested architecture.
- Chose a real Textual shell instead of a static mockup so the slash-command UX is already interactive.
- Added a local-only event bus and a mock orchestrator to preserve the planner/executor contract without paid API calls.
- Added this tracker so current scope and the next implementation targets remain explicit in the repo.
- Verified the shell after `textual` became available in the `torch` environment.
- Refined the UX so plan and logs are opt-in panels and execution only appears after approval.
- Added slash-command autocomplete to the input bar.
