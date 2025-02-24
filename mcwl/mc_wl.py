import discord
from redbot.core import commands, Config
from discord.ui import Select, View
import re
import asyncio
import struct

class MCWhitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        self.config.register_guild(
            log_channel=None,
            whitelist_role=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            welcome_message="✅ You've been added to the Minecraft whitelist!\nYour username `{mc_name}` is now whitelisted."
        )
        
        self.config.register_member(
            mc_name=None
        )

    async def _rcon_command(self, host, port, password, command):
        try:
            reader, writer = await asyncio.open_connection(host, int(port))
            
            # Login packet
            login_packet = b"\x00\x00\x00\x00"  # Request ID
            login_packet += struct.pack("<i", 3)  # Login type
            login_packet += password.encode("utf-8") + b"\x00"
            login_packet += b"\x00\x00"  # Padding
            
            writer.write(struct.pack("<i", len(login_packet)) + login_packet)
            await writer.drain()
            
            # Login response
            login_response_length = struct.unpack("<i", await reader.read(4))[0]
            await reader.read(login_response_length)
            
            # Command packet
            command_packet = b"\x01\x00\x00\x00"  # Request ID
            command_packet += struct.pack("<i", 2)  # Command type
            command_packet += command.encode("utf-8") + b"\x00"
            command_packet += b"\x00\x00"  # Padding
            
            writer.write(struct.pack("<i", len(command_packet)) + command_packet)
            await writer.drain()
            
            # Command response
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
        """Select members with game role to whitelist"""
        guild = ctx.guild
        whitelist_role_id = await self.config.guild(guild).whitelist_role()
        
        if not whitelist_role_id:
            return await ctx.send("❌ Whitelist role not configured!")
        
        whitelist_role = guild.get_role(whitelist_role_id)
        if not whitelist_role:
            return await ctx.send("❌ Whitelist role not found!")
        
        members = [m for m in game_role.members if not m.bot]
        if not members:
            return await ctx.send("❌ No members with this role!")

        class MemberSelect(Select):
            def __init__(self, cog, members):
                self.cog = cog
                options = []
                for member in members[:25]:
                    mc_name = await self.cog.config.member(member).mc_name()
                    label = f"{member.display_name}"[:25]
                    desc = f"MC: {mc_name}"[:40] if mc_name else "No MC name"
                    options.append(discord.SelectOption(
                        label=label,
                        value=str(member.id),
                        description=desc,
                        emoji="🟢" if mc_name else "🔴"
                    ))
                super().__init__(
                    placeholder="Select members to whitelist...",
                    min_values=1,
                    max_values=len(options),
                    options=options
                )

            async def callback(self, interaction):
                selected_ids = [int(i) for i in self.values]
                selected_members = [guild.get_member(i) for i in selected_ids]
                
                added = []
                failed = []
                welcome_msg = await self.cog.config.guild(guild).welcome_message()
                
                for member in selected_members:
                    if not member:
                        continue
                    try:
                        mc_name = await self.cog.config.member(member).mc_name()
                        await member.add_roles(whitelist_role)
                        
                        # Send DM
                        try:
                            if mc_name:
                                await member.send(welcome_msg.format(mc_name=mc_name))
                        except discord.Forbidden:
                            pass
                        
                        added.append(f"{member.mention} (`{mc_name}`)" if mc_name else f"{member.mention}")
                    except Exception as e:
                        failed.append(f"{member.mention} ({str(e)})")
                
                embed = discord.Embed(title="Whitelist Update", color=0x00ff00)
                if added:
                    embed.add_field(name="✅ Added", value="\n".join(added), inline=False)
                if failed:
                    embed.add_field(name="❌ Failed", value="\n".join(failed), inline=False)
                
                await interaction.response.edit_message(embed=embed, view=None)

        view = View()
        view.add_item(MemberSelect(self, members))
        
        embed = discord.Embed(
            title=f"Whitelist Members from {game_role.name}",
            description="Select members to add to the whitelist\n🟢 = MC name set\n🔴 = MC name missing",
            color=game_role.color
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
        
        # Role added
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
        
        # Role removed
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
