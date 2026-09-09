import unittest

from cogs.agent_builder_utils import (
    contains_sensitive_data,
    normalize_agent_ts,
    sanitize_project_name,
    take_discord_chunk,
)


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class AgentBuilderUtilityTests(unittest.TestCase):
    def test_discord_chunks_stay_within_utf16_limit(self):
        text = ("😀" * 700) + "\n" + ("x" * 900)
        chunks = []

        while text:
            chunk, text = take_discord_chunk(text, 1900)
            chunks.append(chunk)

        self.assertTrue(chunks)
        self.assertTrue(all(utf16_units(chunk) <= 1900 for chunk in chunks))

    def test_hard_split_preserves_code_exactly(self):
        original = " " * 10 + "x" * 2500
        first, second = take_discord_chunk(original, 1900)

        self.assertEqual(first + second, original)

    def test_sensitive_credentials_are_detected(self):
        self.assertTrue(contains_sensitive_data("API key=supersecretvalue123"))
        self.assertTrue(contains_sensitive_data("sk-" + ("a" * 30)))
        self.assertTrue(
            contains_sensitive_data(
                ("a" * 24) + "." + ("b" * 6) + "." + ("c" * 30)
            )
        )
        self.assertFalse(
            contains_sensitive_data("Connect the service using YOUR_API_KEY")
        )
        self.assertFalse(contains_sensitive_data("api_key=YOUR_API_KEY"))

    def test_project_name_is_cli_safe(self):
        self.assertEqual(
            sanitize_project_name(" Customer Update Writer! "),
            "customer-update-writer",
        )
        self.assertEqual(sanitize_project_name("!!!"), "custom-guild-agent")

    def test_agent_ts_fence_is_removed_and_required_shape_is_checked(self):
        code = (
            "```typescript\n"
            'import { llmAgent } from "@guildai/agents-sdk"\n'
            "export default llmAgent({})\n"
            "```"
        )
        self.assertFalse(normalize_agent_ts(code).startswith("```"))
        with self.assertRaises(ValueError):
            normalize_agent_ts("const value = 1")


if __name__ == "__main__":
    unittest.main()
