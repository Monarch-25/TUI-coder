import unittest

from agent.tui.commands import help_text, parse_command


class CommandTests(unittest.TestCase):
    def test_parse_command_splits_name_and_args(self) -> None:
        parsed = parse_command('/vcs diff "abc1234"')
        self.assertEqual(parsed.name, "vcs")
        self.assertEqual(parsed.args, ["diff", "abc1234"])

    def test_help_text_mentions_retry_hint(self) -> None:
        text = help_text()
        self.assertIn("/approve", text)
        self.assertIn("Tip:", text)


if __name__ == "__main__":
    unittest.main()
