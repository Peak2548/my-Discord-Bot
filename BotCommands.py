import discord
from discord.ext import commands
import yt_dlp
import asyncio
import base64
from collections import deque
import io
import requests
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Music(commands.Cog):
    """Music player cog for Discord."""

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
            await ctx.send("✅ Queue finished!")
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
        await ctx.send(f"▶️ Now playing: **{title}**")

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
                    vc = await channel.connect(timeout=15.0, reconnect=False)
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
                return
            else:
                await existing_vc.move_to(channel)
                await ctx.send(f"✅ Moved to {channel}")
                return

        try:
            await self.safe_connect(channel)
            await ctx.send(f"✅ Joined {channel}")
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

        loading_msg = await ctx.send("⏳ Loading...")
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
                await loading_msg.edit(content=f"▶️ Now playing: **{title}**")
            else:
                self.queue.append((audio_url, title))
                queue_pos = len(self.queue)
                await loading_msg.edit(content=f"📝 Added to queue: **{title}** (Position: {queue_pos})")

        except Exception as e:
            logger.error(f"Play error: {e}")
            await loading_msg.edit(content=f"❌ Error: {str(e)}")
        finally:
            self.is_loading = False

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context):
        """Show the current music queue."""
        if not self.queue:
            await ctx.send("📭 Queue is empty!")
            return

        queue_list = "\n".join([f"{i+1}. {title}" for i, (_, title) in enumerate(self.queue)])
        embed = discord.Embed(
            title="🎵 Current Queue",
            description=queue_list,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total songs: {len(self.queue)}")
        await ctx.send(embed=embed)

    @commands.command(name="skip", aliases=["sk"])
    async def skip(self, ctx: commands.Context):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skipped!")
        else:
            await ctx.send("❌ Nothing is playing!")

    @commands.command(name="stop", aliases=["s"])
    async def stop(self, ctx: commands.Context):
        """Stop and disconnect from voice channel."""
        if ctx.voice_client:
            self.queue.clear()
            ctx.voice_client.stop()
            try:
                await asyncio.wait_for(ctx.voice_client.disconnect(), timeout=10.0)
                self.cleanup_ffmpeg()
            except (asyncio.TimeoutError, Exception):
                self.cleanup_ffmpeg()
            await ctx.send("⏹️ Stopped and disconnected!")
        else:
            await ctx.send("❌ I'm not connected!")
    async def pause(self, ctx: commands.Context):
        """Pause the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Paused!")
        else:
            await ctx.send("❌ Nothing is playing!")

    @commands.command(name="resume", aliases=["r"])
    async def resume(self, ctx: commands.Context):
        """Resume the paused song."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Resumed!")
        else:
            await ctx.send("❌ Nothing is paused!")

    @commands.command(name="clearqueue", aliases=["cq"])
    async def clearqueue(self, ctx: commands.Context):
        """Clear the music queue."""
        self.queue.clear()
        await ctx.send("🗑️ Queue cleared!")


class AI(commands.Cog):
    """AI chat and code generation cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_model = "llama3.1:8b"
        self.lmstudio_api = "http://127.0.0.1:1234/v1/chat/completions"

    async def generate(self, model: str, prompt: str, num_predict: int = 1024) -> str:
        """Generate AI response using LM Studio API."""
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": num_predict,
                "stream": False
            }
            response = requests.post(self.lmstudio_api, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            
            # Handle different response formats
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            elif "content" in data:
                return data["content"]
            else:
                return str(data)
        except Exception as e:
            logger.error(f"AI generation error: {e}")
            return f"❌ Error: {str(e)}"

    async def send_long_message(self, ctx: commands.Context, message: str):
        """Send a long message in chunks to avoid Discord's message length limit."""
        chunk_size = 1900
        chunks = [message[i:i+chunk_size] for i in range(0, len(message), chunk_size)]
        for chunk in chunks:
            await ctx.send(chunk)

    @commands.command(name="Auan", aliases=["a"])
    async def auan(self, ctx: commands.Context):
        """Echo 'Auan' command."""
        await ctx.send("Auan")

    @commands.command(name="ai")
    async def ai_chat(self, ctx: commands.Context, *, message: str):
        """Chat with AI."""
        if not message:
            await ctx.send("❌ Please provide a question!")
            return
        prompt = f"{message}"
        async with ctx.typing():
            reply = await self.generate(self.chat_model, prompt, num_predict=300)
        await self.send_long_message(ctx, reply)

    @commands.command(name="code")
    async def ai_code(self, ctx: commands.Context, *, task: str):
        """Generate code with AI."""
        if not task:
            await ctx.send("❌ Please specify what code you want!")
            return
        prompt = f"{task}\nand put the code in a code block"
        async with ctx.typing():
            reply = await self.generate(self.chat_model, prompt, num_predict=500)
        await self.send_long_message(ctx, reply)


class ImageGen(commands.Cog):
    """Image generation cog using Stable Diffusion API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sd_api = "http://127.0.0.1:7860/sdapi/v1/txt2img"

    @commands.command(name="image")
    async def generate_image(self, ctx: commands.Context, *, prompt: str):
        """Generate an image from text prompt."""
        await ctx.send(f"🎨 Generating image from prompt:\n> {prompt}")
        try:
            payload = {
                "prompt": prompt,
                "width": 512,
                "height": 512,
                "steps": 25,
                "sampler_name": "Euler a",
                "batch_size": 1,
                "override_settings": {"sd_model_checkpoint": "sd-v1-4.ckpt"}
            }
            response = requests.post(self.sd_api, json=payload, timeout=180)
            response.raise_for_status()
            data = response.json()
            image_bytes = base64.b64decode(data["images"][0])
            buffer = io.BytesIO(image_bytes)
            buffer.seek(0)
            await ctx.send(file=discord.File(fp=buffer, filename="image.png"))
        except requests.exceptions.RequestException as e:
            logger.error(f"Image generation request error: {e}")
            await ctx.send(f"❌ Request failed: {str(e)}")
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            await ctx.send(f"❌ Error: {str(e)}")


async def setup(bot: commands.Bot):
    """Load all cogs."""
    await bot.add_cog(Music(bot))
    await bot.add_cog(AI(bot))
    await bot.add_cog(ImageGen(bot))