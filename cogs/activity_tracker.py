import os
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks


DATABASE_PATH = "activity.db"


class ActivityTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # =====================================================
        # Configuration
        # =====================================================

        self.staff_role_id = self.get_optional_int(
            "STAFF_ROLE_ID"
        )

        self.report_channel_id = self.get_optional_int(
            "WEEKLY_REPORT_CHANNEL_ID"
        )

        timezone_name = os.getenv(
            "WEEKLY_REPORT_TIMEZONE",
            "America/Los_Angeles"
        )

        try:
            self.timezone = ZoneInfo(timezone_name)

        except ZoneInfoNotFoundError:
            print(
                f"Unknown timezone {timezone_name!r}. "
                "Using America/Los_Angeles instead."
            )

            self.timezone = ZoneInfo(
                "America/Los_Angeles"
            )

        self.report_hour = self.get_int_setting(
            variable_name="WEEKLY_REPORT_HOUR",
            default=9,
            minimum=0,
            maximum=23
        )

        self.report_minute = self.get_int_setting(
            variable_name="WEEKLY_REPORT_MINUTE",
            default=0,
            minimum=0,
            maximum=59
        )

        # =====================================================
        # Database
        # =====================================================

        self.database = sqlite3.connect(
            DATABASE_PATH
        )

        self.database.execute(
            "PRAGMA journal_mode = WAL"
        )

        self.create_tables()

        # Starts the automatic Friday scheduler.
        self.friday_report_task.start()

    # =========================================================
    # Configuration helpers
    # =========================================================

    @staticmethod
    def get_optional_int(
        variable_name: str
    ) -> int | None:
        value = os.getenv(variable_name)

        if not value:
            return None

        try:
            return int(value)

        except ValueError:
            print(
                f"{variable_name} must contain a valid "
                f"Discord ID. Current value: {value!r}"
            )

            return None

    @staticmethod
    def get_int_setting(
        variable_name: str,
        default: int,
        minimum: int,
        maximum: int
    ) -> int:
        value = os.getenv(variable_name)

        if value is None:
            return default

        try:
            number = int(value)

        except ValueError:
            print(
                f"{variable_name} must be an integer. "
                f"Using the default value of {default}."
            )

            return default

        if not minimum <= number <= maximum:
            print(
                f"{variable_name} must be between "
                f"{minimum} and {maximum}. "
                f"Using the default value of {default}."
            )

            return default

        return number

    # =========================================================
    # Database setup
    # =========================================================

    def create_tables(self):
        cursor = self.database.cursor()

        # Stores one message total for each user per calendar day.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_activity (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (
                    guild_id,
                    user_id,
                    activity_date
                )
            )
            """
        )

        # Stores daily join and leave totals.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS member_activity (
                guild_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                joined_count INTEGER NOT NULL DEFAULT 0,
                left_count INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (
                    guild_id,
                    activity_date
                )
            )
            """
        )

        # Prevents duplicate automatic Friday reports.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS automatic_report_runs (
                guild_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,

                PRIMARY KEY (
                    guild_id,
                    report_date
                )
            )
            """
        )

        self.database.commit()

    # =========================================================
    # General helpers
    # =========================================================

    def current_local_date(self) -> date:
        return datetime.now(
            self.timezone
        ).date()

    def is_staff(
        self,
        member: discord.Member
    ) -> bool:
        if self.staff_role_id is None:
            return False

        return any(
            role.id == self.staff_role_id
            for role in member.roles
        )

    def get_report_channel(
        self,
        guild: discord.Guild
    ) -> discord.TextChannel | discord.Thread | None:
        if self.report_channel_id is None:
            return None

        channel = guild.get_channel(
            self.report_channel_id
        )

        if isinstance(
            channel,
            discord.TextChannel | discord.Thread
        ):
            return channel

        return None

    @staticmethod
    def calculate_change(
        current: int,
        previous: int
    ) -> float | None:
        """
        Returns the percentage change between two values.

        None means the previous value was zero, so a standard
        percentage cannot be calculated.
        """

        if previous == 0:
            if current == 0:
                return 0.0

            return None

        return (
            (current - previous)
            / previous
        ) * 100

    def format_change(
        self,
        current: int,
        previous: int,
        lower_is_better: bool = False
    ) -> str:
        change = self.calculate_change(
            current,
            previous
        )

        if change is None:
            return "🆕 New activity"

        if abs(change) < 0.1:
            return "➡️ No change from last week"

        improved = change > 0

        if lower_is_better:
            improved = change < 0

        icon = "📈" if improved else "📉"

        if change > 0:
            direction = "increase"
        else:
            direction = "decrease"

        return (
            f"{icon} {abs(change):.1f}% "
            f"{direction} from last week"
        )

    # =========================================================
    # Activity recording
    # =========================================================

    def record_message(
        self,
        guild_id: int,
        user_id: int,
        activity_date: date
    ):
        self.database.execute(
            """
            INSERT INTO message_activity (
                guild_id,
                user_id,
                activity_date,
                message_count
            )
            VALUES (?, ?, ?, 1)

            ON CONFLICT (
                guild_id,
                user_id,
                activity_date
            )
            DO UPDATE SET
                message_count = message_count + 1
            """,
            (
                guild_id,
                user_id,
                activity_date.isoformat()
            )
        )

        self.database.commit()

    def record_member_event(
        self,
        guild_id: int,
        activity_date: date,
        event_type: str
    ):
        if event_type not in {
            "join",
            "leave"
        }:
            raise ValueError(
                "event_type must be either "
                "'join' or 'leave'"
            )

        if event_type == "join":
            joined_amount = 1
            left_amount = 0

        else:
            joined_amount = 0
            left_amount = 1

        self.database.execute(
            """
            INSERT INTO member_activity (
                guild_id,
                activity_date,
                joined_count,
                left_count
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT (
                guild_id,
                activity_date
            )
            DO UPDATE SET
                joined_count =
                    joined_count
                    + excluded.joined_count,

                left_count =
                    left_count
                    + excluded.left_count
            """,
            (
                guild_id,
                activity_date.isoformat(),
                joined_amount,
                left_amount
            )
        )

        self.database.commit()

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):
        # Ignore direct messages.
        if message.guild is None:
            return

        # Ignore messages sent by bots.
        if message.author.bot:
            return

        self.record_message(
            guild_id=message.guild.id,
            user_id=message.author.id,
            activity_date=self.current_local_date()
        )

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        self.record_member_event(
            guild_id=member.guild.id,
            activity_date=self.current_local_date(),
            event_type="join"
        )

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member
    ):
        self.record_member_event(
            guild_id=member.guild.id,
            activity_date=self.current_local_date(),
            event_type="leave"
        )

    # =========================================================
    # Database queries
    # =========================================================

    def get_member_totals(
        self,
        guild_id: int,
        start_date: date,
        end_date: date
    ) -> tuple[int, int]:
        """
        Returns joins and leaves between two dates.

        start_date is included.
        end_date is excluded.
        """

        cursor = self.database.execute(
            """
            SELECT
                COALESCE(
                    SUM(joined_count),
                    0
                ),

                COALESCE(
                    SUM(left_count),
                    0
                )

            FROM member_activity

            WHERE guild_id = ?
              AND activity_date >= ?
              AND activity_date < ?
            """,
            (
                guild_id,
                start_date.isoformat(),
                end_date.isoformat()
            )
        )

        result = cursor.fetchone()

        return (
            int(result[0]),
            int(result[1])
        )

    def get_message_total(
        self,
        guild_id: int,
        start_date: date,
        end_date: date
    ) -> int:
        cursor = self.database.execute(
            """
            SELECT
                COALESCE(
                    SUM(message_count),
                    0
                )

            FROM message_activity

            WHERE guild_id = ?
              AND activity_date >= ?
              AND activity_date < ?
            """,
            (
                guild_id,
                start_date.isoformat(),
                end_date.isoformat()
            )
        )

        result = cursor.fetchone()

        return int(result[0])

    def get_user_message_totals(
        self,
        guild_id: int,
        start_date: date,
        end_date: date
    ) -> dict[int, int]:
        cursor = self.database.execute(
            """
            SELECT
                user_id,
                SUM(message_count) AS total_messages

            FROM message_activity

            WHERE guild_id = ?
              AND activity_date >= ?
              AND activity_date < ?

            GROUP BY user_id

            ORDER BY total_messages DESC
            """,
            (
                guild_id,
                start_date.isoformat(),
                end_date.isoformat()
            )
        )

        return {
            int(user_id): int(message_count)
            for user_id, message_count
            in cursor.fetchall()
        }

    # =========================================================
    # Community health
    # =========================================================

    def get_health_status(
        self,
        current_messages: int,
        previous_messages: int,
        current_joined: int,
        previous_joined: int,
        current_left: int,
        previous_left: int
    ) -> tuple[
        str,
        str,
        discord.Color
    ]:
        score = 0

        message_change = self.calculate_change(
            current_messages,
            previous_messages
        )

        join_change = self.calculate_change(
            current_joined,
            previous_joined
        )

        leave_change = self.calculate_change(
            current_left,
            previous_left
        )

        current_net = (
            current_joined
            - current_left
        )

        previous_net = (
            previous_joined
            - previous_left
        )

        # Increased message activity is positive.
        if message_change is None:
            if current_messages > 0:
                score += 1

        elif message_change > 5:
            score += 1

        elif message_change < -5:
            score -= 1

        # Increased joins are positive.
        if join_change is None:
            if current_joined > 0:
                score += 1

        elif join_change > 5:
            score += 1

        elif join_change < -5:
            score -= 1

        # Fewer members leaving is positive.
        if leave_change is not None:
            if leave_change < -5:
                score += 1

            elif leave_change > 5:
                score -= 1

        # Better net growth is positive.
        if current_net > previous_net:
            score += 1

        elif current_net < previous_net:
            score -= 1

        if score >= 2:
            return (
                "Growing",
                "🟢",
                discord.Color.green()
            )

        if score <= -2:
            return (
                "Slowing Down",
                "🔴",
                discord.Color.red()
            )

        return (
            "Stable",
            "🟡",
            discord.Color.gold()
        )

    # =========================================================
    # Report creation
    # =========================================================

    def build_report_embed(
        self,
        guild: discord.Guild,
        include_today: bool = False
    ) -> discord.Embed:
        """
        Automatic reports use seven completed calendar days.

        Manually generated reports include today's activity when
        include_today is set to True.
        """

        today = self.current_local_date()

        if include_today:
            # The SQL end date is exclusive.
            # Using tomorrow causes today to be included.
            current_end = today + timedelta(days=1)

        else:
            # Using today as the exclusive end date leaves out
            # today's partial activity.
            current_end = today

        current_start = (
            current_end
            - timedelta(days=7)
        )

        previous_end = current_start

        previous_start = (
            previous_end
            - timedelta(days=7)
        )

        current_joined, current_left = (
            self.get_member_totals(
                guild_id=guild.id,
                start_date=current_start,
                end_date=current_end
            )
        )

        previous_joined, previous_left = (
            self.get_member_totals(
                guild_id=guild.id,
                start_date=previous_start,
                end_date=previous_end
            )
        )

        current_messages = self.get_message_total(
            guild_id=guild.id,
            start_date=current_start,
            end_date=current_end
        )

        previous_messages = self.get_message_total(
            guild_id=guild.id,
            start_date=previous_start,
            end_date=previous_end
        )

        current_net = (
            current_joined
            - current_left
        )

        previous_net = (
            previous_joined
            - previous_left
        )

        (
            health_status,
            health_icon,
            embed_color
        ) = self.get_health_status(
            current_messages=current_messages,
            previous_messages=previous_messages,
            current_joined=current_joined,
            previous_joined=previous_joined,
            current_left=current_left,
            previous_left=previous_left
        )

        report_start_datetime = datetime.combine(
            current_start,
            datetime.min.time(),
            tzinfo=self.timezone
        )

        report_end_datetime = datetime.combine(
            current_end - timedelta(days=1),
            datetime.min.time(),
            tzinfo=self.timezone
        )

        if include_today:
            period_note = (
                "Includes activity from today so far."
            )

        else:
            period_note = (
                "Uses seven completed calendar days."
            )

        embed = discord.Embed(
            title="📊 Weekly Community Report",
            description=(
                f"**Community Health:** "
                f"{health_icon} "
                f"**{health_status}**\n\n"

                f"**Reporting period:** "
                f"{discord.utils.format_dt(
                    report_start_datetime,
                    style='D'
                )} – "
                f"{discord.utils.format_dt(
                    report_end_datetime,
                    style='D'
                )}\n"

                f"*{period_note}*"
            ),
            color=embed_color,
            timestamp=datetime.now(
                self.timezone
            )
        )

        embed.add_field(
            name="Members Joined",
            value=(
                f"**{current_joined:,}**\n"
                f"{self.format_change(
                    current_joined,
                    previous_joined
                )}"
            ),
            inline=True
        )

        embed.add_field(
            name="Members Left",
            value=(
                f"**{current_left:,}**\n"
                f"{self.format_change(
                    current_left,
                    previous_left,
                    lower_is_better=True
                )}"
            ),
            inline=True
        )

        if current_net > previous_net:
            net_icon = "📈"

        elif current_net < previous_net:
            net_icon = "📉"

        else:
            net_icon = "➡️"

        embed.add_field(
            name="Net Growth",
            value=(
                f"**{current_net:+,}**\n"
                f"{net_icon} Previous week: "
                f"{previous_net:+,}"
            ),
            inline=True
        )

        embed.add_field(
            name="Messages Sent",
            value=(
                f"**{current_messages:,}**\n"
                f"{self.format_change(
                    current_messages,
                    previous_messages
                )}"
            ),
            inline=False
        )

        current_user_totals = (
            self.get_user_message_totals(
                guild_id=guild.id,
                start_date=current_start,
                end_date=current_end
            )
        )

        previous_user_totals = (
            self.get_user_message_totals(
                guild_id=guild.id,
                start_date=previous_start,
                end_date=previous_end
            )
        )

        active_users = []

        for user_id, message_count in current_user_totals.items():
            member = guild.get_member(
                user_id
            )

            # Skip users who are no longer in the server.
            if member is None:
                continue

            # Skip members with the staff role.
            if self.is_staff(member):
                continue

            previous_count = (
                previous_user_totals.get(
                    user_id,
                    0
                )
            )

            active_users.append(
                (
                    member,
                    message_count,
                    previous_count
                )
            )

            if len(active_users) == 5:
                break

        if active_users:
            active_lines = []

            for (
                position,
                (
                    member,
                    message_count,
                    previous_count
                )
            ) in enumerate(
                active_users,
                start=1
            ):
                comparison = self.format_change(
                    message_count,
                    previous_count
                )

                active_lines.append(
                    f"**{position}.** "
                    f"{member.mention} — "
                    f"**{message_count:,}** messages\n"
                    f"└ {comparison}"
                )

            active_text = "\n".join(
                active_lines
            )

        else:
            active_text = (
                "No non-staff message activity "
                "was recorded."
            )

        embed.add_field(
            name="Most Active Members",
            value=active_text,
            inline=False
        )

        embed.add_field(
            name="Previous Week",
            value=(
                f"**Messages:** "
                f"{previous_messages:,}\n"

                f"**Joined:** "
                f"{previous_joined:,}\n"

                f"**Left:** "
                f"{previous_left:,}\n"

                f"**Net Growth:** "
                f"{previous_net:+,}"
            ),
            inline=False
        )

        embed.set_footer(
            text=(
                f"{guild.name} • "
                "Compared with the previous seven days"
            )
        )

        return embed

    # =========================================================
    # Slash command
    # =========================================================

    @app_commands.command(
        name="weeklyreport",
        description=(
            "Send the weekly community report "
            "to the report channel."
        )
    )
    @app_commands.guild_only()
    async def weekly_report(
        self,
        interaction: discord.Interaction
    ):
        if not isinstance(
            interaction.user,
            discord.Member
        ):
            await interaction.response.send_message(
                "I could not verify your "
                "server membership.",
                ephemeral=True
            )
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
            await interaction.response.send_message(
                "This command can only be used "
                "inside a server.",
                ephemeral=True
            )
            return

        report_channel = self.get_report_channel(
            interaction.guild
        )

        if report_channel is None:
            await interaction.response.send_message(
                "I could not find the configured "
                "weekly report channel. Check "
                "WEEKLY_REPORT_CHANNEL_ID.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        # Manual reports include today's messages.
        embed = self.build_report_embed(
            interaction.guild,
            include_today=True
        )

        try:
            await report_channel.send(
                embed=embed
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to send "
                "messages or embeds in the weekly "
                "report channel.",
                ephemeral=True
            )
            return

        except discord.HTTPException as error:
            print(
                "The manual weekly report "
                "could not be sent:"
            )
            print(error)

            await interaction.followup.send(
                "Something went wrong while sending "
                "the weekly community report.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"The weekly community report was "
            f"sent to {report_channel.mention}.",
            ephemeral=True
        )

    # =========================================================
    # Automatic Friday report
    # =========================================================

    def report_was_sent(
        self,
        guild_id: int,
        report_date: date
    ) -> bool:
        cursor = self.database.execute(
            """
            SELECT 1

            FROM automatic_report_runs

            WHERE guild_id = ?
              AND report_date = ?
            """,
            (
                guild_id,
                report_date.isoformat()
            )
        )

        return cursor.fetchone() is not None

    def mark_report_as_sent(
        self,
        guild_id: int,
        report_date: date
    ):
        self.database.execute(
            """
            INSERT OR IGNORE INTO automatic_report_runs (
                guild_id,
                report_date,
                sent_at
            )
            VALUES (?, ?, ?)
            """,
            (
                guild_id,
                report_date.isoformat(),
                datetime.now(
                    self.timezone
                ).isoformat()
            )
        )

        self.database.commit()

    @tasks.loop(minutes=1)
    async def friday_report_task(self):
        now = datetime.now(
            self.timezone
        )

        # Monday is 0 and Friday is 4.
        if now.weekday() != 4:
            return

        scheduled_time_has_passed = (
            now.hour > self.report_hour
            or (
                now.hour == self.report_hour
                and now.minute >= self.report_minute
            )
        )

        if not scheduled_time_has_passed:
            return

        if self.report_channel_id is None:
            return

        channel = self.bot.get_channel(
            self.report_channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel | discord.Thread
        ):
            print(
                "The weekly report channel could "
                "not be found. Check "
                "WEEKLY_REPORT_CHANNEL_ID."
            )
            return

        guild = channel.guild
        today = now.date()

        if self.report_was_sent(
            guild_id=guild.id,
            report_date=today
        ):
            return

        try:
            # Automatic reports exclude the current partial day.
            embed = self.build_report_embed(
                guild,
                include_today=False
            )

            await channel.send(
                embed=embed
            )

        except discord.Forbidden:
            print(
                "The bot does not have permission "
                "to send the automatic weekly "
                "report."
            )
            return

        except discord.HTTPException as error:
            print(
                "The automatic weekly report "
                "could not be sent:"
            )
            print(error)
            return

        self.mark_report_as_sent(
            guild_id=guild.id,
            report_date=today
        )

    @friday_report_task.before_loop
    async def before_friday_report_task(self):
        await self.bot.wait_until_ready()

    # =========================================================
    # Cleanup
    # =========================================================

    def cog_unload(self):
        self.friday_report_task.cancel()
        self.database.close()


async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        ActivityTracker(bot)
    )