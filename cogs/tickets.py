# Necessary imports for the cog functionality
import io
import os

import discord
from discord import app_commands
from discord.ext import commands

# Button for opening a ticket in the ticket panel
class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="open_ticket"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = interaction.guild
        category = guild.get_channel(int(os.getenv("TICKET_CATEGORY_ID")))
        staff_role = guild.get_role(int(os.getenv("STAFF_ROLE_ID")))
        bot_member = guild.me

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
            topic=str(interaction.user.id)
        )

        await channel.send(
            f"Thank you for opening a ticket {interaction.user.mention} a {staff_role.mention} member should be with you shortly.\n"
            "Please explain what you need help with."
        )

        await interaction.response.send_message(
            f"Your ticket was created: {channel.mention}",
            ephemeral=True
        )

# /ticket commands
class Tickets(
    commands.GroupCog,
    group_name="ticket",
    group_description="Ticket commands"
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="panel",
        description="Posts the ticket panel."
    )
    async def panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Help Desk",
            description="Click the button below to open a ticket.",
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=TicketButton()
        )

    @app_commands.command(
        name="close",
        description="Closes the ticket and saves a transcript."
    )
    @app_commands.describe(summary="A short summary of what happened")
    async def close(
        self,
        interaction: discord.Interaction,
        summary: str
    ):
        channel = interaction.channel
        log_channel = interaction.guild.get_channel(
            int(os.getenv("TICKET_LOG_CHANNEL_ID"))
        )

        await interaction.response.send_message(
            "Closing ticket...",
            ephemeral=True
        )

        transcript = ""

        async for message in channel.history(
            limit=None,
            oldest_first=True
        ):
            transcript += (
                f"{message.author}: {message.clean_content}\n"
            )

        transcript_file = discord.File(
            io.BytesIO(transcript.encode()),
            filename=f"{channel.name}.txt"
        )

        embed = discord.Embed(
            title="Ticket Closed",
            description=summary,
            color=discord.Color.red()
        )

        embed.add_field(
            name="Closed by",
            value=interaction.user.mention
        )

        embed.add_field(
            name="Opened by",
            value=f"<@{channel.topic}>"
        )

        await log_channel.send(
            embed=embed,
            file=transcript_file
        )

        await channel.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))