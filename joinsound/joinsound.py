from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Play a per-user join sound (URL or uploaded .mp3) when a user joins a voice channel.

    - Permissions: bot owner or allowed roles can set (per user) URLs or uploads.
    - Auto-disconnect after playback (configurable).
    - No auto-reconnect loops; hardened against stale voice state after music/other cogs.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {
            "allowed_roles": [],
            "auto_disconnect": True,
            "disconnect_delay": 30,
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.voice_clients = {}       # guild_id -> VoiceClient (cache only; guild.voice_client is truth)
        self.disconnect_tasks = {}    # guild_id -> asyncio.Task
        print("✅ JoinSound loaded (hardened VC lifecycle).")

    # ---------- Role management ----------

    @commands.command()
    async def addjoinsoundrole(self, ctx, role: discord.Role):
        """Add a role allowed to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id in roles:
            return await ctx.send(f"❌ `{role.name}` is already allowed.")
        roles.append(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ `{role.name}` added to allowed roles.")

    @commands.command()
    async def removejoinsoundrole(self, ctx, role: discord.Role):
        """Remove a role from allowed join-sound roles (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can modify allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if role.id not in roles:
            return await ctx.send(f"❌ `{role.name}` is not in allowed roles.")
        roles.remove(role.id)
        await self.config.guild(ctx.guild).allowed_roles.set(roles)
        await ctx.send(f"✅ `{role.name}` removed.")

    @commands.command()
    async def listjoinsoundroles(self, ctx):
        """List roles permitted to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles currently allowed.")
        names = [
            discord.utils.get(ctx.guild.roles, id=r).name
            for r in roles
            if discord.utils.get(ctx.guild.roles, id=r)
        ]
        await ctx.send("✅ Allowed roles: " + ", ".join(names))

    # ---------- Settings ----------

    @commands.command()
    async def toggledisconnect(self, ctx):
        """Toggle auto-disconnect on/off (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can toggle this.")
        current = await self.config.guild(ctx.guild).auto_disconnect()
        new = not current
        await self.config.guild(ctx.guild).auto_disconnect.set(new)
        await ctx.send(f"🔌 Auto-disconnect is now {'enabled' if new else 'disabled'}.")

    @commands.command()
    async def setdisconnectdelay(self, ctx, seconds: int):
        """Set auto-disconnect delay in seconds (5–300, bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can set this.")
        if seconds < 5 or seconds > 300:
            return await ctx.send("❌ Delay must be between 5 and 300 seconds.")
        await self.config.guild(ctx.guild).disconnect_delay.set(seconds)
        await ctx.send(f"⏱️ Disconnect delay set to {seconds}s.")

    # ---------- User setup ----------

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """
        Set your own join sound:
        - Provide a direct .mp3 URL, or
        - Upload a .mp3 attachment (if no URL).
        """
        # Permission check (owner or allowed roles)
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission.")
        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{ctx.author.id}.mp3")

        # Clear previous
        if os.path.isfile(path):
            os.remove(path)
        await self.config.user(ctx.author).mp3_url.clear()

        # URL
        if url:
            if not url.lower().endswith(".mp3"):
                return await ctx.send("❌ URL must end with .mp3")
            await self.config.user(ctx.author).mp3_url.set(url)
            return await ctx.send(f"✅ Your join sound URL set: {url}")

        # Attachment
        if not ctx.message.attachments:
            return await ctx.send("📎 Provide a .mp3 URL or upload a .mp3 file.")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith(".mp3"):
            return await ctx.send("❌ Only .mp3 allowed.")
        try:
            await att.save(path)
            await ctx.send("✅ Your local join sound saved.")
        except Exception as e:
            return await ctx.send(f"❌ Failed to save file: {e}")

    @commands.command()
    async def setjoinsoundfor(self, ctx, member: discord.Member, url: str = None):
        """
        Set join sound for another user (owner or allowed roles):
        - Mention a user and provide a .mp3 URL or upload a .mp3.
        """
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission.")
        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{member.id}.mp3")

        # Clear previous for target
        if os.path.isfile(path):
            os.remove(path)
        await self.config.user(member).mp3_url.clear()

        if url:
            if not url.lower().endswith(".mp3"):
                return await ctx.send("❌ URL must end with .mp3")
            await self.config.user(member).mp3_url.set(url)
            return await ctx.send(f"✅ Join sound set for {member.display_name}: {url}")

        if not ctx.message.attachments:
            return await ctx.send("📎 Provide a .mp3 URL or upload a .mp3 file.")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith(".mp3"):
            return await ctx.send("❌ Only .mp3 allowed.")
        try:
            await att.save(path)
            return await ctx.send(f"✅ Local join sound saved for {member.display_name}.")
        except Exception as e:
            return await ctx.send(f"❌ Failed to save file: {e}")

    @commands.command()
    async def cogtest(self, ctx):
        """Basic health check."""
        await ctx.send("✅ JoinSound cog active.")

    # ---------- Voice handling ----------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Ignore non-changes & bots
        if before.channel == after.channel or member.bot:
            return

        # If the bot itself was disconnected externally → fully clean and stop (no reconnect loop)
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            gid = before.channel.guild.id
            vc = self.voice_clients.pop(gid, None) or before.channel.guild.voice_client
            if vc:
                try:
                    if hasattr(vc, "_should_reconnect"):
                        vc._should_reconnect = False
                    await vc.disconnect()
                except Exception:
                    pass
            task = self.disconnect_tasks.pop(gid, None)
            if task:
                task.cancel()
            print(f"🔔 Bot disconnected in guild {gid}; will (re)connect on next user join only.")
            return

        # Only react when a user joins a channel
        if before.channel is None and after.channel:
            folder = "data/joinsound/mp3s/"
            path = os.path.join(folder, f"{member.id}.mp3")
            url = await self.config.user(member).mp3_url()
            source = url if not os.path.isfile(path) else path
            if not source:
                return

            gid = after.channel.guild.id

            # --- Hardened connect/move block ---
            existing_vc = after.channel.guild.voice_client
            cache_vc = self.voice_clients.get(gid)
            vc = existing_vc or cache_vc

            try:
                if vc and vc.is_connected():
                    if vc.channel.id != after.channel.id:
                        print(f"🔀 Moving VC to {after.channel}")
                        await vc.move_to(after.channel)
                else:
                    # Clean any cached dead client
                    if cache_vc and not cache_vc.is_connected():
                        try:
                            if hasattr(cache_vc, "_should_reconnect"):
                                cache_vc._should_reconnect = False
                            await cache_vc.disconnect()
                        except Exception:
                            pass
                        self.voice_clients.pop(gid, None)

                    print("🎧 Creating fresh voice connection (reconnect=False)")
                    vc = await after.channel.connect(reconnect=False)
                    try:
                        await vc.guild.me.edit(deafen=True)
                    except Exception:
                        pass
                    self.voice_clients[gid] = vc

            except Exception as e:
                print(f"⚠️ Connect error: {e} — hard reset voice state for guild {gid}")
                try:
                    if vc:
                        if hasattr(vc, "_should_reconnect"):
                            vc._should_reconnect = False
                        await vc.disconnect()
                except Exception:
                    pass
                self.voice_clients.pop(gid, None)
                return

            # Play
            try:
                vc.play(discord.FFmpegPCMAudio(source))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
            except Exception as e:
                print(f"⚠️ Playback error: {e}")
                traceback.print_exc()
                return

            # Auto-disconnect timer
            if await self.config.guild(after.channel.guild).auto_disconnect():
                delay = await self.config.guild(after.channel.guild).disconnect_delay()
                task = self.disconnect_tasks.get(gid)
                if task:
                    task.cancel()
                self.disconnect_tasks[gid] = asyncio.create_task(self._idle_disconnect(gid, delay))

    async def _idle_disconnect(self, guild_id, delay):
        await asyncio.sleep(delay)
        vc = self.voice_clients.get(guild_id) or None
        if vc and vc.is_connected():
            try:
                await vc.disconnect()
            except Exception:
                pass
        self.voice_clients.pop(guild_id, None)
        self.disconnect_tasks.pop(guild_id, None)
