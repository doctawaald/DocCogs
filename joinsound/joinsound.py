from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel using Audio cog cmd_play."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": []}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        print("✅ JoinSound cog initialized: using Audio.cmd_play for URL playback.")

    @commands.command()
    async def addjoinsoundrole(self, ctx, role: discord.Role):
        """Add a role allowed to set join sounds (bot owner only)."""
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
            return await ctx.send(f"❌ Role `{role.name}` is not allowed.")
        roles.remove(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ Role `{role.name}` removed from allowed join-sound roles.")

    @commands.command()
    async def listjoinsoundroles(self, ctx):
        """List roles permitted to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles allowed currently.")
        names = [discord.utils.get(ctx.guild.roles, id=r).name for r in roles if discord.utils.get(ctx.guild.roles, id=r)]
        await ctx.send("✅ Allowed join-sound roles: " + ", ".join(names))

    @commands.command()
    async def joinsound(self, ctx, url: str):
        """
        Set your join sound URL (.mp3 only):
        - Provide a direct `.mp3` URL as argument.
        """
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission to set join sounds.")
        if not url.lower().endswith('.mp3'):
            return await ctx.send("❌ URL must end with .mp3")
        await self.config.user(ctx.author).mp3_url.set(url)
        await ctx.send(f"✅ Join sound URL set: {url}")

    @commands.command()
    async def cogtest(self, ctx):
        """Test if JoinSound cog is active."""
        await ctx.send("✅ JoinSound cog loaded.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        print(f"🔔 Voice update: {member} from {before.channel} to {after.channel}")
        if before.channel == after.channel or member.bot or after.channel is None:
            return
        url = await self.config.user(member).mp3_url()
        if not url:
            print(f"🛑 No URL set for {member.display_name}.")
            return
        audio = self.bot.get_cog('Audio')
        if not audio:
            print("❌ Audio cog missing.")
            return
        # Build fake context
        class FakeCtx:
            pass
        fake = FakeCtx()
        fake.bot = self.bot
        fake.author = member
        fake.guild = after.channel.guild
        fake.channel = after.channel
        fake.clean_content = url
        fake.send = lambda *a, **k: None
        try:
            print(f"🎧 Calling Audio.cmd_play for {member.display_name}")
            await audio.cmd_play(fake, url)
        except Exception as e:
            print(f"⚠️ Error in cmd_play: {e}")
            traceback.print_exc()
