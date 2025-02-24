import discord
from redbot.core import commands, Config
from discord.ui import Select, View, Button
import re
import asyncio
import struct
from typing import Optional

class MCWhitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        self.config.register_guild(
            log_channel=None,
            whitelist_role=None,
            game_role=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            welcome_message="✅ You've been added to the Minecraft whitelist!\nYour username `{mc_name}` is now whitelisted.",
            status_message=None
        )
        
        self.config.register_member(
            mc_name=None
        )

    async def _rcon_command(self, host, port, password, command):
        try:
            reader, writer = await asyncio.open_connection(host, int(port))
            
            login_packet = b"\x00\x00\x00\x00"
            login_packet += struct.pack("<i", 3)
            login_packet += password.encode("utf-8") + b"\x00"
            login_packet += b"\x00\x00"
            
            writer.write(struct.pack("<i", len(login_packet)) + login_packet)
            await writer.drain()
            
            login_response_length = struct.unpack("<i", await reader.read(4))[0]
            await reader.read(login_response_length)
            
            command_packet = b"\x01\x00\x00\x00"
            command_packet += struct.pack("<i", 2)
            command_packet += command.encode("utf-8") + b"\x00"
            command_packet += b"\x00\x00"
            
            writer.write(struct.pack("<i", len(command_packet)) + command_packet)
            await writer.drain()
            
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
                return False, "RCON not configured"
            
            result = await self._rcon_command(
                config["rcon_host"],
                config["rcon_port"],
                config["rcon_password"],
                f"whitelist add {mc_name}"
            )
            if "Added" in result:
                return True, result
            return False, result
        except Exception as e:
            return False, str(e)

    async def remove_from_whitelist(self, guild, mc_name):
        try:
            config = await self.config.guild(guild).all()
            if not all([config["rcon_host"], config["rcon_port"], config["rcon_password"]]):
                return False, "RCON not configured"
            
            result = await self._rcon_command(
                config["rcon_host"],
                config["rcon_port"],
                config["rcon_password"],
                f"whitelist remove {mc_name}"
            )
            if "Removed" in result:
                return True, result
            return False, result
        except Exception as e:
            return False, str(e)

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
                embed.set_footer(text=f"Showing 25 of {len(members)} members")
            
            if interaction:
                await interaction.response.edit_message(embed=embed)
            elif ctx:
                return embed
            return embed

    @commands.admin()
    @commands.command()
    async def mcwlsetlog(self, ctx, channel: discord.TextChannel):
        """Set the logging channel"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"📝 Log channel set to {channel.mention}")

    @commands.admin()
    @commands.command()
    async def mcwlsetrole(self, ctx, role: discord.Role):
        """Set the whitelist role"""
        await self.config.guild(ctx.guild).whitelist_role.set(role.id)
        await ctx.send(f"🎮 Whitelist role set to {role.name}")

    @commands.admin()
    @commands.command()
    async def mcwlsetrcon(self, ctx, host: str, port: int, password: str):
        """Set RCON credentials"""
        await self.config.guild(ctx.guild).rcon_host.set(host)
        await self.config.guild(ctx.guild).rcon_port.set(port)
        await self.config.guild(ctx.guild).rcon_password.set(password)
        await ctx.send("🔑 RCON credentials updated")

    @commands.command()
    async def mcwlsetname(self, ctx, mc_name: str):
        """Set your Minecraft username"""
        if not 3 <= len(mc_name) <= 16:
            return await ctx.send("❌ Name must be between 3-16 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", mc_name):
            return await ctx.send("❌ Name can only contain letters, numbers and underscores")
        
        guild = ctx.guild
        member = ctx.author
        old_name = await self.config.member(member).mc_name()
        
        role_id = await self.config.guild(guild).whitelist_role()
        if role_id:
            role = guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role)
                await ctx.send("⚠️ Removed your whitelist role. Request an admin to re-add it after verification")
        
        await self.config.member(member).mc_name.set(mc_name)
        await ctx.send(f"✅ MC name set to `{mc_name}`")
        
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                if old_name:
                    msg = f"📛 {member.mention} changed MC name: `{old_name}` → `{mc_name}`"
                else:
                    msg = f"📛 {member.mention} set MC name to `{mc_name}`"
                await log_channel.send(msg)

    @commands.admin()
    @commands.command()
    async def mcwlremove(self, ctx, member: discord.Member):
        """Remove someone from the whitelist"""
        guild = ctx.guild
        role_id = await self.config.guild(guild).whitelist_role()
        
        if not role_id:
            return await ctx.send("❌ Whitelist role not set")
        
        role = guild.get_role(role_id)
        if not role:
            return await ctx.send("❌ Whitelist role not found")
        
        if role not in member.roles:
            return await ctx.send("❌ User doesn't have the whitelist role")
        
        mc_name = await self.config.member(member).mc_name()
        await member.remove_roles(role)
        await ctx.send(f"✅ Removed {member.mention} from whitelist")
        
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                msg = f"🚫 {member.mention} removed from whitelist"
                if mc_name:
                    msg += f" (MC: `{mc_name}`)"
                await log_channel.send(msg)

    @commands.admin()
    @commands.command()
    async def mcwladd(self, ctx, game_role: discord.Role):
        """Set the game role to manage"""
        await self.config.guild(ctx.guild).game_role.set(game_role.id)
        await ctx.send(f"🎮 Game role set to {game_role.name}")

    @commands.admin()
    @commands.command()
    async def mcwlmember(self, ctx):
        """Show whitelist status for game role members"""
        guild = ctx.guild
        status_message_id = await self.config.guild(guild).status_message()
        
        view = self.StatusView(self)
        embed = await view.update_embed(ctx=ctx)
        
        if status_message_id:
            try:
                message = await ctx.channel.fetch_message(status_message_id)
                await message.edit(embed=embed, view=view)
                return
            except:
                pass
        
        message = await ctx.send(embed=embed, view=view)
        await self.config.guild(guild).status_message.set(message.id)

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
            
            added = []
            failed = []
            welcome_msg = await self.cog.config.guild(self.guild).welcome_message()
            
            for member in selected_members:
                if not member:
                    continue
                try:
                    mc_name = await self.cog.config.member(member).mc_name()
                    await member.add_roles(self.whitelist_role)
                    
                    try:
                        if mc_name:
                            await member.send(welcome_msg.format(mc_name=mc_name))
                    except discord.Forbidden:
                        pass
                    
                    # Update Minecraft whitelist
                    if mc_name:
                        success, response = await self.cog.add_to_whitelist(self.guild, mc_name)
                    
                    added.append(f"{member.mention} (`{mc_name}`" if mc_name else f"{member.mention}")
                except Exception as e:
                    failed.append(f"{member.mention} ({str(e)})")
            
            # Update status embed
            status_view = self.cog.StatusView(self.cog)
            status_embed = await status_view.update_embed(interaction=interaction)
            
            await interaction.response.edit_message(
                content="✅ Processing complete!",
                embed=status_embed,
                view=status_view
            )

    class ProcessView(View):
        def __init__(self, cog, guild, whitelist_role, options):
            super().__init__()
            self.add_item(MCWhitelist.ProcessSelect(cog, guild, whitelist_role, options))

    @commands.admin()
    @commands.command()
    async def mcwlprocess(self, ctx):
        """Process game role members for whitelisting"""
        guild = ctx.guild
        game_role_id = await self.config.guild(guild).game_role()
        whitelist_role_id = await self.config.guild(guild).whitelist_role()
        
        if not game_role_id or not whitelist_role_id:
            return await ctx.send("❌ Configure roles first with `mcwladd` and `mcwlsetrole`")
        
        game_role = guild.get_role(game_role_id)
        whitelist_role = guild.get_role(whitelist_role_id)
        
        members = [m for m in game_role.members if not m.bot] if game_role else []
        if not members:
            return await ctx.send("❌ No members in the game role!")

        options = []
        for member in members[:25]:
            mc_name = await self.config.member(member).mc_name()
            label = f"{member.display_name}"[:25]
            desc = f"MC: {mc_name}"[:40] if mc_name else "No MC name"
            options.append(discord.SelectOption(
                label=label,
                value=str(member.id),
                description=desc,
                emoji="🟢" if mc_name else "🔴"
            ))

        view = self.ProcessView(self, guild, whitelist_role, options)
        embed = discord.Embed(
            title="Process Members for Whitelisting",
            description="Select members to add to the whitelist\n🟢 = MC name set\n🔴 = MC name missing",
            color=whitelist_role.color
        )
        await ctx.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        role_id = await self.config.guild(guild).whitelist_role()
        if not role_id:
            return
        
        role = guild.get_role(role_id)
        if not role:
            return
        
        if role not in before.roles and role in after.roles:
            mc_name = await self.config.member(after).mc_name()
            log_channel_id = await self.config.guild(guild).log_channel()
            
            if not mc_name:
                if log_channel_id:
                    log_channel = guild.get_channel(log_channel_id)
                    await log_channel.send(f"⚠️ {after.mention} got whitelist role but no MC name set")
                return
            
            success, response = await self.add_to_whitelist(guild, mc_name)
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if success:
                    await log_channel.send(f"✅ Added `{mc_name}` for {after.mention}")
                else:
                    await log_channel.send(f"❌ Failed to add {mc_name}: {response}")
        
        elif role in before.roles and role not in after.roles:
            mc_name = await self.config.member(after).mc_name()
            log_channel_id = await self.config.guild(guild).log_channel()
            
            if mc_name:
                success, response = await self.remove_from_whitelist(guild, mc_name)
                if log_channel_id:
                    log_channel = guild.get_channel(log_channel_id)
                    if success:
                        await log_channel.send(f"🚫 Removed `{mc_name}` from {after.mention}")
                    else:
                        await log_channel.send(f"⚠️ Failed to remove {mc_name}: {response}")

async def setup(bot):
    await bot.add_cog(MCWhitelist(bot))
