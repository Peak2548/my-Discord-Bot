import discord
from discord.ext import commands
import time

class GeneralCommands(commands.Cog):
    """General utility commands for the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        """Check the bot's latency (ping)."""
        start_time = time.time()
        message = await ctx.send("🏓 Pinging...")
        end_time = time.time()

        api_latency = round(self.bot.latency * 1000)
        bot_latency = round((end_time - start_time) * 1000)

        embed = discord.Embed(title="🏓 Pong!", color=discord.Color.green())
        embed.add_field(name="🌐 API Latency", value=f"`{api_latency}ms`", inline=True)
        embed.add_field(name="🤖 Bot Latency", value=f"`{bot_latency}ms`", inline=True)
        
        await message.edit(content=None, embed=embed)

    @commands.command(name="clear", aliases=["purge"])
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx: commands.Context, amount: int = 5):
        """Delete messages in the channel (requires Manage Messages permission).
        Usage: !clear <amount>"""
        # +1 to include the !clear command message itself
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"🧹 Deleted **{len(deleted) - 1}** messages!")
        # The alert message will delete itself in 3 seconds
        await msg.delete(delay=3)

    @clear.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You do not have the `Manage Messages` permission!")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Please specify the number of messages to delete as a number, e.g., `!clear 10`")

    @commands.command(name="serverinfo")
    async def serverinfo(self, ctx: commands.Context):
        """Display information about this server."""
        guild = ctx.guild
        embed = discord.Embed(title=f"📊 Server Information: {guild.name}", color=discord.Color.blue())
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        embed.add_field(name="👑 Server Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="👥 Member Count", value=f"{guild.member_count} members", inline=True)
        embed.add_field(name="💬 Text Channels", value=f"{len(guild.text_channels)} channels", inline=True)
        embed.add_field(name="🔊 Voice Channels", value=f"{len(guild.voice_channels)} channels", inline=True)
        embed.add_field(name="📅 Created On", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name="avatar")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        """Get a user's avatar (defaults to yourself if nobody is mentioned)."""
        member = member or ctx.author
        embed = discord.Embed(title=f"🖼️ {member.display_name}'s Avatar", color=discord.Color.purple())
        
        if member.avatar:
            embed.set_image(url=member.avatar.url)
        else:
            embed.description = "❌ This user does not have an avatar."
            
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCommands(bot))