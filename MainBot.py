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
        # บังคับให้ aiohttp ใช้ resolver มาตรฐานของระบบ (ThreadedResolver)
        # แทน aiodns/pycares ที่บางเครื่อง/บาง venv resolve DNS ไม่ผ่าน (ทำให้เชื่อม discord.com ไม่ได้)
        bot.http.connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

        # โหลด extension จากไฟล์ AI.py แทน BotCommands.py
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