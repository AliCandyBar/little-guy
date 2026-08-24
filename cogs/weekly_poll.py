import os
import re
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from crewai import Crew, Process
from crewai.crews.crew_output import CrewOutput

from typing import cast

from agents.research_agent import (
    research_agent,
    create_research_task,
    SelectedArticle
)

from agents.discussion_agent import (
    discussion_agent,
    create_discussion_task
)

from agents.poll_agent import (
    poll_agent,
    create_poll_task
)

from poll_system.poll_history import PollHistory

from poll_system.discord_poll import (
    post_weekly_poll
)


class WeeklyPoll(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # =====================================================
        # Configuration
        # =====================================================

        self.poll_channel_id = self.get_required_id(
            "WEEKLY_POLL_CHANNEL_ID"
        )

        self.staff_role_id = self.get_required_id(
            "STAFF_ROLE_ID"
        )

        timezone_name = os.getenv(
            "WEEKLY_POLL_TIMEZONE",
            "America/Los_Angeles"
        )

        self.timezone = ZoneInfo(
            timezone_name
        )

        # Monday = 0
        # Tuesday = 1
        # Wednesday = 2
        # Thursday = 3
        # Friday = 4
        # Saturday = 5
        # Sunday = 6

        self.poll_day = int(
            os.getenv(
                "WEEKLY_POLL_DAY",
                "0"
            )
        )

        self.poll_hour = int(
            os.getenv(
                "WEEKLY_POLL_HOUR",
                "9"
            )
        )

        self.poll_minute = int(
            os.getenv(
                "WEEKLY_POLL_MINUTE",
                "0"
            )
        )

        # =====================================================
        # Poll history
        # =====================================================

        self.history = PollHistory()

        # Prevent two poll workflows from running simultaneously.
        self.generation_lock = asyncio.Lock()

        self.create_internal_tables()

        # Start automatic scheduler.
        self.weekly_poll_scheduler.start()

    # =========================================================
    # Configuration helpers
    # =========================================================

    @staticmethod
    def get_required_id(
        variable_name: str
    ) -> int:
        value = os.getenv(
            variable_name
        )

        if not value:
            raise RuntimeError(
                f"{variable_name} is missing "
                "from the environment."
            )

        try:
            return int(value)

        except ValueError:
            raise RuntimeError(
                f"{variable_name} must contain "
                "a valid Discord ID."
            )

    # =========================================================
    # Internal database tables
    # =========================================================

    def create_internal_tables(self):
        """
        These tables belong specifically to the weekly poll
        coordinator.

        poll_counters:
            Keeps poll numbering permanent per Discord server.

        automatic_poll_runs:
            Prevents duplicate scheduled polls after a restart.
        """

        self.history.database.execute(
            """
            CREATE TABLE IF NOT EXISTS poll_counters (
                guild_id INTEGER PRIMARY KEY,
                last_poll_number INTEGER NOT NULL
            )
            """
        )

        self.history.database.execute(
            """
            CREATE TABLE IF NOT EXISTS automatic_poll_runs (
                guild_id INTEGER NOT NULL,
                week_key TEXT NOT NULL,
                completed_at TEXT NOT NULL,

                PRIMARY KEY (
                    guild_id,
                    week_key
                )
            )
            """
        )

        self.history.database.commit()

    # =========================================================
    # Staff check
    # =========================================================

    def is_staff(
        self,
        member: discord.Member
    ) -> bool:
        return any(
            role.id == self.staff_role_id
            for role in member.roles
        )

    # =========================================================
    # Poll channel
    # =========================================================

    def get_poll_channel(
        self,
        guild: discord.Guild
    ) -> discord.TextChannel | None:
        channel = guild.get_channel(
            self.poll_channel_id
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):
            return channel

        return None

    # =========================================================
    # Poll numbering
    # =========================================================

    def get_next_poll_number(
        self,
        guild_id: int
    ) -> int:
        cursor = self.history.database.execute(
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

    def save_poll_number(
        self,
        guild_id: int,
        poll_number: int
    ):
        self.history.database.execute(
            """
            INSERT INTO poll_counters (
                guild_id,
                last_poll_number
            )
            VALUES (?, ?)

            ON CONFLICT (guild_id)
            DO UPDATE SET
                last_poll_number =
                    excluded.last_poll_number
            """,
            (
                guild_id,
                poll_number
            )
        )

        self.history.database.commit()

    # =========================================================
    # Automatic-run tracking
    # =========================================================

    @staticmethod
    def get_week_key(
        current_time: datetime
    ) -> str:
        """
        Example:

        2026-W34
        """

        year, week, _ = (
            current_time.isocalendar()
        )

        return (
            f"{year}-W{week:02d}"
        )

    def automatic_poll_was_sent(
        self,
        guild_id: int,
        week_key: str
    ) -> bool:
        cursor = self.history.database.execute(
            """
            SELECT 1

            FROM automatic_poll_runs

            WHERE guild_id = ?
              AND week_key = ?
            """,
            (
                guild_id,
                week_key
            )
        )

        return (
            cursor.fetchone()
            is not None
        )

    def mark_automatic_poll_sent(
        self,
        guild_id: int,
        week_key: str
    ):
        self.history.database.execute(
            """
            INSERT OR IGNORE INTO automatic_poll_runs (
                guild_id,
                week_key,
                completed_at
            )
            VALUES (?, ?, ?)
            """,
            (
                guild_id,
                week_key,
                datetime.now(
                    self.timezone
                ).isoformat()
            )
        )

        self.history.database.commit()

    # =========================================================
    # CrewAI runner
    # =========================================================

    async def run_crew(
        self,
        agent,
        task
    ) -> CrewOutput:
        """
        CrewAI kickoff is synchronous.

        Run it in another thread so Little Guy's Discord event
        loop does not freeze while the AI is researching.
        """

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True
        )

        result = await asyncio.to_thread(
            crew.kickoff
        )

        assert isinstance(result, CrewOutput)

        return result

    # =========================================================
    # Agent output parsing helpers
    # =========================================================

    @staticmethod
    def normalize_agent_output(
        text: str
    ) -> str:
        """
        Removes common Markdown formatting that agents may
        include around field headings.
        """

        text = text.replace(
            "**",
            ""
        )

        text = re.sub(
            r"^#+\s*",
            "",
            text,
            flags=re.MULTILINE
        )

        return text.strip()

    @staticmethod
    def extract_section(
        text: str,
        start_label: str,
        following_labels: list[str]
    ) -> str:
        """
        Extracts text between one labeled section and the next.
        """

        escaped_following = [
            re.escape(label)
            for label in following_labels
        ]

        if escaped_following:
            end_pattern = (
                r"(?=^\s*(?:"
                + "|".join(
                    escaped_following
                )
                + r")\s*:)"
            )

        else:
            end_pattern = r"\Z"

        pattern = (
            rf"(?ims)^\s*"
            rf"{re.escape(start_label)}"
            rf"\s*:\s*"
            rf"(.*?)"
            rf"{end_pattern}"
        )

        match = re.search(
            pattern,
            text
        )

        if match is None:
            raise ValueError(
                f"Could not find '{start_label}' "
                "in the agent output."
            )

        return (
            match.group(1)
            .strip()
        )

    # =========================================================
    # Research output
    # =========================================================

    def parse_research_output(
        self,
        raw_output: str
    ) -> dict:
        text = self.normalize_agent_output(
            raw_output
        )

        headline = self.extract_section(
            text,
            "Headline",
            [
                "Source",
                "URL",
                "Publication Date",
                "Summary",
                "Relevance to Guild.AI"
            ]
        )

        source = self.extract_section(
            text,
            "Source",
            [
                "URL",
                "Publication Date",
                "Summary",
                "Relevance to Guild.AI"
            ]
        )

        url = self.extract_section(
            text,
            "URL",
            [
                "Publication Date",
                "Summary",
                "Relevance to Guild.AI"
            ]
        )

        publication_date = (
            self.extract_section(
                text,
                "Publication Date",
                [
                    "Summary",
                    "Relevance to Guild.AI"
                ]
            )
        )

        summary = self.extract_section(
            text,
            "Summary",
            [
                "Relevance to Guild.AI"
            ]
        )

        relevance = self.extract_section(
            text,
            "Relevance to Guild.AI",
            []
        )

        return {
            "headline": headline,
            "source": source,
            "url": url,
            "publication_date": publication_date,
            "summary": summary,
            "relevance": relevance
        }

    # =========================================================
    # Discussion output
    # =========================================================

    def parse_discussion_output(
        self,
        raw_output: str
    ) -> dict:
        text = self.normalize_agent_output(
            raw_output
        )

        summary = self.extract_section(
            text,
            "Summary",
            [
                "Discussion Prompt"
            ]
        )

        prompt = self.extract_section(
            text,
            "Discussion Prompt",
            []
        )

        return {
            "summary": summary,
            "prompt": prompt
        }

    # =========================================================
    # Poll output
    # =========================================================

    def parse_poll_output(
        self,
        raw_output: str
    ) -> dict:
        text = self.normalize_agent_output(
            raw_output
        )

        question = self.extract_section(
            text,
            "Question",
            [
                "Answers"
            ]
        )

        answers_section = self.extract_section(
            text,
            "Answers",
            []
        )

        answers = re.findall(
            r"(?m)^\s*[1-4][.)]\s*(.+?)\s*$",
            answers_section
        )

        if len(answers) != 4:
            raise ValueError(
                "Poll Agent did not return exactly "
                "four recognizable answers."
            )

        return {
            "question": question,
            "answers": answers
        }

    # =========================================================
    # Complete workflow
    # =========================================================

    async def generate_weekly_poll(
        self,
        guild: discord.Guild,
        generation_type: str
    ) -> int:
        """
        Runs the entire poll workflow.

        generation_type should be:
            automatic
            manual
        """

        async with self.generation_lock:

            print(
                "WEEKLY POLL: Workflow started",
                flush=True
            )

            poll_channel = self.get_poll_channel(
                guild
            )

            if poll_channel is None:
                raise RuntimeError(
                    "The configured weekly poll "
                    "channel could not be found."
                )

            # -------------------------------------------------
            # History
            # -------------------------------------------------

            print(
                "WEEKLY POLL: Loading poll history",
                flush=True
            )

            recent_history = (
                self.history.get_recent_polls(
                    guild_id=guild.id,
                    limit=30
                )
            )

            # -------------------------------------------------
            # Research Agent
            # -------------------------------------------------

            print(
                "WEEKLY POLL: Starting research",
                flush=True
            )

            research_task = (
                create_research_task(
                    recent_history
                )
            )

            research_result = await self.run_crew(
                research_agent,
                research_task
            )


            article = cast(
                SelectedArticle,
                research_result.pydantic
            )

            if research_result.pydantic is None:
                raise RuntimeError(
                    "Research Agent returned invalid article data."
                )
            
            # article = research_result.pydantic

            # if article is None:
            #     print(
            #         "WEEKLY POLL: Research Agent did not "
            #         "return structured article data.",
            #         flush=True
            #     )

            print(
                research_result.raw,
                flush=True
            )
            #     if not isinstance(
            #         article,
            #         SelectedArticle):
            #         raise RuntimeError(
            #             "Research Agent returned invalid article data."
            #     )

            print(
                "WEEKLY POLL: Selected article:",
                article.headline,
                flush=True
            )

            # -------------------------------------------------
            # Hard duplicate check
            # -------------------------------------------------

            if self.history.article_was_used(
                guild.id,
                article.url
            ):
                raise RuntimeError(
                    "The Research Agent selected an "
                    "article that has already been used."
                )

            if self.history.headline_was_used(
                guild.id,
                article.headline
            ):
                raise RuntimeError(
                    "The Research Agent selected a "
                    "headline that has already been used."
                )

            # -------------------------------------------------
            # Discussion Agent
            # -------------------------------------------------

            print(
                "WEEKLY POLL: Creating discussion",
                flush=True
            )

            discussion_task = (
                create_discussion_task(
                    article_title=article.headline,
                    article_url=article.url,
                    source_name=article.source,
                    publication_date=article.publication_date,
                    article_summary=article.summary,
                    relevance_to_guild=article.relevance_to_guild
                )
            )

            discussion_result = await self.run_crew(
                discussion_agent,
                discussion_task
            )
            discussion_raw = discussion_result.raw

            try:
                discussion = (
                    self.parse_discussion_output(
                        discussion_raw
                    )
                )

            except Exception:
                print(
                    "WEEKLY POLL: Discussion output "
                    "could not be parsed:",
                    flush=True
                )

                print(
                    discussion_raw,
                    flush=True
                )

                raise

            print(
                "WEEKLY POLL: Discussion generated",
                flush=True
            )

            # -------------------------------------------------
            # Poll Agent
            # -------------------------------------------------

            print(
                "WEEKLY POLL: Creating poll",
                flush=True
            )

            poll_task = create_poll_task(
                article_title=article.headline,
                article_summary=article.summary,
                relevance_to_guild=article.relevance_to_guild,
                discussion_prompt=discussion[
                    "prompt"
                ]
            )

            poll_result = await self.run_crew(
                poll_agent,
                poll_task
            )
            poll_raw = poll_result.raw

            try:
                poll_data = (
                    self.parse_poll_output(
                        poll_raw
                    )
                )

            except Exception:
                print(
                    "WEEKLY POLL: Poll output "
                    "could not be parsed:",
                    flush=True
                )

                print(
                    poll_raw,
                    flush=True
                )

                raise

            print(
                "WEEKLY POLL: Poll generated",
                flush=True
            )

            # -------------------------------------------------
            # Poll number
            # -------------------------------------------------

            poll_number = (
                self.get_next_poll_number(
                    guild.id
                )
            )

            print(
                f"WEEKLY POLL: Preparing "
                f"poll #{poll_number}",
                flush=True
            )

            # -------------------------------------------------
            # Discord
            # -------------------------------------------------

            poll_message, thread = (
                await post_weekly_poll(
                    poll_channel=poll_channel,
                    poll_number=poll_number,
                    poll_question=poll_data[
                        "question"
                    ],
                    answers=poll_data[
                        "answers"
                    ],
                    article_url=article.url,
                    discussion_summary=discussion[
                        "summary"
                    ],
                    discussion_prompt=discussion[
                        "prompt"
                    ]
                )
            )

            # -------------------------------------------------
            # Save history
            # -------------------------------------------------

            self.history.save_poll(
                guild_id=guild.id,
                poll_number=poll_number,
                created_at=datetime.now(
                    self.timezone
                ).isoformat(),

                article_title=article.headline,

                article_url=article.url,

                source_name=article.source,

                publication_date=article.publication_date,

                poll_question=poll_data[
                    "question"
                ],

                answers=poll_data[
                    "answers"
                ],

                poll_message_id=poll_message.id,
                thread_id=thread.id,

                generation_type=generation_type
            )

            self.save_poll_number(
                guild_id=guild.id,
                poll_number=poll_number
            )

            print(
                f"WEEKLY POLL: Poll #{poll_number} "
                "saved to database",
                flush=True
            )

            print(
                "WEEKLY POLL: Workflow complete",
                flush=True
            )

            return poll_number

    # =========================================================
    # Clear polls
    # =========================================================

    async def clear_recent_polls(
        self,
        guild: discord.Guild,
        amount: int
    ) -> int:
        """
        Removes the most recent polls for this guild from
        Discord and removes their memory/history records.

        The poll number count is reset upon clearing all polls, or the count starts with the next number.
        (ie. if there are #1 and #2 polls, the next would be #3).
        """

        poll_channel = self.get_poll_channel(
            guild
        )

        if poll_channel is None:
            raise RuntimeError(
                "The weekly poll channel "
                "could not be found."
            )

        records = (
            self.history.get_polls_to_clear(
                guild_id=guild.id,
                amount=amount
            )
        )
        remaining_polls = self.history.get_recent_polls(
            guild_id=guild.id,
            limit=1
        )

        if remaining_polls:
            new_last_number = remaining_polls[0][
                "poll_number"
            ]
        else:
            new_last_number = 0

        self.history.database.execute(
            """
            INSERT INTO poll_counters (
                guild_id,
                last_poll_number
            )
            VALUES (?, ?)

            ON CONFLICT (guild_id)
            DO UPDATE SET
                last_poll_number =
                    excluded.last_poll_number
            """,
            (
                guild.id,
                new_last_number
            )
        )

        self.history.database.commit()

        if not records:
            return 0

        deleted_poll_numbers = []

        for record in records:
            poll_number = record[
                "poll_number"
            ]

            thread_id = record[
                "thread_id"
            ]

            message_id = record[
                "poll_message_id"
            ]

            try:
                # ---------------------------------------------
                # Delete discussion thread
                # ---------------------------------------------

                if thread_id:
                    thread = guild.get_thread(
                        thread_id
                    )

                    if thread is None:
                        try:
                            thread = (
                                await guild.fetch_channel(
                                    thread_id
                                )
                            )

                        except discord.NotFound:
                            thread = None

                    if isinstance(
                        thread,
                        discord.Thread
                    ):
                        await thread.delete(
                            reason=(
                                "Weekly poll history "
                                "cleared by staff"
                            )
                        )

                # ---------------------------------------------
                # Delete poll message
                # ---------------------------------------------

                if message_id:
                    try:
                        poll_message = (
                            await poll_channel.fetch_message(
                                message_id
                            )
                        )

                        await poll_message.delete()

                    except discord.NotFound:
                        pass

                deleted_poll_numbers.append(
                    poll_number
                )

            except discord.Forbidden:
                print(
                    f"WEEKLY POLL: Missing permission "
                    f"while clearing poll #{poll_number}",
                    flush=True
                )

            except discord.HTTPException as error:
                print(
                    f"WEEKLY POLL: Discord error while "
                    f"clearing poll #{poll_number}: "
                    f"{error}",
                    flush=True
                )

        # -----------------------------------------------------
        # Remove successfully cleared polls from AI memory
        # -----------------------------------------------------

        self.history.delete_poll_records(
            guild_id=guild.id,
            poll_numbers=deleted_poll_numbers
        )

        return len(
            deleted_poll_numbers
        )

    # =========================================================
    # /weeklypoll
    # =========================================================

    @app_commands.command(
        name="weeklypoll",
        description=(
            "Generate a weekly poll or clear "
            "recent poll history."
        )
    )
    @app_commands.describe(
        clear=(
            "Optional: number of recent polls "
            "to remove from this server."
        )
    )
    @app_commands.guild_only()
    async def weeklypoll(
        self,
        interaction: discord.Interaction,
        clear: int | None = None
    ):
        if not isinstance(
            interaction.user,
            discord.Member
        ):
            return

        if not self.is_staff(
            interaction.user
        ):
            await interaction.response.send_message(
                "This command is only available "
                "to staff members.",
                ephemeral=True
            )
            return

        if interaction.guild is None:
            return

        # -----------------------------------------------------
        # Clear mode
        # -----------------------------------------------------

        if clear is not None:
            if clear < 1:
                await interaction.response.send_message(
                    "The number of polls to clear "
                    "must be at least 1.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(
                ephemeral=True
            )

            try:
                deleted = await self.clear_recent_polls(
                    guild=interaction.guild,
                    amount=clear
                )

            except Exception as error:
                print(
                    "WEEKLY POLL CLEAR ERROR:",
                    repr(error),
                    flush=True
                )

                await interaction.followup.send(
                    "Something went wrong while "
                    "clearing weekly polls. "
                    "Check the Coolify logs.",
                    ephemeral=True
                )
                return

            await interaction.followup.send(
                f"Cleared **{deleted}** weekly "
                f"poll{'s' if deleted != 1 else ''} "
                "from this server and removed "
                "their history.",
                ephemeral=True
            )

            return

        # -----------------------------------------------------
        # Generate mode
        # -----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            poll_number = (
                await self.generate_weekly_poll(
                    guild=interaction.guild,
                    generation_type="manual"
                )
            )

        except Exception as error:
            print(
                "WEEKLY POLL ERROR:",
                type(error).__name__,
                repr(error),
                flush=True
            )

            await interaction.followup.send(
                "The weekly poll workflow failed. "
                "Check the Coolify logs to see "
                "which stage failed.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Weekly poll **#{poll_number}** "
            "was created successfully.",
            ephemeral=True
        )

    # =========================================================
    # Automatic scheduler
    # =========================================================

    @tasks.loop(minutes=1)
    async def weekly_poll_scheduler(self):
        now = datetime.now(
            self.timezone
        )

        if now.weekday() != self.poll_day:
            return

        scheduled_time_has_passed = (
            now.hour > self.poll_hour
            or (
                now.hour
                == self.poll_hour
                and now.minute
                >= self.poll_minute
            )
        )

        if not scheduled_time_has_passed:
            return

        channel = self.bot.get_channel(
            self.poll_channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return

        guild = channel.guild

        week_key = self.get_week_key(
            now
        )

        if self.automatic_poll_was_sent(
            guild_id=guild.id,
            week_key=week_key
        ):
            return

        if self.generation_lock.locked():
            return

        print(
            "WEEKLY POLL: Starting "
            "automatic weekly run",
            flush=True
        )

        try:
            poll_number = (
                await self.generate_weekly_poll(
                    guild=guild,
                    generation_type="automatic"
                )
            )

        except Exception as error:
            print(
                "WEEKLY POLL AUTOMATIC ERROR:",
                type(error).__name__,
                repr(error),
                flush=True
            )

            return

        self.mark_automatic_poll_sent(
            guild_id=guild.id,
            week_key=week_key
        )

        print(
            f"WEEKLY POLL: Automatic "
            f"poll #{poll_number} completed",
            flush=True
        )

    @weekly_poll_scheduler.before_loop
    async def before_weekly_poll_scheduler(
        self
    ):
        await self.bot.wait_until_ready()

    # =========================================================
    # Cleanup
    # =========================================================

    def cog_unload(self):
        self.weekly_poll_scheduler.cancel()
        self.history.close()


async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        WeeklyPoll(bot)
    )