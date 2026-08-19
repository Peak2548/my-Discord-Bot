"""
Discord bot cog: music playback (YouTube via yt-dlp -> ffmpeg -> voice).
"""

import asyncio
import io
import logging
import os
import shlex
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import discord
import yt_dlp
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==========================================================================
# Music cog
# ==========================================================================

# cookies.txt lives next to this file — exported from a browser logged into
# YouTube (see "Get cookies.txt LOCALLY" extension). Use an absolute path
# built from __file__ rather than a bare relative path, since the bot may
# be launched with a different working directory (e.g. from Start.bat).
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')

YDL_OPTS: dict = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'socket_timeout': 30,
    'cookiefile': COOKIES_FILE,
    # Force single client (mweb) — the only client that bgutil POT provider
    # is designed to match correctly per yt-dlp PO-Token-Guide (Aug 2026).
    # If yt-dlp auto-fallbacks to android_vr/web on its own (as seen in logs),
    # the POT server token won't match the actual requesting client,
    # resulting in 403 errors every time.
    'extractor_args': {
        'youtube': {
            'player_client': ['mweb'],
        },
    },
}

# discord.py's FFmpegPCMAudio only accepts before_options/options as
# plain strings (it silently drops anything else), and it tokenizes them
# with shlex.split(). So we build the string with shlex.quote() around
# any value that needs it, instead of hand-rolling quotes ourselves —
# that hand-rolling is exactly what caused the original CRLF-in-a-
# manually-quoted-string bug.
BASE_FFMPEG_BEFORE_OPTIONS = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
FFMPEG_OPTIONS = '-vn'

FFMPEG_ERROR_LOG = 'ffmpeg_error.log'
_ffmpeg_err_file: Optional[io.TextIOBase] = None

if not os.path.isfile(COOKIES_FILE):
    logger.warning(
        "cookies.txt not found at %s — YouTube playback will likely fail "
        "with 403 errors until you export one (see the 'Get cookies.txt "
        "LOCALLY' browser extension) and place it here.",
        COOKIES_FILE,
    )


def _ffmpeg_stderr_target() -> io.TextIOBase:
    """A single reused file handle for ffmpeg's stderr, so real errors land
    in ffmpeg_error.log instead of being silently discarded (which is why
    only a bare, unhelpful return code used to show up in the bot's log)."""
    global _ffmpeg_err_file
    if _ffmpeg_err_file is None or _ffmpeg_err_file.closed:
        _ffmpeg_err_file = open(FFMPEG_ERROR_LOG, 'a', encoding='utf-8', errors='replace')
    return _ffmpeg_err_file


@dataclass
class Song:
    audio_url: str
    title: str
    webpage_url: str
    requested_by: str
    requested_by_avatar: Optional[str] = None
    # The exact headers yt-dlp used to obtain audio_url (User-Agent, etc.).
    # googlevideo URLs are signed for a specific client (Android VR, web,
    # ...) and reject requests whose headers don't match that client — so
    # this must be forwarded to ffmpeg as-is rather than us guessing a UA.
    http_headers: dict = field(default_factory=dict)


@dataclass
class GuildMusicState:
    """Per-guild playback state. A bot can be in several servers at once,
    so queue/loading/connecting flags must not be shared between them."""
    queue: deque = field(default_factory=deque)
    current_source: Optional[discord.FFmpegPCMAudio] = None
    is_loading: bool = False
    connecting: bool = False


