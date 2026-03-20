import asyncio
import unittest

from agent.core.bedrock import BedrockClient, BedrockConfig
from agent.core.session import initial_state
from agent.tools import ToolIntent, ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_registry_exposes_coder_conversation_tools(self) -> None:
        registry = ToolRegistry()
        names = registry.tool_names()
        self.assertIn("search_files", names)
        self.assertIn("read_file", names)
        self.assertIn("list_code_definition_names", names)
        self.assertIn("execute_command", names)
        self.assertIn("use_skill", names)

    def test_safe_command_is_auto_approved(self) -> None:
        registry = ToolRegistry()
        result = asyncio.run(
            registry.execute_intent(ToolIntent("execute_command", "inspect", {"command": "git status --short --branch"}))
        )
        self.assertFalse(result.needs_approval)
        self.assertIn("##", result.output or "")

    def test_unsafe_command_requires_approval(self) -> None:
        registry = ToolRegistry()
        result = asyncio.run(
            registry.execute_intent(ToolIntent("execute_command", "inspect", {"command": "pytest -q"}))
        )
        self.assertTrue(result.needs_approval)

    def test_use_skill_returns_skill_summary(self) -> None:
        registry = ToolRegistry()
        result = asyncio.run(
            registry.execute_intent(ToolIntent("use_skill", "inspect", {"skill_name": "pdf", "goal": "extract tables from a pdf"}))
        )
        self.assertIn("Skill: pdf", result.output or "")

    def test_anthropic_tools_can_be_filtered(self) -> None:
        registry = ToolRegistry()
        schemas = registry.anthropic_tools(["read_file", "search_files"])
        names = [schema["name"] for schema in schemas]
        self.assertEqual(names, ["read_file", "search_files"])


class BedrockPayloadTests(unittest.TestCase):
    def test_tool_payload_includes_fine_grained_streaming_header(self) -> None:
        client = BedrockClient(BedrockConfig(region="us-east-1"))
        state = initial_state()
        payload = client.build_payload(
            system_prompt="system",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            state=state,
            tools=ToolRegistry().anthropic_tools(),
        )
        self.assertIn("tools", payload)
        self.assertIn("fine-grained-tool-streaming-2025-05-14", payload["anthropic_beta"])


if __name__ == "__main__":
    unittest.main()
