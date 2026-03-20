import asyncio
import unittest

from agent.core.conversation import ConversationRuntime


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


if __name__ == "__main__":
    unittest.main()
