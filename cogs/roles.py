import os

import discord
from discord import app_commands
from discord.ext import commands


# Emoji connected to each username-color role.
COLOR_ROLES = {
    "🔴": int(os.getenv("RED_ROLE_ID")),
    "🟠": int(os.getenv("ORANGE_ROLE_ID")),
    "🟡": int(os.getenv("YELLOW_ROLE_ID")),
    "🟢": int(os.getenv("GREEN_ROLE_ID")),
    "🔵": int(os.getenv("BLUE_ROLE_ID")),
    "🟣": int(os.getenv("PURPLE_ROLE_ID"))
}

VERIFY_EMOJI = "✅"
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID"))


class Roles(
    commands.GroupCog,
    group_name="roles",
    group_description="Reaction-role commands"
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # These will be filled when the panel commands are used. Once the messages have been sent, copy their ID's and save them to .env
        # Then add their ID's here to avoid having to re-run the panel commands every time the bot restarts.
        self.color_message_id = int(os.getenv("COLOR_ROLE_MESSAGE_ID")) if os.getenv("COLOR_ROLE_MESSAGE_ID") else None
        self.verify_message_id = int(os.getenv("VERIFY_MESSAGE_ID")) if os.getenv("VERIFY_MESSAGE_ID") else None

        # Debugging: print the message IDs when the bot starts up
        print(f"Color message ID: {self.color_message_id}")
        print(f"Verify message ID: {self.verify_message_id}")

    @app_commands.command(
        name="panel",
        description="Posts the username-color role panel."
    )
    async def panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Choose Your Username Color",
            description=(
                "React below to select a color.\n\n"
                "🔴 Roaring Red\n"
                "🟠 Original Orange\n"
                "🟡 Youthful Yellow\n"
                "🟢 Grinning Green\n"
                "🔵 Bold Blue\n"
                "🟣 Proud Purple"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(embed=embed)

        message = await interaction.original_response()
        self.color_message_id = message.id

        for emoji in COLOR_ROLES:
            await message.add_reaction(emoji)

    @app_commands.command(
        name="verify",
        description="Posts the server verification panel."
    )
    async def verify(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Server Verification",
            description=(
                "Please read the server rules, then react with ✅ "
                "to gain access to the rest of the server."
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed)

        message = await interaction.original_response()
        self.verify_message_id = message.id

        await message.add_reaction(VERIFY_EMOJI)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self,
        payload: discord.RawReactionActionEvent
    ):
        if payload.member is None or payload.member.bot:
            return

        emoji = str(payload.emoji)

        # Verification reaction
        if payload.message_id == self.verify_message_id:
            if emoji == VERIFY_EMOJI:
                role = payload.member.guild.get_role(VERIFIED_ROLE_ID)
                await payload.member.add_roles(role)

        # Username-color reaction; removes previous color roles and adds the new one
        if payload.message_id == self.color_message_id:
            role_id = COLOR_ROLES.get(emoji)

            if role_id:
                guild = payload.member.guild
                new_role = guild.get_role(role_id)

                color_role_ids = set(COLOR_ROLES.values())

                old_roles = [
                    role
                    for role in payload.member.roles
                    if role.id in color_role_ids and role.id != new_role.id
                ]

                if old_roles:
                    await payload.member.remove_roles(*old_roles)

                await payload.member.add_roles(new_role)

                channel = guild.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)

                for reaction in message.reactions:
                    reaction_emoji = str(reaction.emoji)

                    if reaction_emoji in COLOR_ROLES and reaction_emoji != emoji:
                        await reaction.remove(payload.member)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self,
        payload: discord.RawReactionActionEvent
    ):
        if payload.message_id != self.color_message_id:
            return

        role_id = COLOR_ROLES.get(str(payload.emoji))

        if role_id:
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            role = guild.get_role(role_id)

            await member.remove_roles(role)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))