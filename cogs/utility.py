# Necessary imports for the cog functionality
import discord
import os
from discord import app_commands
from discord import user
from discord.ext import commands

# Class defining the Utility cog, which includes basic commands for the bot
class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    # Debugging commands
    @app_commands.command(
        name="hello",
        description="Say hello!"
    )
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Hello!",
            ephemeral=True
    )
    @app_commands.command(
        name="ping",
        description="Shows the bot's latency."
    )
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)

        await interaction.response.send_message(
            f"🏓 Pong! `{latency} ms`",
            ephemeral=True
    )

    # Social media embed
    @app_commands.command(
        name="socials",
        description="Displays all of Guild.AI's social media links."
    )
    async def socials(self, interaction: discord.Interaction):

        embed = discord.Embed(
            title="🌐 Our Socials",
            description="Thanks for checking us out!",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🐦 X",
            value="https://x.com/GuildAI",
            inline=False
        )

        embed.add_field(
            name="💼 LinkedIn",
            value="https://www.linkedin.com/company/guild-ai-group/",
            inline=False
        )

        embed.add_field(
            name="▶️ YouTube",
            value="https://www.youtube.com/@guild-ai",
            inline=False
        )

        embed.add_field(
            name="<:guildai:1531757361864245470>"" Our Website:",
            value="https://www.guild.ai/",
            inline=False
        )

        assert self.bot.user is not None

        embed.set_footer(
            text="Have a great day!",
            icon_url=self.bot.user.display_avatar.url
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# =========================================================

# Moderation: kick and ban

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        staff_role_id = os.getenv("STAFF_ROLE_ID")

        self.staff_role_id = (
            int(staff_role_id)
            if staff_role_id
            else None
        )

        message_log_channel_id = os.getenv("MESSAGE_LOG_CHANNEL_ID")

        self.message_log_channel_id = (
            int(message_log_channel_id)
            if message_log_channel_id
            else None
        )


    # Establishes the log channel for message logs, if set in the environment variables
    def get_message_log_channel(
        self,
        guild: discord.Guild
    ) -> discord.TextChannel | None:
        if self.message_log_channel_id is None:
            return None

        channel = guild.get_channel(
            self.message_log_channel_id
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):
            return channel

        return None

    # Check if a member has the staff role based on their roles in the guild
    def is_staff(
            self,
            member: discord.Member,
    ) -> bool:
        if self.staff_role_id is None:
            return False

        return any(
            role.id == self.staff_role_id
            for role in member.roles
        )

    # Check if a moderator can moderate a target member based on their roles and hierarchy
    def can_moderate(
        self,
        moderator: discord.Member,
        target: discord.Member
    ) -> tuple[bool, str]:
        guild = moderator.guild

        if moderator.id == target.id:
            return False, "You cannot moderate yourself."

        if target.id == guild.owner_id:
            return False, "You cannot moderate the server owner."

        if (
            moderator.id != guild.owner_id
            and target.top_role >= moderator.top_role
        ):
            return (
                False,
                "You cannot moderate someone with an equal "
                "or higher role than you."
            )

        bot_member = guild.me

        if (
            bot_member is not None
            and target.top_role >= bot_member.top_role
        ):
            return (
                False,
                "My bot role must be above that member's "
                "highest role."
            )

        return True, ""

    # =========================================================
    # Kick
    # =========================================================

    @app_commands.command(
        name="kick",
        description="Remove a member from the server."
    )
    @app_commands.describe(
        member="The member to kick",
        reason="Why the member is being kicked"
    )
    @app_commands.guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        moderator = interaction.user

        if not isinstance(moderator, discord.Member):
            return

        if not self.is_staff(moderator):
            await interaction.response.send_message(
                "This command is only available to staff.",
                ephemeral=True
            )
            return
        
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used within a server.",
                ephemeral=True
            )
            return

        allowed, error_message = self.can_moderate(
            moderator,
            member
        )

        if not allowed:
            await interaction.response.send_message(
                error_message,
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        audit_reason = (
            f"{reason} | "
            f"Moderator: {moderator} ({moderator.id})"
        )

        try:
            await member.kick(
                reason=audit_reason
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to kick that member. "
                "Check my Kick Members permission and role position.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Member Kicked",
            color=discord.Color.orange()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="Member",
            value=f"{member} (`{member.id}`)",
            inline=False
        )

        embed.add_field(
            name="Moderator",
            value=moderator.mention,
            inline=False
        )

        embed.add_field(
            name="Reason",
            value=reason,
            inline=False
        )

        log_channel = self.get_message_log_channel(
            interaction.guild
        )

        if log_channel:
            await log_channel.send(
                embed=embed
            )

    # =========================================================
    # Ban
    # =========================================================

    @app_commands.command(
        name="ban",
        description="Ban a member from the server."
    )
    @app_commands.describe(
        user_id="The ID of the user to ban",
        delete_days="Delete 3 days of message history",
        reason="Why the member is being banned"
    )
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        member: discord.Member,
        delete_days: bool = False,
        reason: str = "No reason provided"
    ):
        moderator = interaction.user

        if not isinstance(moderator, discord.Member):
            return

        if not self.is_staff(moderator):
            await interaction.response.send_message(
                "This command is only available to staff.",
                ephemeral=True
            )
            return
        
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used within a server.",
                ephemeral=True
            )
            return

        allowed, error_message = self.can_moderate(
            moderator,
            member
        )

        if not allowed:
            await interaction.response.send_message(
                error_message,
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        audit_reason = (
            f"{reason} | "
            f"Moderator: {moderator} ({moderator.id})"
        )

        delete_seconds = 259200 if delete_days else 0
        user_object = discord.Object(id=member.id)
        try:
            await interaction.guild.ban(
                user_object,
                reason=audit_reason,
                delete_message_seconds=delete_seconds
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to ban that member. "
                "Check my Ban Members permission and role position.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Member Banned",
            color=discord.Color.red()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="Member",
            value=f"{member} (`{member.id}`)",
            inline=False
        )

        embed.add_field(
            name="Moderator",
            value=moderator.mention,
            inline=False
        )

        embed.add_field(
            name="Reason",
            value=reason,
            inline=False
        )
        
        log_channel = self.get_message_log_channel(
            interaction.guild
        )

        if log_channel:
            await log_channel.send(
                embed=embed
            )



# Activate upon start-up
async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
    await bot.add_cog(Moderation(bot))