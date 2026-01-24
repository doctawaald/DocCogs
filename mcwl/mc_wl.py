import discord
from redbot.core import commands, Config
from discord.ui import Select, View, Button
import re
import asyncio
import struct
from typing import Optional

class MCWhitelist(commands.Cog):
    """Manage Minecraft Whitelists via Discord using RCON."""
    
    def __init__(self, bot):
        self.bot = bot
        # BELANGRIJK: Dit nummer moet hetzelfde blijven om je settings te behouden!
        self.config = Config.get_conf(self, identifier=1234567890)
        
        self.config.register_guild(
            log_channel=None,
            whitelist_role=None,
            game_role=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            welcome_message="✅ You have been added to the Minecraft whitelist!\nYour username `{mc_name}` is now authorized.",
            status_message=None
        )
        
        self.config.register_member(
            mc_name=None
        )

    # --- RCON & HELPER FUNCTIONS ---

    async def _rcon_command(self, host, port, password, command):
        """Sends an RCON command to the server."""
        try:
            reader, writer = await asyncio.open_connection(host, int(port))
            
            # Login Packet
            login_packet = b"\x00\x00\x00\x00"
            login_packet += struct.pack("<i", 3)
            login_packet += password.encode("utf-8") + b"\x00"
            login_packet += b"\x00\x00"
            
            writer.write(struct.pack("<i", len(login_packet)) + login_packet)
            await writer.drain()
            
            # Read login response
            login_response_length = struct.unpack("<i", await reader.read(4))[0]
            await reader.read(login_response_length)
            
            # Command Packet
            command_packet = b"\x01\x00\x00\x00"
            command_packet += struct.pack("<i", 2)
            command_packet += command.encode("utf-8") + b"\x00"
            command_packet += b"\x00\x00"
            
            writer.write(struct.pack("<i", len(command_packet)) + command_packet)
            await writer.drain()
            
            # Read command response
            response_length = struct.unpack("<i", await reader.read(4))[0]
            response = await reader.read(response_length)
            
            writer.close()
            await writer.wait_closed()

            return response[8:-2].decode("utf-8").strip()
        except Exception as e:
            raise e

    async def add_to_whitelist(self, guild, mc_name):
        try:
            config = await self.config.guild(guild).all()
            if not all([config["rcon_host"], config["rcon_port"], config["rcon_password"]]):
                return False, "RCON not configured."
            
            result = await self._rcon_command(
                config["rcon_host"],
                config["rcon_port"],
                config["rcon_password"],
                f"whitelist add {mc_name}"
            )
            # Check for success (Server response usually contains 'Added', 'Updated' or 'already')
            if "Added" in result or "Updated" in result or "already" in result.lower():
                return True, result
            return False, result
        except Exception as e:
            return False, str(e)

    async def remove_from_whitelist(self, guild, mc_name):
        try:
            config = await self.config.guild(guild).all()
            if not all([config["rcon_host"], config["rcon_port"], config["rcon_password"]]):
                return False, "RCON not configured."
            
            result = await self._rcon_command(
                config["rcon_host"],
                config["rcon_port"],
                config["rcon_password"],
                f"whitelist remove {mc_name}"
            )
            if "Removed" in result or "left" in result:
                return True, result
            return False, result
        except Exception as e:
            return False, str(e)

    # --- UI VIEWS ---

    class StatusView(View):
        def __init__(self, cog):
            super().__init__(timeout=None)
            self.cog = cog
        
        @discord.ui.button(label="Refresh", style=discord.ButtonStyle.grey, custom_id="refresh_status")
        async def refresh_button(self, interaction: discord.Interaction, button: Button):
            await self.update_embed(interaction)
        
        async def update_embed(self, interaction: Optional[discord.Interaction] = None, ctx: Optional[commands.Context] = None):
            guild = interaction.guild if interaction else ctx.guild
            game_role_id = await self.cog.config.guild(guild).game_role()
            whitelist_role_id = await self.cog.config.guild(guild).whitelist_role()
            
            if not game_role_id or not whitelist_role_id:
                return
            
            game_role = guild.get_role(game_role_id)
            whitelist_role = guild.get_role(whitelist_role_id)
            
            members = sorted(game_role.members, key=lambda m: m.display_name) if game_role else []
            
            embed = discord.Embed(
                title=f"Whitelist Status - {game_role.name if game_role else 'Unknown'}",
                description="🟢 = Whitelisted | 🔴 = Not whitelisted\n\n",
                color=game_role.color if game_role else 0x000000
            )
            
            for member in members[:25]:
                mc_name = await self.cog.config.member(member).mc_name()
                status = "🟢" if whitelist_role and whitelist_role in member.roles else "🔴"
                mc_text = f"MC: `{mc_name}`" if mc_name else "*No MC name*"
                embed.description += f"{status} {member.mention} - {mc_text}\n"
            
            if len(members) > 25:
                embed.set_footer(text=f"Showing first 25 of {len(members)} members")
            
            if interaction:
                await interaction.response.edit_message(embed=embed)
            elif ctx:
                return embed
            return embed

    class ProcessSelect(Select):
        def __init__(self, cog, guild, whitelist_role, options):
            super().__init__(
                placeholder="Select members to whitelist...",
                min_values=1,
                max_values=len(options),
                options=options
            )
            self.cog = cog
            self.guild = guild
            self.whitelist_role = whitelist_role
        
        async def callback(self, interaction: discord.Interaction):
            selected_ids = [int(i) for i in self.values]
            selected_members = [self.guild.get_member(i) for i in selected_ids]
            
            welcome_msg = await self.cog.config.guild(self.guild).welcome_message()
            
            await interaction.response.defer() # Wait signal
            
            for member in selected_members:
                if not member: continue
                try:
                    mc_name = await self.cog.config.member(member).mc_name()
                    
                    # Add role (Triggers listener, but we handle it safely)
                    if self.whitelist_role not in member.roles:
                         await member.add_roles(self.whitelist_role)
                    
                    # Send DM
                    try:
                        if mc_name:
                            await member.send(welcome_msg.format(mc_name=mc_name))
                    except discord.Forbidden:
                        pass
                    
                    # Force RCON update just in case
                    if mc_name:
                        await self.cog.add_to_whitelist(self.guild, mc_name)
                    
                except Exception:
                    pass
            
            # Update status embed
            status_view = self.cog.StatusView(self.cog)
            status_embed = await status_view.update_embed(ctx=await self.cog.bot.get_context(interaction.message))
            
            await interaction.edit_original_response(
                content="✅ Processing complete!",
                embed=status_embed,
                view=status_view
            )

    class ProcessView(View):
        def __init__(self, cog, guild, whitelist_role, options):
            super().__init__()
            self.add_item(MCWhitelist.ProcessSelect(cog, guild, whitelist_role, options))

    # --- COMMAND GROUPS ---

    @commands.group(name="mcwhitelist", aliases=["wl", "mcwl"])
    async def mcwl(self, ctx):
        """Main command for Minecraft Whitelist management."""
        pass

    # --- USER COMMANDS ---

    @mcwl.command(name="setname", aliases=["link", "addname"])
    async def set_mc_name(self, ctx, mc_name: str):
        """Link your Minecraft username to your Discord account."""
        if not 3 <= len(mc_name) <= 16:
            return await ctx.send("❌ Name must be between 3-16 characters.")
        if not re.match(r"^[a-zA-Z0-9_]+$", mc_name):
            return await ctx.send("❌ Name can only contain letters, numbers, and underscores.")
        
        guild = ctx.guild
        member = ctx.author
        old_name = await self.config.member(member).mc_name()
        
        # Security: Remove role if name changes to force re-verification if needed
        role_id = await self.config.guild(guild).whitelist_role()
        if role_id:
            role = guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role)
                await ctx.send("⚠️ Your whitelist role was temporarily removed because you changed your name.")
        
        await self.config.member(member).mc_name.set(mc_name)
        await ctx.send(f"✅ Your Minecraft name has been set to: `{mc_name}`")
        
        # Logging
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                action = f"changed name: `{old_name}` → `{mc_name}`" if old_name else f"set name to `{mc_name}`"
                await log_channel.send(f"📛 {member.mention} {action}")

    @mcwl.command(name="me", aliases=["info"])
    async def check_my_status(self, ctx):
        """Check your registered Minecraft name."""
        mc_name = await self.config.member(ctx.author).mc_name()
        if mc_name:
            await ctx.send(f"👤 Your registered MC name is: `{mc_name}`")
        else:
            await ctx.send("❌ You haven't set an MC name yet. Use `[p]wl link <name>`.")

    # --- ADMIN CONFIG COMMANDS ---

    @mcwl.group(name="config", aliases=["settings"])
    @commands.admin()
    async def mcwl_config(self, ctx):
        """Configure the whitelist settings."""
        pass

    @mcwl_config.command(name="rcon")
    async def config_rcon(self, ctx, host: str, port: int, password: str):
        """Set RCON credentials (IP Port Password)."""
        await self.config.guild(ctx.guild).rcon_host.set(host)
        await self.config.guild(ctx.guild).rcon_port.set(port)
        await self.config.guild(ctx.guild).rcon_password.set(password)
        await ctx.send("🔑 RCON credentials saved. Make sure the port is open!")

    @mcwl_config.command(name="wlrole")
    async def config_whitelist_role(self, ctx, role: discord.Role):
        """Set the role that grants whitelist access."""
        await self.config.guild(ctx.guild).whitelist_role.set(role.id)
        await ctx.send(f"🎟️ Whitelist role set to: {role.name}")

    @mcwl_config.command(name="gamerole")
    async def config_game_role(self, ctx, role: discord.Role):
        """Set the role containing potential players (the pool)."""
        await self.config.guild(ctx.guild).game_role.set(role.id)
        await ctx.send(f"🎮 Game role set to: {role.name}")

    @mcwl_config.command(name="logchannel")
    async def config_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for logs."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"📝 Logs will be sent to {channel.mention}")

    # --- ADMIN MANAGEMENT COMMANDS ---

    @mcwl.group(name="admin", aliases=["manage"])
    @commands.admin()
    async def mcwl_admin(self, ctx):
        """Directly manage members."""
        pass

    @mcwl_admin.command(name="remove")
    async def admin_remove(self, ctx, member: discord.Member):
        """Force remove someone from the whitelist."""
        guild = ctx.guild
        role_id = await self.config.guild(guild).whitelist_role()
        
        if not role_id: return await ctx.send("❌ No whitelist role configured.")
        role = guild.get_role(role_id)
        
        mc_name = await self.config.member(member).mc_name()
        
        # Remove role (triggers listener for RCON remove)
        if role and role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"✅ {member.mention} removed from whitelist and role taken.")
        else:
            # If they don't have the role, try RCON remove if name is known
            if mc_name:
                await self.remove_from_whitelist(guild, mc_name)
                await ctx.send(f"⚠️ {member.mention} didn't have the role, but `whitelist remove` command was sent.")
            else:
                await ctx.send("❌ User has no role and no MC name set.")

    @mcwl_admin.command(name="status", aliases=["dashboard"])
    async def admin_status(self, ctx):
        """Show the status dashboard."""
        guild = ctx.guild
        status_message_id = await self.config.guild(guild).status_message()
        
        view = self.StatusView(self)
        embed = await view.update_embed(ctx=ctx)
        
        # Try to update old message
        if status_message_id:
            try:
                message = await ctx.channel.fetch_message(status_message_id)
                await message.edit(embed=embed, view=view)
                return
            except:
                pass
        
        message = await ctx.send(embed=embed, view=view)
        await self.config.guild(guild).status_message.set(message.id)

    @mcwl_admin.command(name="wizard", aliases=["process"])
    async def admin_wizard(self, ctx):
        """Start the interactive whitelist wizard."""
        guild = ctx.guild
        game_role_id = await self.config.guild(guild).game_role()
        whitelist_role_id = await self.config.guild(guild).whitelist_role()
        
        if not game_role_id or not whitelist_role_id:
            return await ctx.send("❌ Configure roles first using `[p]wl config`")
        
        game_role = guild.get_role(game_role_id)
        whitelist_role = guild.get_role(whitelist_role_id)
        
        members = [m for m in game_role.members if not m.bot] if game_role else []
        if not members:
            return await ctx.send("❌ No members found in the Game Role.")

        options = []
        # Max 25 options in a dropdown
        for member in members[:25]:
            mc_name = await self.config.member(member).mc_name()
            label = f"{member.display_name}"[:25]
            desc = f"MC: {mc_name}"[:40] if mc_name else "No name set"
            options.append(discord.SelectOption(
                label=label,
                value=str(member.id),
                description=desc,
                emoji="🟢" if mc_name else "🔴"
            ))

        view = self.ProcessView(self, guild, whitelist_role, options)
        embed = discord.Embed(
            title="Whitelist Wizard",
            description="Select members to add to the whitelist.\n🟢 = Name Set\n🔴 = No Name (will be skipped)",
            color=whitelist_role.color
        )
        await ctx.send(embed=embed, view=view)

    # --- AUTOMATION (LISTENER) ---

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        role_id = await self.config.guild(guild).whitelist_role()
        if not role_id: return
        
        role = guild.get_role(role_id)
        if not role: return
        
        # ROLE ADDED -> ADD WHITELIST
        if role not in before.roles and role in after.roles:
            mc_name = await self.config.member(after).mc_name()
            log_channel_id = await self.config.guild(guild).log_channel()
            
            if not mc_name:
                if log_channel_id:
                    chan = guild.get_channel(log_channel_id)
                    await chan.send(f"⚠️ {after.mention} got whitelist role, but has no MC name set!")
                return
            
            success, response = await self.add_to_whitelist(guild, mc_name)
            if log_channel_id:
                chan = guild.get_channel(log_channel_id)
                if success:
                    await chan.send(f"✅ Added: `{mc_name}` for {after.mention}")
                else:
                    await chan.send(f"❌ Failed to add `{mc_name}`: {response}")
        
        # ROLE REMOVED -> REMOVE WHITELIST
        elif role in before.roles and role not in after.roles:
            mc_name = await self.config.member(after).mc_name()
            log_channel_id = await self.config.guild(guild).log_channel()
            
            if mc_name:
                success, response = await self.remove_from_whitelist(guild, mc_name)
                if log_channel_id:
                    chan = guild.get_channel(log_channel_id)
                    if success:
                        await chan.send(f"🚫 Removed: `{mc_name}` from {after.mention}")
                    else:
                        await chan.send(f"⚠️ Failed to remove `{mc_name}`: {response}")

async def setup(bot):
    await bot.add_cog(MCWhitelist(bot))
