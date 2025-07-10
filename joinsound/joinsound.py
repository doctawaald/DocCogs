from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel using the Audio cog (Lavalink or FFmpeg), with debugging and fallback."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": [], "auto_disconnect": True, "disconnect_delay": 30}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.disconnect_tasks = {}
        print("✅ JoinSound cog initialized with debug and playback fallback.")

    @commands.command()
    async def toggledisconnect(self, ctx):
        """Toggle auto-disconnect on or off for this server."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can toggle auto-disconnect.")
        current = await self.config.guild(ctx.guild).auto_disconnect()
        new = not current
        await self.config.guild(ctx.guild).auto_disconnect.set(new)
        await ctx.send(f"🔌 Auto-disconnect is now {'enabled' if new else 'disabled'}.")

    @commands.command()
    async def setdisconnectdelay(self, ctx, seconds: int):
        """Set the idle disconnect delay in seconds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can set the disconnect delay.")
        if seconds < 5 or seconds > 300:
            return await ctx.send("❌ Delay must be between 5 and 300 seconds.")
        await self.config.guild(ctx.guild).disconnect_delay.set(seconds)
        await ctx.send(f"⏱️ Auto-disconnect delay set to {seconds} seconds.")

    @commands.command()
    async def joinroles(self, ctx):
        """List roles permitted to set join sounds."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles allowed.")
        names = [discord.utils.get(ctx.guild.roles, id=r).name for r in roles if discord.utils.get(ctx.guild.roles, id=r)]
        await ctx.send("✅ Allowed roles: " + ", ".join(names))

    @commands.command()
    async def joinrole(self, ctx, add: bool, role: discord.Role):
        """Add (`True`) or remove (`False`) a role from allowed join-sound roles (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if add:
            if role.id in roles:
                return await ctx.send(f"❌ Role `{role.name}` already allowed.")
            roles.append(role.id)
            action = 'added'
        else:
            if role.id not in roles:
                return await ctx.send(f"❌ Role `{role.name}` not in allowed list.")
            roles.remove(role.id)
            action = 'removed'
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` {action}.")

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """Set your join sound (URL or upload local file)."""
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ No permission.")
        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        local = os.path.join(folder, f"{ctx.author.id}.mp3")
        # clear old
        if os.path.isfile(local): os.remove(local)
        await self.config.user(ctx.author).mp3_url.clear()
        # url mode
        if url:
            if not url.lower().endswith('.mp3'):
                return await ctx.send("❌ URL must end with .mp3")
            await self.config.user(ctx.author).mp3_url.set(url)
            return await ctx.send(f"✅ Join sound URL set: {url}")
        # upload
        if not ctx.message.attachments:
            return await ctx.send("📎 Provide URL or upload .mp3")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith('.mp3'):
            return await ctx.send("❌ Only .mp3 allowed")
        await att.save(local)
        await ctx.send("✅ Local join sound saved.")

    @commands.command()
    async def cogtest(self, ctx):
        """Test if JoinSound cog active."""
        await ctx.send("✅ JoinSound cog active.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        print(f"🔔 UPDATE: {member} from {before.channel} to {after.channel}")
        if before.channel == after.channel or member.bot or after.channel is None:
            print("⏭️ skipping")
            return
        # determine source
        folder = "data/joinsound/mp3s/"
        local = os.path.join(folder, f"{member.id}.mp3")
        url = await self.config.user(member).mp3_url()
        source = local if os.path.isfile(local) else url
        if not source:
            print(f"🛑 no source for {member.display_name}")
            return
        # get audio cog
        audio = self.bot.get_cog('Audio')
        print(f"Audio cog methods: {dir(audio) if audio else 'None'}")
        if not audio:
            print("❌ Audio cog missing")
            return
        # fake context
        class F: pass
        fake = F()
        fake.bot = self.bot
        fake.author = member
        fake.guild = after.channel.guild
        fake.channel = after.channel
        fake.clean_content = source
        fake.send = lambda *a, **k: None
        # try various methods
        try:
            if hasattr(audio, 'cmd_play'):
                print("Using cmd_play")
                await audio.cmd_play(fake, source)
            elif hasattr(audio, 'play'):
                print("Using play")
                await audio.play(fake, source)
            elif hasattr(audio, 'play_path'):
                print("Using play_path")
                await audio.play_path(fake, source)
            elif hasattr(audio, 'play_url'):
                print("Using play_url")
                await audio.play_url(fake, source)
            else:
                print("⚠️ No playback method found on Audio cog")
        except Exception as e:
            print(f"⚠️ Error playing via Audio cog: {e}")
            traceback.print_exc()
