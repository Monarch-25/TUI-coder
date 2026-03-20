import unittest

from agent.core.bedrock import BedrockRound, BedrockToolCall
from agent.core.prompt import PromptLibrary
from agent.core.session import initial_state


class PromptTests(unittest.TestCase):
    def test_prompt_library_renders_conversation_prompt_with_state(self) -> None:
        state = initial_state()
        prompt = PromptLibrary().render("conversation_system", state)
        self.assertIn(state.session_id, prompt)
        self.assertIn("/approve", prompt)
        self.assertIn("/thinking", prompt)
        self.assertIn("search_files", prompt)
        self.assertIn("use_skill", prompt)
        self.assertIn("<role>", prompt)
        self.assertIn("<approval_policy>", prompt)
        self.assertIn("<available_conversation_tools>", prompt)
        self.assertIn("conversation_system", prompt)

    def test_prompt_library_exposes_expected_prompt_stack(self) -> None:
        names = PromptLibrary().active_prompt_names()
        self.assertIn("planner_system", names)
        self.assertIn("executor_system", names)
        self.assertIn("next_prompt_suggestion", names)

    def test_bedrock_round_prefers_explicit_assistant_blocks(self) -> None:
        round_result = BedrockRound(
            text="ignored",
            stop_reason="tool_use",
            tool_calls=[BedrockToolCall("toolu_1", "read_file", {"path": "README.md"})],
            assistant_blocks=[
                {"type": "thinking", "thinking": "need a file read", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "README.md"}},
            ],
        )
        self.assertEqual(round_result.assistant_content()[0]["type"], "thinking")
        self.assertEqual(round_result.assistant_content()[1]["name"], "read_file")
