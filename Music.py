import asyncio
import logging
from collections import deque
from typing import Optional

import discord
import yt_dlp
from discord.ext import commands

logger = logging.getLogger(__name__)

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
        self.current_source: Optional[discord.FFmpegOpusAudio] = None

    async def extract_audio(self, url: str, retries: int = 2) -> tuple[str, str, str]:
        loop = asyncio.get_event_loop()
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = await loop.run_in_executor(None, ydl.extract_info, url, False)
                    if 'entries' in info:
                        info = info['entries'][0]
                    audio_url = info.get('url')
                    title = info.get('title', 'Unknown') or 'Unknown'
                    webpage_url = info.get('webpage_url') or info.get('original_url') or url
                    if not audio_url:
                        raise yt_dlp.utils.ExtractorError("No audio URL returned")
                    return audio_url, title, webpage_url
            except yt_dlp.utils.YoutubeDLError as e:
                last_error = e
                logger.warning(f"yt-dlp extraction attempt {attempt}/{retries} failed: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.5)
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error in extract_audio (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    await asyncio.sleep(1.5)

        raise last_error

    async def play_next(self, ctx: commands.Context):
        if not self.queue:
            self.is_playing = False
            embed = discord.Embed(description="✅ **Queue finished!** No more songs to play.", color=discord.Color.green())
            await ctx.send(embed=embed)
            return

        if not ctx.voice_client or not ctx.voice_client.is_connected():
            self.queue.clear()
            self.is_playing = False
            return

        audio_url, title, webpage_url = self.queue.popleft()
        voice_client = ctx.voice_client

        def after_playing(error):
            if error:
                logger.error(f"Playback error: {error}")
            if ctx.voice_client and ctx.voice_client.is_connected():
                asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

        source = discord.FFmpegOpusAudio(audio_url, **self.ffmpeg_opts)
        self.current_source = source
        voice_client.play(source, after=after_playing)

        embed = discord.Embed(title="🎵 Now Playing", description=f"**[{title}]({webpage_url})**", color=discord.Color.blurple())
        if ctx.author.avatar:
            embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    async def safe_connect(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        if self._connecting:
            return None
        self._connecting = True
        try:
            existing = channel.guild.voice_client
            if existing is not None:
                try:
                    await existing.disconnect(force=True)
                except Exception:
                    pass
                await asyncio.sleep(2)

            last_error = None
            for attempt in range(1, 4):
                try:
                    # 🌟 แก้ไขตรงนี้: เพิ่ม timeout เป็น 20.0 และเปลี่ยน reconnect เป็น True
                    vc = await channel.connect(timeout=20.0, reconnect=True, self_deaf=True)
                    await asyncio.sleep(1) # เพิ่มเวลาพักให้ Handshake เสร็จสมบูรณ์
                    return vc
                except Exception as e:
                    last_error = e
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
        source = self.current_source
        self.current_source = None
        if source is None:
            return

        process = getattr(source, "_process", None)
        if process is None:
            return

        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        except Exception:
            pass

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
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
            await ctx.send(f"❌ Could not join: {str(e)}")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, url: str):
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
                await ctx.send(f"❌ Can't connect to voice channel: {str(e)}")
                return
        else:
            voice_client = ctx.voice_client
            if voice_client.channel != channel:
                try:
                    await voice_client.move_to(channel)
                    await asyncio.sleep(1)
                except Exception as e:
                    await ctx.send(f"❌ Can't move to voice channel: {str(e)}")
                    return

        loading_msg = await ctx.send("⏳ *Extracting audio metadata, please wait...*")
        self.is_loading = True

        try:
            if 'youtube.com' in url or 'youtu.be' in url:
                if 'v=' in url:
                    video_id = url.split('v=')[1].split('&')[0]
                    url = f"https://www.youtube.com/watch?v={video_id}"

            audio_url, title, webpage_url = await self.extract_audio(url)
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
                self.current_source = source
                voice_client.play(source, after=after_playing)

                embed = discord.Embed(title="🎵 Now Playing", description=f"**[{title}]({webpage_url})**", color=discord.Color.green())
                if ctx.author.avatar:
                    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
                await loading_msg.delete()
                await ctx.send(embed=embed)
            else:
                self.queue.append((audio_url, title, webpage_url))
                embed = discord.Embed(title="📝 Added to Queue", description=f"**{title}**", color=discord.Color.orange())
                embed.add_field(name="Position in Queue", value=f"`#{len(self.queue)}`", inline=True)
                if ctx.author.avatar:
                    embed.set_footer(text=f"Added by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
                await loading_msg.delete()
                await ctx.send(embed=embed)

        except Exception as e:
            await loading_msg.edit(content=f"❌ Error playing song: {str(e)}")
        finally:
            self.is_loading = False

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context):
        if not self.queue:
            embed = discord.Embed(description="📭 **Queue is currently empty!**", color=discord.Color.gold())
            await ctx.send(embed=embed)
            return

        queue_list = "\n".join(f"`{i + 1}.` {title}" for i, (_, title, _) in enumerate(self.queue))
        embed = discord.Embed(title="🎵 Current Music Queue", description=queue_list, color=discord.Color.blue())
        embed.set_footer(text=f"Total Songs: {len(self.queue)} | Requested by {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.command(name="skip", aliases=["sk"])
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Skipped current song!**")
        else:
            await ctx.send("❌ Nothing is currently playing!")

    @commands.command(name="disconn", aliases=["dc"])
    async def stop(self, ctx: commands.Context):
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
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ **Music paused.**")
        else:
            await ctx.send("❌ Nothing is playing right now!")

    @commands.command(name="resume", aliases=["r"])
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ **Music resumed.**")
        else:
            await ctx.send("❌ Music is not paused!")

    @commands.command(name="clearqueue", aliases=["cq"])
    async def clearqueue(self, ctx: commands.Context):
        self.queue.clear()
        await ctx.send("🗑️ **Queue has been successfully cleared!**")


async def setup(bot: commands.Bot):
    """Load the Music cog."""
    await bot.add_cog(Music(bot))