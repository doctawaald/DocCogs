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
        default_guild = {"allowed_roles": []}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        print("✅ JoinSound cog initialized. Ensure Opus + PyNaCl are installed.")

    @commands.command()
    async def addjoinsoundrole(self, ctx, role: discord.Role):
        """Add a role that can set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id in roles:
            return await ctx.send(f"❌ Role `{role.name}` is already allowed.")
        roles.append(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` added to allowed join-sound roles.")

    @commands.command()
    async def removejoinsoundrole(self, ctx, role: discord.Role):
        """Remove a role from allowed join-sound roles (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id not in roles:
            return await ctx.send(f"❌ Role `{role.name}` is not in allowed roles.")
        roles.remove(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` removed from allowed roles.")

    @commands.command()
    async def listjoinsoundroles(self, ctx):
        """List roles allowed to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles are currently allowed to set join sounds.")
        names = [
            discord.utils.get(ctx.guild.roles, id=r).name
            for r in roles
            if discord.utils.get(ctx.guild.roles, id=r)
        ]
        await ctx.send("✅ Allowed join-sound roles: " + ", ".join(names))

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """
        Set your join sound:
        - Upload an mp3 file as an attachment if no URL provided.
        - Or provide a direct .mp3 URL.
        """
        # Permission check: owner or allowed role
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(role.id in allowed for role in ctx.author.roles):
                return await ctx.send("❌ You don't have permission to set join sounds.")

        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        local_path = os.path.join(folder, f"{ctx.author.id}.mp3")

        # Clear previous audio settings
        # Remove old local file if switching to URL or resetting
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                print(f"⚠️ Could not remove old file: {e}")

        # URL mode
        if url:
            if not url.lower().endswith(".mp3"):
                return await ctx.send("❌ The link must end with `.mp3`.")
            # Clear any old URL then set new
            await self.config.user(ctx.author).mp3_url.clear()
            await self.config.user(ctx.author).mp3_url.set(url)
            return await ctx.send(f"✅ Your join MP3 URL has been set: {url}")

        # Upload mode
        if not ctx.message.attachments:
            return await ctx.send("📎 Upload a `.mp3` file or provide a URL.")

        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith(".mp3"):
            return await ctx.send("❌ Only `.mp3` files are allowed.")

        # Clear old URL if uploading new file
        await self.config.user(ctx.author).mp3_url.clear()
        # Save new file
        try:
            await att.save(local_path)
        except Exception as e:
            return await ctx.send(f"❌ Failed to save file: {e}")

        return await ctx.send("✅ Your local join MP3 has been saved!")

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

        try:
            print(f"🎧 Attempting to join {after.channel} for {member.display_name}")
            vc = await after.channel.connect()
            vc.play(discord.FFmpegPCMAudio(source))
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
        except Exception as e:
            print(f"⚠️ Error during join or playback for {member.display_name}: {e}")
            traceback.print_exc()
