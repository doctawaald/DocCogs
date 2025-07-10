from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel with persistent connections."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": []}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.voice_clients = {}
        self.disconnect_tasks = {}
        print("✅ JoinSound cog initialized with persistent voice connections.")

    @commands.command()
    async def addjoinsoundrole(self, ctx, role: discord.Role):
        """Grant a role permission to set join sounds (bot owner only)."""
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
        """Revoke a role's permission to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id not in roles:
            return await ctx.send(f"❌ Role `{role.name}` is not in allowed roles.")
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
            return await ctx.send("ℹ️ No roles are currently allowed to set join sounds.")
        names = [discord.utils.get(ctx.guild.roles, id=r).name for r in roles if discord.utils.get(ctx.guild.roles, id=r)]
        await ctx.send("✅ Allowed join-sound roles: " + ", ".join(names))

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """
        Set your join sound (admin/role only):
        - Provide a direct .mp3 URL as argument.
        - Or upload a .mp3 file as attachment if no URL provided.
        """
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission to set join sounds.")

        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        local_path = os.path.join(folder, f"{ctx.author.id}.mp3")

        # Clear old local file if exists
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                print(f"⚠️ Failed to remove old local file: {e}")
        # Clear old URL
        await self.config.user(ctx.author).mp3_url.clear()

        # URL mode
        if url:
            if not url.lower().endswith(".mp3"):
                return await ctx.send("❌ The link must end with `.mp3`.")
            await self.config.user(ctx.author).mp3_url.set(url)
            return await ctx.send(f"✅ Your join MP3 URL has been set: {url}")

        # Upload mode
        if not ctx.message.attachments:
            return await ctx.send("📎 Please provide a .mp3 URL or upload a .mp3 file as attachment.")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith(".mp3"):
            return await ctx.send("❌ Only .mp3 files are allowed.")
        try:
            await att.save(local_path)
        except Exception as e:
            return await ctx.send(f"❌ Failed to save file: {e}")

        return await ctx.send("✅ Your local join sound has been set!")

    @commands.command()
    async def cogtest(self, ctx):
        """Test if JoinSound cog is loaded."""
        await ctx.send("✅ JoinSound cog is active with persistent connections.")

    async def _idle_disconnect(self, guild_id, delay=60):
        await asyncio.sleep(delay)
        vc = self.voice_clients.get(guild_id)
        if vc and vc.is_connected():
            try:
                await vc.disconnect()
                print(f"🔌 Disconnected idle voice client for guild {guild_id}")
            except Exception:
                pass
        self.voice_clients.pop(guild_id, None)
        self.disconnect_tasks.pop(guild_id, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        print(f"🔔 Voice update: {member} from {before.channel} to {after.channel}")
        if before.channel == after.channel or member.bot or after.channel is None:
            return

        # Determine source: local file or URL
        folder = "data/joinsound/mp3s/"
        local_path = os.path.join(folder, f"{member.id}.mp3")
        url = await self.config.user(member).mp3_url()
        if os.path.isfile(local_path):
            source = local_path
        elif url:
            source = url
        else:
            print(f"🛑 No audio set for {member.display_name}.")
            return

        guild_id = after.guild.id
        vc = self.voice_clients.get(guild_id)
        if not vc or not vc.is_connected():
            try:
                vc = await after.channel.connect()
                self.voice_clients[guild_id] = vc
                print(f"🎧 Connected persistent voice client in guild {guild_id}")
            except Exception as e:
                print(f"⚠️ Cannot connect voice for {member.display_name}: {e}")
                traceback.print_exc()
                return

        # Cancel pending disconnect
        task = self.disconnect_tasks.get(guild_id)
        if task:
            task.cancel()

        # Play audio
        try:
            vc.play(discord.FFmpegPCMAudio(source))
            while vc.is_playing():
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Playback error for {member.display_name}: {e}")
            traceback.print_exc()

        # Schedule idle disconnect
        self.disconnect_tasks[guild_id] = asyncio.create_task(self._idle_disconnect(guild_id))
