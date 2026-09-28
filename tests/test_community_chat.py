import random
import sqlite3
import unittest
from datetime import date, datetime, timezone

from cogs.community_chat_utils import (
    greeter_member_id,
    is_blocked_search_topic,
    prompt_sent_on,
    random_allowed_time,
    record_prompt_send,
    requests_code_execution,
    requests_silence,
    requires_web_search,
    sentence_count,
    should_use_discord_reply,
)


class CommunityChatTests(unittest.TestCase):
    def test_greeter_message_extracts_new_member(self):
        self.assertEqual(
            greeter_member_id(
                "Hey <@123456789>! We are so glad you joined **Guild.AI**!"
            ),
            123456789,
        )
        self.assertEqual(
            greeter_member_id(
                "Hey <@!123456789>! We are so glad you joined **Guild.AI**!"
            ),
            123456789,
        )
        self.assertEqual(
            greeter_member_id(
                "Hey <@123456789>! We are so glad you joined **Guild.ai!**"
            ),
            123456789,
        )
        self.assertEqual(
            greeter_member_id(
                "Hey <@123456789>! We are so glad you joined **Guild.ai**!\n"
                "https://i.imgur.com/PCTYgeY.gif"
            ),
            123456789,
        )
        self.assertIsNone(greeter_member_id("Welcome <@123456789>"))

    def test_execution_requests_are_rejected(self):
        self.assertTrue(requests_code_execution("Please run this Python script"))
        self.assertTrue(requests_code_execution("Could you execute this shell command?"))
        self.assertFalse(requests_code_execution("Explain what this Python code does"))
        self.assertFalse(requests_code_execution("How do I run Python code locally?"))
        self.assertFalse(requests_code_execution("Could you explain how to run Python locally?"))

    def test_stop_and_hostile_messages_close_conversation(self):
        self.assertTrue(requests_silence("Shut up"))
        self.assertTrue(requests_silence("Please stop talking"))
        self.assertTrue(requests_silence("That response was useless"))
        self.assertTrue(requests_silence("Bad bot, that wasn't helpful"))
        self.assertFalse(requests_silence("How do negative numbers work?"))
        self.assertFalse(requests_silence("That test returned the wrong value"))

    def test_only_question_mark_messages_use_discord_reply(self):
        self.assertTrue(should_use_discord_reply("Can you help me?"))
        self.assertFalse(should_use_discord_reply("Can you help me"))
        self.assertFalse(should_use_discord_reply("That worked, thank you"))

    def test_explicit_or_current_questions_require_web_search(self):
        self.assertTrue(requires_web_search("Search the web for this library"))
        self.assertTrue(requires_web_search("What is the latest Guild.AI release?"))
        self.assertTrue(requires_web_search("Can you verify that claim?"))
        self.assertFalse(requires_web_search("Explain what a state machine is"))

    def test_inappropriate_and_political_search_topics_are_blocked(self):
        self.assertTrue(is_blocked_search_topic("Find NSFW content online"))
        self.assertTrue(is_blocked_search_topic("What is happening in politics?"))
        self.assertTrue(is_blocked_search_topic("Summarize the state of the world"))
        self.assertTrue(is_blocked_search_topic("Search recent election news"))
        self.assertFalse(is_blocked_search_topic("Explain agent state machines"))
        self.assertFalse(is_blocked_search_topic("Find the latest Python release"))

    def test_random_prompt_time_stays_outside_quiet_hours(self):
        rng = random.Random(42)
        for _ in range(500):
            generated = random_allowed_time(rng)
            self.assertGreaterEqual(generated.hour, 4)
            self.assertLess(generated.hour, 23)

    def test_sentence_count(self):
        self.assertEqual(sentence_count("One. Two? Three!"), 3)
        self.assertEqual(sentence_count("What are you building?"), 1)

    def test_daily_prompt_record_prevents_same_day_duplicate(self):
        database = sqlite3.connect(":memory:")
        database.execute(
            "CREATE TABLE discussion_runs ("
            "guild_id INTEGER NOT NULL, local_date TEXT NOT NULL, "
            "source TEXT NOT NULL, sent_at TEXT NOT NULL, "
            "PRIMARY KEY (guild_id, local_date))"
        )
        today = date(2026, 9, 25)
        self.assertFalse(prompt_sent_on(database, 123, today))
        record_prompt_send(
            database,
            123,
            today,
            "manual",
            datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(prompt_sent_on(database, 123, today))
        with self.assertRaises(sqlite3.IntegrityError):
            record_prompt_send(
                database,
                123,
                today,
                "scheduled",
                datetime(2026, 9, 25, 13, tzinfo=timezone.utc),
            )
        database.close()


if __name__ == "__main__":
    unittest.main()
