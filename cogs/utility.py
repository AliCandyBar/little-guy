# Necessary imports for the cog functionality
import discord
from discord import app_commands
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

        embed.set_footer(text="Have a great day!""<:little_guy:1531757449969668147>")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# Activate upon start-up
async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))