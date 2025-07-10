from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel using the Audio cog (Lavalink or FFmpeg)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": [], "auto_disconnect": True, "disconnect_delay": 30}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.disconnect_tasks = {}
        print("✅ JoinSound cog initialized using Audio cog playback.")

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
    async def addjoinsoundrole(self, ctx, role: discord.Role):
        """Grant a role permission to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id in roles:
            return await ctx.send(f"❌ Role `{role.name}` already allowed.")
        roles.append(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` added.")

    @commands.command()
    async def removejoinsoundrole(self, ctx, role: discord.Role):
        """Revoke a role's permission to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id not in roles:
            return await ctx.send(f"❌ Role `{role.name}` not in allowed list.")
        roles.remove(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` removed.")

    @commands.command()
    async def listjoinsoundroles(self, ctx):
        """List roles permitted to set join sounds."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles allowed.")
        names = [discord.utils.get(ctx.guild.roles, id=r).name for r in roles if discord.utils.get(ctx.guild.roles, id=r)]
        await ctx.send("✅ Allowed roles: " + ", ".join(names))

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """Set your join sound (URL or upload local file)."""
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ No permission.")
        # prepare folder
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
        # upload mode
        if not ctx.message.attachments:
            return await ctx.send("📎 Provide URL or upload .mp3")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith('.mp3'):
            return await ctx.send("❌ Only .mp3 allowed")
        await att.save(local)
        await ctx.send("✅ Local join sound saved.")

    @commands.command()
    async def cogtest(self, ctx):
        await ctx.send("✅ JoinSound cog active.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel or member.bot or after.channel is None:
            return
        # determine source
        folder = "data/joinsound/mp3s/"
        local = os.path.join(folder, f"{member.id}.mp3")
        url = await self.config.user(member).mp3_url()
        if os.path.isfile(local):
            source = local
            play_func = 'path'
        elif url:
            source = url
            play_func = 'url'
        else:
            return
        audio = self.bot.get_cog('Audio')
        if not audio:
            print("❌ Audio cog missing")
            return
        # create fake ctx
        fake_ctx = type('C', (), {})()
        fake_ctx.bot = self.bot
        fake_ctx.author = member
        fake_ctx.guild = after.channel.guild
        fake_ctx.channel = after.channel
        fake_ctx.send = lambda *a, **k: None
        try:
            print(f"🎧 Queuing join sound ({play_func}) for {member.display_name}")
            if play_func == 'path':
                await audio.play_path(fake_ctx, source)
            else:
                await audio.play_url(fake_ctx, source)
        except Exception as e:
            print(f"⚠️ Error queuing audio: {e}")
            traceback.print_exc()
        # auto disconnect handled by Audio cog
