from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel (URL or upload), with role permissions and auto-disconnect."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": [], "auto_disconnect": True, "disconnect_delay": 30}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.voice_clients = {}       # guild_id -> VoiceClient
        self.disconnect_tasks = {}    # guild_id -> asyncio.Task
        print("✅ JoinSound cog initialized.")

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
        await ctx.send(f"✅ Role `{role.name}` added.")

    @commands.command()
    async def removejoinsoundrole(self, ctx, role: discord.Role):
        """Remove a role from allowed join-sound roles (bot owner only)."""
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
        """List roles permitted to set join sounds (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can view allowed roles.")
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            return await ctx.send("ℹ️ No roles currently allowed.")
        names = [discord.utils.get(ctx.guild.roles, id=r).name for r in roles if discord.utils.get(ctx.guild.roles, id=r)]
        await ctx.send("✅ Allowed roles: " + ", ".join(names))

    @commands.command()
    async def toggledisconnect(self, ctx):
        """Toggle auto-disconnect on or off for this server (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can toggle auto-disconnect.")
        current = await self.config.guild(ctx.guild).auto_disconnect()
        new = not current
        await self.config.guild(ctx.guild).auto_disconnect.set(new)
        await ctx.send(f"🔌 Auto-disconnect is now {'enabled' if new else 'disabled'}.")

    @commands.command()
    async def setdisconnectdelay(self, ctx, seconds: int):
        """Set the auto-disconnect delay in seconds (bot owner only, 5–300)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can set disconnect delay.")
        if seconds < 5 or seconds > 300:
            return await ctx.send("❌ Delay must be between 5 and 300 seconds.")
        await self.config.guild(ctx.guild).disconnect_delay.set(seconds)
        await ctx.send(f"⏱️ Disconnect delay set to {seconds}s.")

    @commands.command()
    async def joinsound(self, ctx, url: str = None):
        """
        Set your join sound:
        - Provide a direct .mp3 URL as argument.
        - Or upload a .mp3 file as attachment if no URL provided.
        """
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission.")
        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{ctx.author.id}.mp3")
        if os.path.isfile(path): os.remove(path)
        await self.config.user(ctx.author).mp3_url.clear()
        if url:
            if not url.lower().endswith('.mp3'):
                return await ctx.send("❌ URL must end with .mp3")
            await self.config.user(ctx.author).mp3_url.set(url)
            return await ctx.send(f"✅ Join sound URL set: {url}")
        if not ctx.message.attachments:
            return await ctx.send("📎 Provide a .mp3 URL or upload a .mp3 file.")
        att = ctx.message.attachments[0]
        if not att.filename.lower().endswith('.mp3'):
            return await ctx.send("❌ Only .mp3 allowed.")
        try:
            await att.save(path)
            await ctx.send("✅ Local join sound saved.")
        except Exception as e:
            await ctx.send(f"❌ Failed to save file: {e}")

    @commands.command()
    async def cogtest(self, ctx):
        """Test if cog is loaded."""
        await ctx.send("✅ JoinSound cog active.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
                # If bot was disconnected externally, skip and remove voice client to prevent auto-reconnect
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            print("🔔 Bot was disconnected externally, skipping auto-join and cleaning up.")
            guild_id = before.channel.guild.id
            # Remove and disconnect underlying vc to stop resume
            vc = self.voice_clients.pop(guild_id, None)
            if vc:
                try:
                    await vc.disconnect()
                except Exception as e:
                    print(f"⚠️ Error cleaning up voice client: {e}")
            # Cancel any pending disconnect task
            task = self.disconnect_tasks.pop(guild_id, None)
            if task:
                task.cancel()
            return
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            print("🔔 Bot was disconnected externally, skipping auto-join.")
            # Do not reconnect
            return

        print(f"🔔 Voice update: {member} from {before.channel} to {after.channel}")
        if before.channel == after.channel or member.bot or after.channel is None:
            return

        # Determine source
        url = await self.config.user(member).mp3_url()
        folder = "data/joinsound/mp3s/"
        path = os.path.join(folder, f"{member.id}.mp3")
        source = url if not os.path.isfile(path) else path
        if not source:
            return

        guild = after.channel.guild
        vc = self.voice_clients.get(guild.id)
        try:
            if vc is None or not vc.is_connected():
                vc = await after.channel.connect()
                try:
                    await vc.guild.me.edit(deafen=True)
                except:
                    pass
                self.voice_clients[guild.id] = vc
            elif vc.channel.id != after.channel.id:
                await vc.move_to(after.channel)
        except Exception as e:
            print(f"⚠️ Connect error: {e}")
            traceback.print_exc()
            return

        # Play audio
        try:
            vc.play(discord.FFmpegPCMAudio(source))
            while vc.is_playing():
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Playback error: {e}")
            traceback.print_exc()
            return

        # Auto-disconnect
        if await self.config.guild(guild).auto_disconnect():
            delay = await self.config.guild(guild).disconnect_delay()
            task = self.disconnect_tasks.get(guild.id)
            if task:
                task.cancel()
            self.disconnect_tasks[guild.id] = asyncio.create_task(self._idle_disconnect(guild.id, delay))

    async def _idle_disconnect(self, guild_id, delay):
        await asyncio.sleep(delay)
        vc = self.voice_clients.get(guild_id)
        if vc and vc.is_connected():
            try:
                await vc.disconnect()
            except:
                pass
        self.voice_clients.pop(guild_id, None)
        self.disconnect_tasks.pop(guild_id, None)
