"""
Discord bot cog: Stable Diffusion image generation.

(The Music cog used to live in this file too — it now lives in Music.py,
so this file is easier to edit without scrolling past playback code.)
"""

import asyncio
import base64
import io
import logging

import aiohttp
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==========================================================================
# ImageGen cog — Stable Diffusion (async aiohttp)
# ==========================================================================

SD_TXT2IMG_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"
SD_REQUEST_TIMEOUT_SECONDS = 180
SD_CHECKPOINT = "sd-v1-4.ckpt"


class ImageGen(commands.Cog):
    """Image generation cog using a non-blocking aiohttp call to an SD WebUI instance."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="image")
    async def generate_image(self, ctx: commands.Context, *, prompt: str):
        """Generate an image from a text prompt via the SD WebUI API."""
        status_msg = await ctx.send(f"🎨 **Generating your masterpiece...**\n> *Prompt:* `{prompt}`")

        payload = {
            "prompt": prompt,
            "width": 512,
            "height": 512,
            "steps": 25,
            "sampler_name": "Euler a",
            "batch_size": 1,
            "override_settings": {"sd_model_checkpoint": SD_CHECKPOINT},
        }

        try:
            timeout = aiohttp.ClientTimeout(total=SD_REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(SD_TXT2IMG_URL, json=payload) as resp:
                    if resp.status != 200:
                        await status_msg.edit(content=f"❌ SD API returned error status: `{resp.status}`")
                        return
                    data = await resp.json()

            image_bytes = base64.b64decode(data["images"][0])
            buffer = io.BytesIO(image_bytes)

            embed = discord.Embed(
                title="✨ Dream Generated",
                description=f"**Prompt:** {prompt}",
                color=discord.Color.purple(),
            )
            file = discord.File(fp=buffer, filename="generated_art.png")
            embed.set_image(url="attachment://generated_art.png")
            if ctx.author.avatar:
                embed.set_footer(text=f"Artisan: {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

            await status_msg.delete()
            await ctx.send(file=file, embed=embed)

        except asyncio.TimeoutError:
            await status_msg.edit(content="⚠️ Stable Diffusion took too long to respond. (Timeout)")
        except aiohttp.ClientError as e:
            logger.error("Image generation connection error: %s", e)
            await status_msg.edit(content="❌ Connection failed. Please check if your Stable Diffusion WebUI API is running.")
        except Exception:
            logger.exception("Image generation error")
            await status_msg.edit(content="❌ Something went wrong while drawing.")


async def setup(bot: commands.Bot):
    """Load this cog."""
    await bot.add_cog(ImageGen(bot))