import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class RecoveryUnavailable(RuntimeError):
    pass


class AgentBuilderRecovery:
    TTL_SECONDS = 24 * 60 * 60

    def __init__(self):
        key = os.getenv("AGENT_BUILDER_RECOVERY_KEY", "").strip()
        self._fernet = Fernet(key.encode()) if key else None
        configured_dir = os.getenv(
            "AGENT_BUILDER_RECOVERY_DIR",
            ".agent_builder_recovery",
        )
        self._directory = Path(configured_dir)

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    @staticmethod
    def _filename(code: str) -> str:
        digest = hashlib.sha256(code.upper().encode()).hexdigest()
        return f"{digest}.recovery"

    def save(self, user_id: int, state: dict[str, Any]) -> str:
        if not self._fernet:
            raise RecoveryUnavailable("Recovery is not configured.")

        self.cleanup_expired()
        code = f"AB-{secrets.token_hex(6).upper()}"
        payload = {
            "user_id": user_id,
            "expires_at": int(time.time()) + self.TTL_SECONDS,
            "state": state,
        }
        encrypted = self._fernet.encrypt(
            json.dumps(payload, separators=(",", ":")).encode()
        )
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / self._filename(code)
        path.write_bytes(encrypted)
        return code

    def cleanup_expired(self):
        if not self._fernet or not self._directory.exists():
            return
        now = time.time()
        for path in self._directory.glob("*.recovery"):
            try:
                payload = json.loads(self._fernet.decrypt(path.read_bytes()))
                if payload.get("expires_at", 0) < now:
                    path.unlink(missing_ok=True)
            except (OSError, InvalidToken, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)

    def load(self, user_id: int, code: str) -> dict[str, Any] | None:
        if not self._fernet:
            raise RecoveryUnavailable("Recovery is not configured.")

        path = self._directory / self._filename(code)
        try:
            encrypted = path.read_bytes()
            payload = json.loads(self._fernet.decrypt(encrypted))
        except (FileNotFoundError, InvalidToken, ValueError, json.JSONDecodeError):
            return None

        if (
            payload.get("user_id") != user_id
            or payload.get("expires_at", 0) < time.time()
        ):
            path.unlink(missing_ok=True)
            return None

        path.unlink(missing_ok=True)
        return payload.get("state")
