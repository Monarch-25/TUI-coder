import asyncio
import unittest

from textual.widgets import RichLog

from agent.core.agent import MockAgentOrchestrator
from agent.core.conversation import ConversationRuntime
from agent.core.session import initial_state
from agent.tui.events import EventBus
from agent.tui.panels import StreamPanel


class ConversationRuntimeTests(unittest.TestCase):
    def test_plan_actions_for_repo_question_includes_workspace_listing(self) -> None:
        runtime = ConversationRuntime()
        actions = runtime.plan_actions("Explain the codebase structure and current plan files")
        self.assertTrue(any(action.name == "workspace_files" for action in actions))

    def test_plan_actions_for_file_question_prefers_direct_read(self) -> None:
        runtime = ConversationRuntime()
        actions = runtime.plan_actions("Explain agent/tui/app.py and how /thinking works")
        self.assertTrue(any(action.name == "read_file" for action in actions))

    def test_workspace_files_tool_returns_summary(self) -> None:
        runtime = ConversationRuntime()
        output = asyncio.run(runtime._workspace_files())
        self.assertIn("Top-level counts:", output)

    def test_plain_conversation_turn_does_not_stage_a_plan(self) -> None:
        async def run() -> None:
            state = initial_state()
            orchestrator = MockAgentOrchestrator(state, EventBus())
            await orchestrator.handle_conversation_turn("heyy")
            self.assertFalse(state.pending_approval)
            self.assertEqual(state.plan_steps, [])
            self.assertIsNone(state.last_plan_query)
            self.assertEqual(state.stream_entries[-1].role, "reply")

        asyncio.run(run())

    def test_explicit_plan_turn_tracks_last_plan_query(self) -> None:
        async def run() -> None:
            state = initial_state()
            orchestrator = MockAgentOrchestrator(state, EventBus())
            await orchestrator.stage_plan("build the next panel")
            self.assertTrue(state.pending_approval)
            self.assertEqual(state.last_plan_query, "build the next panel")

        asyncio.run(run())

    def test_stream_panel_is_scrollable_rich_log(self) -> None:
        panel = StreamPanel()
        self.assertIsInstance(panel, RichLog)


if __name__ == "__main__":
    unittest.main()
