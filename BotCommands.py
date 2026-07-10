"""
Discord bot cogs: music playback and Stable Diffusion image generation.
Optimized with beautiful Embeds, async HTTP clients, and clean UX.
"""

import asyncio
import base64
import io
import logging
import subprocess
from collections import deque
from typing import Optional

import aiohttp
import discord
import yt_dlp
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==========================================================================
# Music cog
# ==========================================================================

class Music(commands.Cog):
    """Music player cog for Discord with beautiful Embeds."""

    ydl_opts: dict = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'default_search': 'ytsearch',
        'source_address': '0.0.0.0',
        'socket_timeout': 30,
    }

    ffmpeg_opts: dict = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.is_loading = False
        self.queue: deque = deque()
        self.is_playing = False
        self._connecting = False

    async def extract_audio(self, url: str) -> tuple[str, str]:
        """Extract audio URL and title from the given URL."""
        loop = asyncio.get_event_loop()
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = await loop.run_in_executor(None, ydl.extract_info, url, False)
                if 'entries' in info:
                    info = info['entries'][0]
                audio_url = info.get('url')
                title = info.get('title', 'Unknown') or 'Unknown'
                return audio_url, title
        except yt_dlp.utils.YoutubeDLError as e:
            logger.error(f"yt-dlp error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in extract_audio: {e}")
            raise

    async def play_next(self, ctx: commands.Context):
        """Play the next song in the queue."""
        if not self.queue:
            self.is_playing = False
            embed = discord.Embed(description="✅ **Queue finished!** No more songs to play.", color=discord.Color.green())
            await ctx.send(embed=embed)
            return

        if not ctx.voice_client or not ctx.voice_client.is_connected():
            self.queue.clear()
            self.is_playing = False
            return

        audio_url, title = self.queue.popleft()
        voice_client = ctx.voice_client

        def after_playing(error):
            if error:
                logger.error(f"Playback error: {error}")
            if ctx.voice_client and ctx.voice_client.is_connected():
                asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

        source = discord.FFmpegOpusAudio(audio_url, **self.ffmpeg_opts)
        voice_client.play(source, after=after_playing)
        
        # UI Upgrade: ตอนเล่นเพลงถัดไปใช้ Embed สวยงาม
        embed = discord.Embed(title="🎵 Now Playing", description=f"**[{title}]({audio_url})**", color=discord.Color.blurple())
        if ctx.author.avatar:
            embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    async def safe_connect(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        """Connect to a voice channel with retry logic."""
        if self._connecting:
            return None
        self._connecting = True
        try:
            existing = channel.guild.voice_client
            if existing is not None:
                logger.info(f"Cleaning up stale voice client in {existing.channel}")
                try:
                    await existing.disconnect(force=True)
                except Exception:
                    pass
                await asyncio.sleep(2)

            last_error = None
            for attempt in range(1, 4):
                try:
                    logger.info(f"Voice connect attempt {attempt}/3...")
                    vc = await channel.connect(timeout=15.0, reconnect=False, self_deaf=True)
                    await asyncio.sleep(0.5)
                    logger.info(f"✅ Connected on attempt {attempt}")
                    return vc
                except Exception as e:
                    last_error = e
                    logger.error(f"Attempt {attempt} failed: {e}")
                    if attempt < 3:
                        bad_vc = channel.guild.voice_client
                        if bad_vc:
                            try:
                                await bad_vc.disconnect(force=True)
                            except Exception:
                                pass
                        await asyncio.sleep(2 * attempt)

            raise last_error or discord.errors.ConnectionException("Failed to connect after retries")
        finally:
            self._connecting = False

    def cleanup_ffmpeg(self) -> None:
        """Force-kill any lingering ffmpeg.exe process after stopping playback."""
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'ffmpeg.exe'], capture_output=True)
        except Exception as e:
            logger.warning(f"Non-fatal error while cleaning up ffmpeg: {e}")

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
        """Connect bot to the user's voice channel."""
        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel first!")
            return

        channel = ctx.author.voice.channel
        existing_vc = ctx.guild.voice_client
        if existing_vc and existing_vc.is_connected():
            if existing_vc.channel == channel:
                await ctx.send("✅ Already connected to your channel!")
            else:
                await existing_vc.move_to(channel)
                await ctx.send(f"✅ Moved to **{channel}**")
            return

        try:
            await self.safe_connect(channel)
            await ctx.send(f"✅ Joined **{channel}**")
        except Exception as e:
            logger.error(f"Join error: {e}")
            await ctx.send(f"❌ Could not join: {str(e)}")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, url: str):
        """Play a song from the given URL."""
        if self.is_loading:
            await ctx.send("⏳ Already loading a song, please wait...")
            return

        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel!")
            return

        channel = ctx.author.voice.channel

        if ctx.voice_client is None:
            try:
                voice_client = await self.safe_connect(channel)
                if voice_client is None:
                    await ctx.send("⏳ Already connecting, please wait a moment...")
                    return
            except Exception as e:
                logger.error(f"Connect error: {e}")
                await ctx.send(f"❌ Can't connect to voice channel: {str(e)}")
                return
        else:
            voice_client = ctx.voice_client
            if voice_client.channel != channel:
                try:
                    await voice_client.move_to(channel)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Move error: {e}")
                    await ctx.send(f"❌ Can't move to voice channel: {str(e)}")
                    return

        loading_msg = await ctx.send("⏳ *Extracting audio metadata, please wait...*")
        self.is_loading = True

        try:
            if 'youtube.com' in url or 'youtu.be' in url:
                if 'v=' in url:
                    video_id = url.split('v=')[1].split('&')[0]
                    url = f"https://www.youtube.com/watch?v={video_id}"

            audio_url, title = await self.extract_audio(url)
            if not audio_url:
                await loading_msg.edit(content="❌ Could not find audio URL")
                return

            if not voice_client.is_playing():
                def after_playing(error):
                    if error:
                        logger.error(f"Playback error: {error}")
                    if ctx.voice_client and ctx.voice_client.is_connected():
                        asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

                source = discord.FFmpegOpusAudio(audio_url, **self.ffmpeg_opts)
                voice_client.play(source, after=after_playing)
                
                # UI Upgrade: Embed สำหรับเพลงปัจจุบัน
                embed = discord.Embed(title="🎵 Now Playing", description=f"**[{title}]({url})**", color=discord.Color.green())
                if ctx.author.avatar:
                    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
                await loading_msg.delete()
                await ctx.send(embed=embed)
            else:
                self.queue.append((audio_url, title))
                
                # UI Upgrade: Embed สำหรับตอนเพิ่มเข้าคิว
                embed = discord.Embed(title="📝 Added to Queue", description=f"**{title}**", color=discord.Color.orange())
                embed.add_field(name="Position in Queue", value=f"`#{len(self.queue)}`", inline=True)
                if ctx.author.avatar:
                    embed.set_footer(text=f"Added by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
                await loading_msg.delete()
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Play error: {e}")
            await loading_msg.edit(content=f"❌ Error playing song: {str(e)}")
        finally:
            self.is_loading = False

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context):
        """Show the current music queue."""
        if not self.queue:
            embed = discord.Embed(description="📭 **Queue is currently empty!**", color=discord.Color.gold())
            await ctx.send(embed=embed)
            return

        queue_list = "\n".join(f"`{i + 1}.` {title}" for i, (_, title) in enumerate(self.queue))
        embed = discord.Embed(title="🎵 Current Music Queue", description=queue_list, color=discord.Color.blue())
        embed.set_footer(text=f"Total Songs: {len(self.queue)} | Requested by {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.command(name="skip", aliases=["sk"])
    async def skip(self, ctx: commands.Context):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Skipped current song!**")
        else:
            await ctx.send("❌ Nothing is currently playing!")

    @commands.command(name="stop", aliases=["st"])
    async def stop(self, ctx: commands.Context):
        """Stop and disconnect from voice channel."""
        if not ctx.voice_client:
            await ctx.send("❌ I am not in any voice channel!")
            return

        self.queue.clear()
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            ctx.voice_client.stop()
        try:
            await asyncio.wait_for(ctx.voice_client.disconnect(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        finally:
            self.cleanup_ffmpeg()
        await ctx.send("⏹️ **Playback stopped and queue cleared.**")

    @commands.command(name="pause", aliases=["ps"])
    async def pause(self, ctx: commands.Context):
        """Pause the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ **Music paused.**")
        else:
            await ctx.send("❌ Nothing is playing right now!")

    @commands.command(name="resume", aliases=["r"])
    async def resume(self, ctx: commands.Context):
        """Resume the paused song."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ **Music resumed.**")
        else:
            await ctx.send("❌ Music is not paused!")

    @commands.command(name="clearqueue", aliases=["cq"])
    async def clearqueue(self, ctx: commands.Context):
        """Clear the music queue."""
        self.queue.clear()
        await ctx.send("🗑️ **Queue has been successfully cleared!**")


# ==========================================================================
# ImageGen cog — Stable Diffusion (Upgraded to Pure Async aiohttp)
# ==========================================================================

SD_TXT2IMG_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"
SD_REQUEST_TIMEOUT_SECONDS = 180


class ImageGen(commands.Cog):
    """Image generation cog using non-blocking aiohttp call & beautiful Embed framing."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="image")
    async def generate_image(self, ctx: commands.Context, *, prompt: str):
        """Generate an image from a text prompt via SD WebUI."""
        status_msg = await ctx.send(f"🎨 **Generating your masterpiece...**\n> *Prompt:* `{prompt}`")
        
        payload = {
            "prompt": prompt,
            "width": 512,
            "height": 512,
            "steps": 25,
            "sampler_name": "Euler a",
            "batch_size": 1,
            "override_settings": {"sd_model_checkpoint": "sd-v1-4.ckpt"},
        }

        try:
            # 🌟 ปรับปรุง: เปลี่ยนเป็น Async aiohttp แท้ๆ ไม่บล็อกการทำงานบอทแน่นอน 
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=SD_REQUEST_TIMEOUT_SECONDS)
                async with session.post(SD_TXT2IMG_URL, json=payload, timeout=timeout) as resp:
                    if resp.status != 200:
                        await status_msg.edit(content=f"❌ SD API returned error status: `{resp.status}`")
                        return
                    
                    data = await resp.json()

            # แปลงภาพจาก base64
            image_bytes = base64.b64decode(data["images"][0])
            buffer = io.BytesIO(image_bytes)
            buffer.seek(0)
            
            # 🌟 UI Upgrade: ส่งภาพแบบกล่องพรีเมียม ฝังภาพลงใน Embed
            embed = discord.Embed(
                title="✨ Dream Generated", 
                description=f"**Prompt:** {prompt}", 
                color=discord.Color.purple()
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
            logger.error(f"Image generation connection error: {e}")
            await status_msg.edit(content="❌ Connection failed. Please check if your Stable Diffusion WebUI API is running.")
        except Exception as e:
            logger.exception("Image generation error")
            await status_msg.edit(content=f"❌ Something went wrong while drawing: `{str(e)}`")


async def setup(bot: commands.Bot):
    """Load all cogs."""
    await bot.add_cog(Music(bot))
    await bot.add_cog(ImageGen(bot))