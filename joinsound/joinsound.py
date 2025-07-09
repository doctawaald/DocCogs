from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        self.config.register_user(**default_user)

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
            print(f"🛑 No audio set for {member.display_name} — not joining.")
            return

        source = local_path if os.path.isfile(local_path) else url

        try:
            print(f"🎧 Attempting to join {after.channel} for {member.display_name}")
            vc = await after.channel.connect()
            if audio_available:
                vc.play(discord.FFmpegPCMAudio(source))
                while vc.is_playing():
                    await asyncio.sleep(1)
            await asyncio.sleep(1.5)
            await vc.disconnect()
        except Exception as e:
            print(f"⚠️ Error during join or playback for {member.display_name}: {e}")
            traceback.print_exc()
