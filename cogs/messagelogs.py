import os

import discord
from discord.ext import commands


def trim(text: str, limit: int = 1024) -> str:
    if not text:
        return "*No text*"

    if len(text) > limit:
        return text[:limit - 3] + "..."

    return text


class MessageLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        log_channel_id = os.getenv("MESSAGE_LOG_CHANNEL_ID")
        self.log_channel_id = int(log_channel_id) if log_channel_id else None



# Message edit and delete logging

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message
    ):
        if before.author.bot:
            return

        if before.content == after.content:
            return

        if self.log_channel_id is None:
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if log_channel is None:
            return

        embed = discord.Embed(
            title="Message Edited",
            color=discord.Color.orange()
        )

        embed.set_author(
            name=str(before.author),
            icon_url=before.author.display_avatar.url
        )

        embed.add_field(
            name="Author",
            value=before.author.mention,
            inline=False
        )

        embed.add_field(
            name="Channel",
            value=before.channel.mention,
            inline=False
        )

        embed.add_field(
            name="Before",
            value=trim(before.content),
            inline=False
        )

        embed.add_field(
            name="After",
            value=trim(after.content),
            inline=False
        )

        embed.add_field(
            name="Message",
            value=f"[Jump to message]({after.jump_url})",
            inline=False
        )
        embed.set_footer(
            text=f"User ID: {before.author.id}"
        )

        await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return

        if self.log_channel_id is None:
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if log_channel is None:
            return

        embed = discord.Embed(
            title="Message Deleted",
            color=discord.Color.red()
        )

        embed.set_author(
            name=str(message.author),
            icon_url=message.author.display_avatar.url
        )

        embed.add_field(
            name="Author",
            value=message.author.mention,
            inline=False
        )

        embed.add_field(
            name="Channel",
            value=message.channel.mention,
            inline=False
        )

        embed.add_field(
            name="Content",
            value=trim(message.content),
            inline=False
        )

        embed.set_footer(
            text=f"User ID: {message.author.id}"
        )

        if message.attachments:
            attachment_names = "\n".join(
                attachment.filename
                for attachment in message.attachments
            )

            embed.add_field(
                name="Attachments",
                value=trim(attachment_names),
                inline=False
            )

        files = []

        for attachment in message.attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except discord.HTTPException:
                print(
                    f"Could not save deleted attachment: "
                    f"{attachment.filename}"
                )

        await log_channel.send(
            embed=embed,
            files=files
        )


# ----------------------------------------------------------------------------------------

# Member joins or leaves server
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if self.log_channel_id is None:
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if log_channel is None:
            return

        embed = discord.Embed(
            title="Member Joined",
            description=f"{member.mention} has joined the server.",
            color=discord.Color.green()
        )

        embed.set_author(
            name=str(member),
            icon_url=member.display_avatar.url
        )

        embed.set_footer(
            text=f"User ID: {member.id}"
        )

        await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if self.log_channel_id is None:
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if log_channel is None:
            return

        embed = discord.Embed(
            title="Member Left",
            description=f"{member.mention} has left the server.",
            color=discord.Color.red()
        )

        embed.set_author(
            name=str(member),
            icon_url=member.display_avatar.url
        )

        embed.set_footer(
            text=f"User ID: {member.id}"
        )

        await log_channel.send(embed=embed)

# ----------------------------------------------------------------------------------------

# Member changed their nickname

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member
    ):
        if before.nick == after.nick:
            return

        if self.log_channel_id is None:
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if log_channel is None:
            return

        embed = discord.Embed(
            title="Nickname Changed",
            color=discord.Color.blue()
        )

        embed.set_author(
            name=str(after),
            icon_url=after.display_avatar.url
        )

        embed.add_field(
            name="Member",
            value=after.mention,
            inline=False
        )

        embed.add_field(
            name="Before",
            value=before.nick if before.nick else "*No nickname*",
            inline=False
        )

        embed.add_field(
            name="After",
            value=after.nick if after.nick else "*No nickname*",
            inline=False
        )

        embed.set_footer(
            text=f"User ID: {after.id}"
        )

        await log_channel.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MessageLogs(bot))