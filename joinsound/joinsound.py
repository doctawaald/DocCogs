from redbot.core import commands, Config
import discord
import os
import asyncio
import traceback

class JoinSound(commands.Cog):
    """Plays a sound when a user joins a voice channel with persistent connections and supports both URLs and local files."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=43219876)
        default_user = {"mp3_url": None}
        default_guild = {"allowed_roles": []}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)
        self.disconnect_tasks = {}  # guild_id -> asyncio.Task
        print("✅ JoinSound cog initialized with improved voice handling.")

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
        # Permission check: bot owner or allowed role
        if not await self.bot.is_owner(ctx.author):
            allowed = await self.config.guild(ctx.guild).allowed_roles()
            if not any(r.id in allowed for r in ctx.author.roles):
                return await ctx.send("❌ You don't have permission to set join sounds.")

        folder = "data/joinsound/mp3s/"
        os.makedirs(folder, exist_ok=True)
        local_path = os.path.join(folder, f"{ctx.author.id}.mp3")

        # Clear old local file
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
        await ctx.send("✅ JoinSound cog is active with improved voice handling.")

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

        guild = after.channel.guild
        # Find existing voice client
        vc = discord.utils.get(self.bot.voice_clients, guild=guild)
        try:
            if vc is None:
                print(f"🎧 Connecting to voice channel {after.channel} for guild {guild.id}")
                vc = await after.channel.connect()
            elif vc.channel.id != after.channel.id:
                print(f"🔀 Moving voice client to {after.channel}")
                await vc.move_to(after.channel)
        except discord.errors.ClientException as e:
            print(f"⚠️ Voice connection issue: {e}")
            traceback.print_exc()
            # Attempt fresh connect
            try:
                vc = await after.channel.connect()
            except Exception as e2:
                print(f"⚠️ Failed fresh connect: {e2}")
                return
        except Exception as e:
            print(f"⚠️ Unexpected error connecting/moving: {e}")
            traceback.print_exc()
            return

        # Cancel pending idle disconnect if any
        task = self.disconnect_tasks.get(guild.id)
        if task:
            task.cancel()

        # Play audio
        try:
            print(f"▶️ Playing {source} for {member.display_name}")
            vc.play(discord.FFmpegPCMAudio(source))
            while vc.is_playing():
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Playback error for {member.display_name}: {e}")
            traceback.print_exc()

        # Schedule idle disconnect in 30s
        async def _idle_disconnect():
            await asyncio.sleep(30)
            if vc.is_connected():
                try:
                    await vc.disconnect()
                    print(f"🔌 Idle disconnected voice client for guild {guild.id}")
                except:
                    pass
            self.disconnect_tasks.pop(guild.id, None)

        self.disconnect_tasks[guild.id] = asyncio.create_task(_idle_disconnect())
