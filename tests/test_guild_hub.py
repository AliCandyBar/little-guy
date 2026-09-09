import time
import unittest

from agents.guild_hub import GuildAgentHub


class GuildAgentHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_ranking_prefers_name_and_description_matches(self):
        hub = GuildAgentHub()
        hub._catalog_loaded_at = time.monotonic()
        hub._catalog = [
            {
                "name": "ticket-triage",
                "description": "Prioritizes customer support tickets.",
                "url": "https://app.guild.ai/hub/agents/example~ticket-triage",
                "category": "Customer Support",
                "installs": "10",
            },
            {
                "name": "release-writer",
                "description": "Writes product release notes.",
                "url": "https://app.guild.ai/hub/agents/example~release-writer",
                "category": "Development",
                "installs": "20",
            },
        ]

        matches = await hub.find_candidates(
            "Triage and prioritize our support tickets"
        )

        self.assertEqual(matches[0]["name"], "ticket-triage")
        self.assertNotIn("release-writer", [item["name"] for item in matches])


if __name__ == "__main__":
    unittest.main()
