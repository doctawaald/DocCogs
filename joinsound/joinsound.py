from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback
from types import SimpleNamespace

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        self.config.register_user(**default_user)
        print("✅ JoinSound cog initialized.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def joinsound(self, ctx, url: str = None):
        """
        Set a join sound (admin only):
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
    async def cogtest(self, ctx):
        """Test if JoinSound cog is active."""
        await ctx.send("✅ JoinSound cog is loaded and responding.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        print(f"🔔 Voice update: {member} changed from {before.channel} to {after.channel}")

        if before.channel == after.channel or member.bot or after.channel is None:
            print("⏭️ No relevant channel change or bot/self join — skipping.")
            return

        local_path = f"data/joinsound/mp3s/{member.id}.mp3"
        url = await self.config.user(member).mp3_url()
        audio_available = os.path.isfile(local_path) or url

        if not audio_available:
            print(f"🛑 No audio set for {member.display_name} — not playing anything.")
            return

        source = local_path if os.path.isfile(local_path) else url

        audio_cog = self.bot.get_cog("Audio")
        if not audio_cog:
            print("❌ Audio cog not loaded — cannot play sound.")
            return

        try:
            # Fake context to trigger play command
            fake_ctx = SimpleNamespace()
            fake_ctx.guild = after.channel.guild
            fake_ctx.author = member
            fake_ctx.voice_client = None
            fake_ctx.channel = after.channel
            fake_ctx.clean_content = source
            fake_ctx.send = lambda *args, **kwargs: None

            print(f"🎧 Asking Audio cog to queue sound for {member.display_name} in {after.channel}")

            await audio_cog.cmd_play(fake_ctx, source)

        except Exception as e:
            print(f"⚠️ Error using Audio cog fallback: {e}")
            traceback.print_exc()
