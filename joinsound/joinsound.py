from redbot.core import commands, Config
import discord
import os
import asyncio

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"autojoin_role": None}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """
        Set your join sound:
        - Upload an mp3 file as an attachment without an argument.
        - Or provide an mp3 URL as an argument.
        """
        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)

        if url:
            if not url.endswith(".mp3"):
                await ctx.send("❌ The link must end with `.mp3`.")
                return
            await self.config.user(ctx.author).mp3_url.set(url)
            await ctx.send(f"✅ Your join MP3 URL has been set: {url}")
            return

        if not ctx.message.attachments:
            await ctx.send("📎 Upload a `.mp3` file or provide a URL.")
            return

        att = ctx.message.attachments[0]
        if not att.filename.endswith(".mp3"):
            await ctx.send("❌ Only `.mp3` files are allowed.")
            return

        file_path = os.path.join(folder, f"{ctx.author.id}.mp3")
        await att.save(file_path)
        await self.config.user(ctx.author).mp3_url.set(None)
        await ctx.send("✅ Your local join MP3 has been saved!")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def setjoinsoundrole(self, ctx, role: discord.Role):
        """Set a role that will trigger the bot to auto-join when a member with that role joins a voice channel."""
        await self.config.guild(ctx.guild).autojoin_role.set(role.id)
        await ctx.send(f"✅ The role `{role.name}` has been set as the trigger for auto join.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel or member.bot or after.channel is None:
            return

        guild_config = await self.config.guild(member.guild).autojoin_role()
        role_triggered = any(r.id == guild_config for r in member.roles) if guild_config else False

        local_path = f"data/joinsound/mp3s/{member.id}.mp3"
        url = await self.config.user(member).mp3_url()
        audio_available = os.path.isfile(local_path) or url

        if not audio_available and not role_triggered:
            return

        source = local_path if os.path.isfile(local_path) else url

        try:
            vc = await after.channel.connect()
            if audio_available:
                vc.play(discord.FFmpegPCMAudio(source))
                while vc.is_playing():
                    await asyncio.sleep(1)
            await asyncio.sleep(1.5)
            await vc.disconnect()
        except Exception as e:
            print(f"⚠️ Error during join or playback: {e}")
