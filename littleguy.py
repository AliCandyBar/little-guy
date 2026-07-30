# Import necessary libraries
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from cogs.tickets import TicketButton

# Load environment variables from .env file
load_dotenv()

# Get the Discord bot token from .env file
token = os.getenv("DISCORD_TOKEN")


# Define a custom class that imports various cogs and sets up the bot
class LittleGuyBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("cogs.utility")
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.roles")
        await self.load_extension("cogs.messagelogs")
        await self.load_extension("cogs.whois")
        await self.load_extension("cogs.activity_tracker")

        self.add_view(TicketButton())
        synced = await self.tree.sync()

        print(f"Synced {len(synced)} commands.")

# Set up the bot with the necessary intents and command prefix
intents = discord.Intents.default()
intents.message_content = True
intents.members =  True
intents.reactions = True

bot = LittleGuyBot(
    command_prefix="!",
    intents=intents
)

# Start-up event to indicate the bot is ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(token)