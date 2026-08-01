import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks


# Store the database inside a data folder.
DATA_FOLDER = Path("data")
DATABASE_PATH = DATA_FOLDER / "bump_reminders.db"


# Words the bot looks for in successful bump responses.
# These can be adjusted later if either bot uses different wording.
DISBOARD_SUCCESS_PHRASES = (
    "bump done",
    "bumped",
)

CARLBOT_SUCCESS_PHRASES = (
    "bump done",
    "bumped",
    "bump",
    "server bumped",
    "You've successfully bumped this server",
)


class BumpReminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.disboard_bot_id = self.get_required_id(
            "DISBOARD_BOT_ID"
        )

        self.carlbot_bot_id = self.get_required_id(
            "CARLBOT_BOT_ID"
        )

        self.reminder_role_id = self.get_required_id(
            "BUMP_REMINDER_ROLE_ID"
        )

        DATA_FOLDER.mkdir(exist_ok=True)

        self.database = sqlite3.connect(DATABASE_PATH)

        self.create_table()

        self.reminder_checker.start()

    # =========================================================
    # Setup helpers
    # =========================================================

    @staticmethod
    def get_required_id(variable_name: str) -> int:
        value = os.getenv(variable_name)

        if not value:
            raise RuntimeError(
                f"{variable_name} is missing from the environment."
            )

        return int(value)

    def create_table(self):
        self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS bump_reminders (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                reminder_time TEXT NOT NULL,

                PRIMARY KEY (
                    guild_id,
                    service
                )
            )
            """
        )

        self.database.commit()

    # =========================================================
    # Message-reading helpers
    # =========================================================

    @staticmethod
    def get_message_text(message: discord.Message) -> str:
        """
        Combines normal message text and embed text so successful
        bump responses can be detected in either format.
        """

        parts = [message.content]

        for embed in message.embeds:
            if embed.title:
                parts.append(embed.title)

            if embed.description:
                parts.append(embed.description)

            for field in embed.fields:
                parts.append(field.name)
                parts.append(field.value)

            if embed.footer and embed.footer.text:
                parts.append(embed.footer.text)

        return " ".join(
            part for part in parts if part
        ).lower()

    @staticmethod
    def contains_success_phrase(
        text: str,
        phrases: tuple[str, ...]
    ) -> bool:
        return any(
            phrase in text
            for phrase in phrases
        )

    # =========================================================
    # Reminder database methods
    # =========================================================

    def save_reminder(
        self,
        guild_id: int,
        channel_id: int,
        service: str,
        reminder_time: datetime
    ):
        """
        Adds a reminder or replaces the previous reminder for the
        same service in the same server.
        """

        self.database.execute(
            """
            INSERT INTO bump_reminders (
                guild_id,
                channel_id,
                service,
                reminder_time
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT (
                guild_id,
                service
            )
            DO UPDATE SET
                channel_id = excluded.channel_id,
                reminder_time = excluded.reminder_time
            """,
            (
                guild_id,
                channel_id,
                service,
                reminder_time.isoformat()
            )
        )

        self.database.commit()

    def get_due_reminders(
        self,
        current_time: datetime
    ) -> list[tuple[int, int, str]]:
        cursor = self.database.execute(
            """
            SELECT
                guild_id,
                channel_id,
                service

            FROM bump_reminders

            WHERE reminder_time <= ?
            """,
            (
                current_time.isoformat(),
            )
        )

        return cursor.fetchall()

    def delete_reminder(
        self,
        guild_id: int,
        service: str
    ):
        self.database.execute(
            """
            DELETE FROM bump_reminders

            WHERE guild_id = ?
              AND service = ?
            """,
            (
                guild_id,
                service
            )
        )

        self.database.commit()

    # =========================================================
    # Detect successful bumps
    # =========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):
        if message.guild is None:
            return

        message_text = self.get_message_text(message)

        # -----------------------------
        # Disboard: two-hour reminder
        # -----------------------------

        if message.author.id == self.disboard_bot_id:
            if not self.contains_success_phrase(
                message_text,
                DISBOARD_SUCCESS_PHRASES
            ):
                return

            reminder_time = (
                datetime.now(timezone.utc)
                + timedelta(hours=2)
            )

            self.save_reminder(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                service="disboard",
                reminder_time=reminder_time
            )

            confirmation_embed = discord.Embed(
                title="⏰ Disboard Reminder Set",
                description=(
                    "I'll remind you the server can be bumped again in **2 hours**."
                ),
                color=discord.Color.blurple(),
            )

            await message.channel.send(
                content=f"<@&{self.reminder_role_id}>",
                embed=confirmation_embed,
                allowed_mentions=discord.AllowedMentions(
                    roles=True,
                    users=False,
                    everyone=False
                )
            )

            print(
                "Disboard reminder scheduled for "
                f"{reminder_time.isoformat()}"
            )

            return

        # -----------------------------
        # Carl-bot: six-hour reminder
        # -----------------------------

        if message.author.id == self.carlbot_bot_id:


            # Debugging output to verify that the author ID and message content are being checked correctly
            print("Carl-bot author matched.")
            print(f"Author ID: {message.author.id}")
            print(f"Raw content: {message.content!r}")
            print(f"Parsed text: {message_text!r}")
            print(f"Expected phrases: {CARLBOT_SUCCESS_PHRASES!r}")

            if not self.contains_success_phrase(
                message_text,
                CARLBOT_SUCCESS_PHRASES
            ):
                # Debugging output to indicate that the message did not match any of the expected phrases
                print(
                    "Carl-bot text did not match.",
                    f"text={message_text!r}",
                    f"phrases={CARLBOT_SUCCESS_PHRASES!r}"
                )
                return

            print("Carl-bot success phrase matched.")

            reminder_time = (
                datetime.now(timezone.utc)
                + timedelta(hours=6)
            )

            self.save_reminder(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                service="carlbot",
                reminder_time=reminder_time
            )

            confirmation_embed = discord.Embed(
                title="⏰ Carl-bot Reminder Set",
                description=(
                    "I'll remind you the server can be bumped again in **6 hours**."
                ),
                color=discord.Color.blurple(),
            )

            await message.channel.send(
                content=f"<@&{self.reminder_role_id}>",
                embed=confirmation_embed,
                allowed_mentions=discord.AllowedMentions(
                    roles=True,
                    users=False,
                    everyone=False
                )
            )

            print(
                "Carl-bot reminder scheduled for "
                f"{reminder_time.isoformat()}"
            )

    # =========================================================
    # Reminder embeds
    # =========================================================

    def create_disboard_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🚀 Disboard Bump Is Ready!",
            description=(
                "It has been **2 hours** since the last "
                "successful Disboard bump.\n\n"
                "The server can be bumped again with `/bump`."
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(
            text="Time for another server bump!"
        )

        return embed

    def create_carlbot_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⭐ Carl-bot Bump Is Ready!",
            description=(
                "It has been **6 hours** since the last "
                "successful Carl-bot bump.\n\n"
                "The server can now be bumped again with `/bump`."
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(
            text="Time for another server bump!"
        )

        return embed

    # =========================================================
    # Check and send reminders
    # =========================================================

    @tasks.loop(minutes=1)
    async def reminder_checker(self):
        current_time = datetime.now(timezone.utc)

        due_reminders = self.get_due_reminders(
            current_time
        )

        for guild_id, channel_id, service in due_reminders:
            channel = self.bot.get_channel(channel_id)

            if not isinstance(
                channel,
                discord.TextChannel | discord.Thread
            ):
                print(
                    f"Could not find bump channel {channel_id}."
                )

                continue

            if service == "disboard":
                embed = self.create_disboard_embed()

            elif service == "carlbot":
                embed = self.create_carlbot_embed()

            else:
                self.delete_reminder(
                    guild_id,
                    service
                )

                continue

            try:
                await channel.send(
                    content=f"<@&{self.reminder_role_id}>",
                    embed=embed
                )

            except discord.HTTPException as error:
                print(
                    f"Could not send {service} reminder: "
                    f"{error}"
                )

                continue

            self.delete_reminder(
                guild_id,
                service
            )

    @reminder_checker.before_loop
    async def before_reminder_checker(self):
        await self.bot.wait_until_ready()

    # =========================================================
    # Cleanup
    # =========================================================

    def cog_unload(self):
        self.reminder_checker.cancel()
        self.database.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(BumpReminders(bot))