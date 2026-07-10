import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import logging
import sys
import aiohttp

# Configure yt-dlp to use deno for JavaScript extraction
os.environ['EJS'] = r'C:\Users\Peako\.deno\bin\deno.exe'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    print("[ERROR] TOKEN not found in .env file!")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info(f'{bot.user} is now running!')


async def main():
    async with bot:
        # Force aiohttp to use the system's standard resolver (ThreadedResolver)
        # instead of aiodns/pycares, which fails to resolve DNS on some
        # machines/venvs (causing "Could not contact DNS servers" and
        # preventing connection to discord.com).
        bot.http.connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

        # Load both extensions:
        #  - BotCommands.py: Music + ImageGen cogs
        #  - AI.py: the full-featured AI cog (shared channel history,
        #    !models, real web search, etc.)
        # These must NOT both define an "AI" cog / `!ai` command, or
        # discord.py will raise a CommandRegistrationError on startup.
        await bot.load_extension("BotCommands")
        await bot.load_extension("AI")
        await bot.start(TOKEN)


# Cleanup on exit
import atexit

def cleanup_on_exit():
    import subprocess
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'],
                      capture_output=True, create_no_window=True)
    except Exception:
        pass

atexit.register(cleanup_on_exit)


if __name__ == "__main__":
    asyncio.run(main())