import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import logging
import sys
import shutil
import aiohttp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configure yt-dlp to use deno for JavaScript extraction (if available)
# --------------------------------------------------------------------------
# เดิม: hardcode path Windows (C:\Users\Peako\.deno\bin\deno.exe)
# ปัญหา: path นี้ไม่มีอยู่จริงบน Linux container (เช่น Render) เลยไม่มี JS runtime
# แก้ไข: หา deno แบบ dynamic ด้วย shutil.which() ถ้าไม่เจอก็ข้ามไปเฉยๆ
_deno_path = shutil.which('deno') or r'C:\Users\Peako\.deno\bin\deno.exe'
if shutil.which('deno') or os.path.isfile(_deno_path):
    os.environ['EJS'] = _deno_path
    logger.info(f"Using deno JS runtime at: {_deno_path}")
else:
    logger.warning("deno not found on this system — yt-dlp will run without a JS runtime "
                    "(some YouTube formats may be missing)")

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
        # create_no_window is a Windows-only kwarg; guard it so this doesn't
        # crash on Linux (e.g. Render) where ffmpeg.exe/taskkill don't exist anyway.
        kwargs = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], **kwargs)
        else:
            subprocess.run(['pkill', '-f', 'ffmpeg'], **kwargs)
    except Exception:
        pass


atexit.register(cleanup_on_exit)


if __name__ == "__main__":
    asyncio.run(main())