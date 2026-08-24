import os
import sqlite3
from pathlib import Path

# Poll history database path, change from weekly_poll for prod to weekly_poll_test for testing
DATABASE_PATH = Path(
    os.getenv(
        "WEEKLY_POLL_DATABASE",
        "data/weekly_poll_test.db"
    )
)

DATABASE_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)


class PollHistory:
    def __init__(self):
        self.database = sqlite3.connect(
            DATABASE_PATH
        )

        self.database.execute(
            "PRAGMA journal_mode = WAL"
        )

        self.create_tables()

    # =========================================================
    # Database setup
    # =========================================================

    def create_tables(self):
        self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                guild_id INTEGER NOT NULL,
                poll_number INTEGER NOT NULL,

                created_at TEXT NOT NULL,

                article_title TEXT NOT NULL,
                article_url TEXT NOT NULL,
                source_name TEXT,
                publication_date TEXT,

                poll_question TEXT NOT NULL,

                answer_1 TEXT NOT NULL,
                answer_2 TEXT NOT NULL,
                answer_3 TEXT NOT NULL,
                answer_4 TEXT NOT NULL,

                poll_message_id INTEGER,
                thread_id INTEGER,

                generation_type TEXT NOT NULL,

                UNIQUE (
                    guild_id,
                    poll_number
                )
            )
            """
        )

        self.database.commit()

    # =========================================================
    # Save poll
    # =========================================================

    def save_poll(
        self,
        guild_id: int,
        poll_number: int,
        created_at: str,
        article_title: str,
        article_url: str,
        source_name: str,
        publication_date: str,
        poll_question: str,
        answers: list[str],
        poll_message_id: int,
        thread_id: int,
        generation_type: str
    ):
        if len(answers) != 4:
            raise ValueError(
                "Weekly polls must contain exactly 4 answers."
            )

        self.database.execute(
            """
            INSERT INTO weekly_polls (
                guild_id,
                poll_number,
                created_at,

                article_title,
                article_url,
                source_name,
                publication_date,

                poll_question,

                answer_1,
                answer_2,
                answer_3,
                answer_4,

                poll_message_id,
                thread_id,

                generation_type
            )
            VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?,
                ?, ?, ?, ?,
                ?, ?,
                ?
            )
            """,
            (
                guild_id,
                poll_number,
                created_at,

                article_title,
                article_url,
                source_name,
                publication_date,

                poll_question,

                answers[0],
                answers[1],
                answers[2],
                answers[3],

                poll_message_id,
                thread_id,

                generation_type
            )
        )

        self.database.commit()

    # =========================================================
    # Recent poll history
    # =========================================================

    def get_recent_polls(
        self,
        guild_id: int,
        limit: int = 20
    ) -> list[dict]:
        cursor = self.database.execute(
            """
            SELECT
                poll_number,
                article_title,
                article_url,
                poll_question

            FROM weekly_polls

            WHERE guild_id = ?

            ORDER BY poll_number DESC

            LIMIT ?
            """,
            (
                guild_id,
                limit
            )
        )

        rows = cursor.fetchall()

        return [
            {
                "poll_number": row[0],
                "article_title": row[1],
                "article_url": row[2],
                "poll_question": row[3]
            }
            for row in rows
        ]

    # =========================================================
    # Duplicate checks
    # =========================================================

    def article_was_used(
        self,
        guild_id: int,
        article_url: str
    ) -> bool:
        cursor = self.database.execute(
            """
            SELECT 1

            FROM weekly_polls

            WHERE guild_id = ?
              AND article_url = ?

            LIMIT 1
            """,
            (
                guild_id,
                article_url
            )
        )

        return cursor.fetchone() is not None

    def headline_was_used(
        self,
        guild_id: int,
        article_title: str
    ) -> bool:
        cursor = self.database.execute(
            """
            SELECT 1

            FROM weekly_polls

            WHERE guild_id = ?
              AND LOWER(article_title) = LOWER(?)

            LIMIT 1
            """,
            (
                guild_id,
                article_title
            )
        )

        return cursor.fetchone() is not None

    # =========================================================
    # Poll numbering
    # =========================================================

    def get_next_poll_number(
        self,
        guild_id: int
    ) -> int:
        cursor = self.database.execute(
            """
            SELECT COALESCE(
                MAX(poll_number),
                0
            )

            FROM weekly_polls

            WHERE guild_id = ?
            """,
            (
                guild_id,
            )
        )

        highest_number = cursor.fetchone()[0]

        return highest_number + 1

    # =========================================================
    # Get recent records for deletion
    # =========================================================

    def get_polls_to_clear(
        self,
        guild_id: int,
        amount: int
    ) -> list[dict]:
        cursor = self.database.execute(
            """
            SELECT
                poll_number,
                poll_message_id,
                thread_id,
                article_title

            FROM weekly_polls

            WHERE guild_id = ?

            ORDER BY poll_number DESC

            LIMIT ?
            """,
            (
                guild_id,
                amount
            )
        )

        rows = cursor.fetchall()

        return [
            {
                "poll_number": row[0],
                "poll_message_id": row[1],
                "thread_id": row[2],
                "article_title": row[3]
            }
            for row in rows
        ]

    # =========================================================
    # Delete poll history
    # =========================================================

    def delete_poll_records(
        self,
        guild_id: int,
        poll_numbers: list[int]
    ):
        if not poll_numbers:
            return

        placeholders = ",".join(
            "?" for _ in poll_numbers
        )

        self.database.execute(
            f"""
            DELETE FROM weekly_polls

            WHERE guild_id = ?
              AND poll_number IN (
                  {placeholders}
              )
            """,
            (
                guild_id,
                *poll_numbers
            )
        )

        self.database.commit()

    # =========================================================
    # Cleanup
    # =========================================================

    def close(self):
        self.database.close()