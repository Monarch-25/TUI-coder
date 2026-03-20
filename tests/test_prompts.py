import unittest

from agent.core.prompt import PromptLibrary
from agent.core.session import initial_state


class PromptTests(unittest.TestCase):
    def test_prompt_library_renders_conversation_prompt_with_state(self) -> None:
        state = initial_state()
        prompt = PromptLibrary().render("conversation_system", state)
        self.assertIn(state.session_id, prompt)
        self.assertIn("/approve", prompt)
        self.assertIn("/thinking", prompt)
        self.assertIn("conversation_system", prompt)

    def test_prompt_library_exposes_expected_prompt_stack(self) -> None:
        names = PromptLibrary().active_prompt_names()
        self.assertIn("planner_system", names)
        self.assertIn("executor_system", names)
        self.assertIn("next_prompt_suggestion", names)