class Music(commands.Cog):
    """Music player cog with a per-guild queue."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = {}

    def state_for(self, guild_id: int) -> GuildMusicState:
        return self._states.setdefault(guild_id, GuildMusicState())

    # ---- yt-dlp ----------------------------------------------------

    async def extract_song(self, url: str, requester: discord.Member, retries: int = 2) -> Song:
        """Resolve a search term/URL into a playable Song, retrying transient
        yt-dlp/network failures once before giving up."""
        loop = asyncio.get_running_loop()
        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                if 'entries' in info:
                    info = info['entries'][0]

                audio_url = info.get('url')
                if not audio_url:
                    raise yt_dlp.utils.ExtractorError("No audio URL returned")

                return Song(
                    audio_url=audio_url,
                    title=info.get('title') or 'Unknown',
                    # webpage_url is the real youtube.com/watch?v=... link —
                    # what should be clicked, not the temporary signed audio
                    # stream URL or raw search text.
                    webpage_url=info.get('webpage_url') or info.get('original_url') or url,
                    requested_by=requester.display_name,
                    requested_by_avatar=requester.display_avatar.url if requester.avatar else None,
                    http_headers=dict(info.get('http_headers') or {}),
                )
            except yt_dlp.utils.YoutubeDLError as e:
                last_error = e
                logger.warning("yt-dlp extraction attempt %d/%d failed: %s", attempt, retries, e)
            except Exception as e:
                last_error = e
                logger.error("Unexpected error extracting audio (attempt %d/%d): %s", attempt, retries, e)

            if attempt < retries:
                await asyncio.sleep(1.5)

        raise last_error

    # ---- voice connection --------------------------------------------

    async def safe_connect(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        """Connect to a voice channel, cleaning up any stale connection first
        and retrying a few times before giving up."""
        state = self.state_for(channel.guild.id)
        if state.connecting:
            return None
        state.connecting = True
        try:
            existing = channel.guild.voice_client
            if existing is not None:
                logger.info("Cleaning up stale voice client in %s", existing.channel)
                await self._safe_disconnect(existing)
                await asyncio.sleep(2)

            last_error: Optional[Exception] = None
            for attempt in range(1, 4):
                try:
                    logger.info("Voice connect attempt %d/3...", attempt)
                    vc = await channel.connect(timeout=15.0, reconnect=False, self_deaf=True)
                    await asyncio.sleep(0.5)
                    logger.info("Connected on attempt %d", attempt)
                    return vc
                except Exception as e:
                    last_error = e
                    logger.error("Voice connect attempt %d failed: %s", attempt, e)
                    if attempt < 3:
                        await self._safe_disconnect(channel.guild.voice_client)
                        await asyncio.sleep(2 * attempt)

            raise last_error or discord.errors.ConnectionException("Failed to connect after retries")
        finally:
            state.connecting = False

    @staticmethod
    async def _safe_disconnect(vc: Optional[discord.VoiceClient]) -> None:
        if vc is None:
            return
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass

    # ---- playback --------------------------------------------------

    def _cleanup_ffmpeg(self, state: GuildMusicState) -> None:
        """Kill only the ffmpeg process this bot spawned for this guild (if
        any lingers), instead of every ffmpeg.exe on the machine."""
        source, state.current_source = state.current_source, None
        process = getattr(source, "_process", None)
        if process is None:
            return
        try:
            if process.poll() is None:  # still running
                process.kill()
                process.wait(timeout=5)
                logger.info("Killed lingering ffmpeg process (pid=%s)", process.pid)
        except Exception as e:
            logger.warning("Non-fatal error cleaning up ffmpeg process: %s", e)

    async def _start_playback(self, ctx: commands.Context, song: Song) -> None:
        """Hand a Song to the voice client and announce it."""
        state = self.state_for(ctx.guild.id)
        voice_client = ctx.voice_client

        def after_playing(error: Optional[Exception]) -> None:
            if error:
                logger.error("Playback error: %s", error)
            if ctx.voice_client and ctx.voice_client.is_connected():
                asyncio.run_coroutine_threadsafe(self._play_next(ctx), self.bot.loop)

        before_options = BASE_FFMPEG_BEFORE_OPTIONS
        if song.http_headers:
            header_block = ''.join(f'{k}: {v}\r\n' for k, v in song.http_headers.items())
            before_options += ' -headers ' + shlex.quote(header_block)

        source = discord.FFmpegPCMAudio(
            song.audio_url,
            before_options=before_options,
            options=FFMPEG_OPTIONS,
            stderr=_ffmpeg_stderr_target(),
        )
        state.current_source = source
        voice_client.play(source, after=after_playing)

        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{song.title}]({song.webpage_url})**",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Requested by {song.requested_by}", icon_url=song.requested_by_avatar)
        await ctx.send(embed=embed)

    async def _play_next(self, ctx: commands.Context) -> None:
        """Pop the next song off this guild's queue and play it, if any."""
        state = self.state_for(ctx.guild.id)

        if not ctx.voice_client or not ctx.voice_client.is_connected():
            state.queue.clear()
            return

        if not state.queue:
            embed = discord.Embed(description="✅ **Queue finished!** No more songs to play.", color=discord.Color.green())
            await ctx.send(embed=embed)
            return

        await self._start_playback(ctx, state.queue.popleft())

    # ---- commands ----------------------------------------------------

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
        """Connect the bot to your voice channel."""
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
            logger.error("Join error: %s", e)
            await ctx.send(f"❌ Could not join: {e}")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, url: str):
        """Play a song, or add it to the queue if something's already playing."""
        state = self.state_for(ctx.guild.id)

        if state.is_loading:
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
                logger.error("Connect error: %s", e)
                await ctx.send(f"❌ Can't connect to voice channel: {e}")
                return
        else:
            voice_client = ctx.voice_client
            if voice_client.channel != channel:
                try:
                    await voice_client.move_to(channel)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error("Move error: %s", e)
                    await ctx.send(f"❌ Can't move to voice channel: {e}")
                    return

        # Normalize plain YouTube watch URLs so extra query params (e.g.
        # from a shared link) don't confuse yt-dlp.
        if ('youtube.com' in url or 'youtu.be' in url) and 'v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            url = f"https://www.youtube.com/watch?v={video_id}"

        loading_msg = await ctx.send("⏳ *Extracting audio metadata, please wait...*")
        state.is_loading = True
        try:
            song = await self.extract_song(url, ctx.author)
        except Exception as e:
            logger.error("Play error: %s", e)
            await loading_msg.edit(content=f"❌ Error playing song: {e}")
            return
        finally:
            state.is_loading = False

        await loading_msg.delete()

        if voice_client.is_playing() or voice_client.is_paused():
            state.queue.append(song)
            embed = discord.Embed(title="📝 Added to Queue", description=f"**{song.title}**", color=discord.Color.orange())
            embed.add_field(name="Position in Queue", value=f"`#{len(state.queue)}`", inline=True)
            embed.set_footer(text=f"Added by {song.requested_by}", icon_url=song.requested_by_avatar)
            await ctx.send(embed=embed)
        else:
            await self._start_playback(ctx, song)

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context):
        """Show the current music queue."""
        state = self.state_for(ctx.guild.id)
        if not state.queue:
            embed = discord.Embed(description="📭 **Queue is currently empty!**", color=discord.Color.gold())
            await ctx.send(embed=embed)
            return

        queue_list = "\n".join(f"`{i + 1}.` {song.title}" for i, song in enumerate(state.queue))
        embed = discord.Embed(title="🎵 Current Music Queue", description=queue_list, color=discord.Color.blue())
        embed.set_footer(text=f"Total Songs: {len(state.queue)}")
        await ctx.send(embed=embed)

    @commands.command(name="skip", aliases=["sk"])
    async def skip(self, ctx: commands.Context):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Skipped current song!**")
        else:
            await ctx.send("❌ Nothing is currently playing!")

    @commands.command(name="disconn", aliases=["dc"])
    async def stop(self, ctx: commands.Context):
        """Stop playback, clear the queue, and disconnect."""
        state = self.state_for(ctx.guild.id)
        if not ctx.voice_client:
            await ctx.send("❌ I am not in any voice channel!")
            return

        state.queue.clear()
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            ctx.voice_client.stop()
        try:
            await asyncio.wait_for(ctx.voice_client.disconnect(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        finally:
            self._cleanup_ffmpeg(state)
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
        """Clear the music queue (does not stop the current song)."""
        self.state_for(ctx.guild.id).queue.clear()
        await ctx.send("🗑️ **Queue has been successfully cleared!**")


async def setup(bot: commands.Bot):
    """Load this cog."""
    await bot.add_cog(Music(bot))