import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from cogs.agent_builder_recovery import AgentBuilderRecovery


class AgentBuilderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        environment = {
            "AGENT_BUILDER_RECOVERY_KEY": Fernet.generate_key().decode(),
            "AGENT_BUILDER_RECOVERY_DIR": self.temp_dir.name,
        }
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.store = AgentBuilderRecovery()

    def tearDown(self):
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_recovery_is_encrypted_user_bound_and_one_time(self):
        state = {"transcript": ["Build a fictional ticket agent"]}
        code = self.store.save(123, state)
        encrypted = next(Path(self.temp_dir.name).iterdir()).read_bytes()

        self.assertNotIn(b"fictional ticket agent", encrypted)
        self.assertIsNone(self.store.load(999, code))

        code = self.store.save(123, state)
        self.assertEqual(self.store.load(123, code), state)
        self.assertIsNone(self.store.load(123, code))


if __name__ == "__main__":
    unittest.main()
