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
# Configure a JavaScript runtime (deno) for yt-dlp's YouTube signature/
# n-challenge solving.
# --------------------------------------------------------------------------
# เดิม: hardcode path ตายตัว 'C:\Users\Peako\.deno\bin\deno.exe' — ถ้าลง
# ใหม่/ย้ายเครื่อง/deno ไม่ได้อยู่ตรงนั้นแล้ว จะเซ็ต env ไปชี้ไฟล์ที่ไม่มีจริง
# โดยไม่มี error แจ้งเตือนใดๆ (yt-dlp แค่จะ warn เฉยๆ ตอนรันจริง)
#
# แก้ไข: เช็คไฟล์ตาม path เดิมก่อน (เผื่อคุณล็อกไว้แบบนั้นตั้งใจ) ถ้าไม่เจอ
# ค่อย fallback ไปหาใน PATH ของระบบอัตโนมัติด้วย shutil.which()
_HARDCODED_DENO_PATH = r'C:\Users\Peako\.deno\bin\deno.exe'

_deno_path = _HARDCODED_DENO_PATH if os.path.isfile(_HARDCODED_DENO_PATH) else shutil.which('deno')

if _deno_path:
    os.environ['EJS'] = _deno_path
    logger.info(f"Using deno JS runtime at: {_deno_path}")
else:
    logger.warning(
        "deno not found (checked %s and system PATH) — yt-dlp will run without "
        "a JS runtime; some YouTube formats may be missing. Install deno from "
        "https://deno.land to fix this.",
        _HARDCODED_DENO_PATH,
    )

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
    """Best-effort cleanup on shutdown. Only used as a last resort fallback —
    the Music cog kills its own ffmpeg process directly via PID, so this
    should rarely need to do anything."""
    import subprocess
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', 'ffmpeg.exe'],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


atexit.register(cleanup_on_exit)


if __name__ == "__main__":
    asyncio.run(main())