import discord
from discord import app_commands
from discord.ext import commands


class Whois(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


# The command itself
    @app_commands.command(
        name="whois",
        description="View information about a server member."
    )

# Is a moderator and/or has the Moderate Members permission
    @app_commands.checks.has_permissions(
        moderate_members=True
    )

# Who you're looking up, and the information it provides
    @app_commands.describe(
        member="The member you want to look up."
    )
    async def whois(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None
    ):
        # If no member is selected, show the command user's profile.
        if member is None:
            member = interaction.user

        embed = discord.Embed(
            title="User Information",
            color=member.color
        )

        embed.set_author(
            name=str(member),
            icon_url=member.display_avatar.url
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="Username",
            value=member.name,
            inline=True
        )

        embed.add_field(
            name="Nickname",
            value=member.nick or "None",
            inline=True
        )

        embed.add_field(
            name="Mention",
            value=member.mention,
            inline=False
        )

        embed.add_field(
            name="Discord Account Created",
            value=(
                f"{discord.utils.format_dt(member.created_at, style='F')}\n"
                f"{discord.utils.format_dt(member.created_at, style='R')}"
            ),
            inline=False
        )

        if member.joined_at is not None:
            joined_server = (
                f"{discord.utils.format_dt(member.joined_at, style='F')}\n"
                f"{discord.utils.format_dt(member.joined_at, style='R')}"
            )
        else:
            joined_server = "Unknown"

        embed.add_field(
            name="Joined Server",
            value=joined_server,
            inline=False
        )

        roles = member.roles[1:]

        if roles:
            role_text = ", ".join(
                role.mention
                for role in reversed(roles)
            )
        else:
            role_text = "None"

        # Embed fields can contain at most 1024 characters.
        if len(role_text) > 1024:
            role_text = role_text[:1021] + "..."

        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=role_text,
            inline=False
        )

        embed.add_field(
            name="Highest Role",
            value=member.top_role.mention,
            inline=True
        )

        embed.add_field(
            name="Bot Account",
            value="Yes" if member.bot else "No",
            inline=True
        )

        embed.add_field(
            name="User ID",
            value=str(member.id),
            inline=False
        )

        if member.premium_since is not None:
            embed.add_field(
                name="Server Booster Since",
                value=(
                    f"{discord.utils.format_dt(member.premium_since, style='F')}\n"
                    f"{discord.utils.format_dt(member.premium_since, style='R')}"
                ),
                inline=False
            )

        if member.voice is not None and member.voice.channel is not None:
            embed.add_field(
                name="Voice Channel",
                value=member.voice.channel.mention,
                inline=False
            )

        embed.set_footer(
            text=f"Requested by {interaction.user}",
            icon_url=interaction.user.display_avatar.url
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Whois(bot))