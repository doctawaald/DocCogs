import discord
from redbot.core import commands, Config
import re
import asyncio

class MCWhitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        self.config.register_guild(
            log_channel=None,
            whitelist_role=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None
        )
        
        self.config.register_member(
            mc_name=None
        )

    async def _rcon_command(self, host, port, password, command):
        try:
            reader, writer = await asyncio.open_connection(host, int(port))
            
            # Send login packet
            login_packet = (
                b"\x00\x00\x00\x00"  # Request ID (0 for login)
                + b"\x03"            # Login type (3)
                + password.encode("utf-8") + b"\x00"
                + b"\x00\x00"        # Two null bytes for padding
            )
            writer.write(len(login_packet).to_bytes(4, "little") + login_packet)
            await writer.drain()
            
            # Read login response
            response_length = int.from_bytes(await reader.read(4), "little")
            await reader.read(response_length)  # Discard login response
            
            # Send command packet
            command_packet = (
                b"\x01\x00\x00\x00"  # Request ID (1)
                + b"\x02"            # Command type (2)
                + command.encode("utf-8") + b"\x00"
                + b"\x00"            # Null byte padding
            )
            writer.write(len(command_packet).to_bytes(4, "little") + command_packet)
            await writer.drain()
            
            # Read command response
            response_length = int.from_bytes(await reader.read(4), "little")
            response = await reader.read(response_length)
            writer.close()
            
            return response[4:-2].decode("utf-8")  # Strip packet headers and null bytes
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
            return True, result
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
            return True, result
        except Exception as e:
            return False, str(e)

    @commands.admin()
    @commands.command()
    async def mcwlsetlog(self, ctx, channel: discord.TextChannel):
        """Set the logging channel"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}")

    @commands.admin()
    @commands.command()
    async def mcwlsetrole(self, ctx, role: discord.Role):
        """Set the whitelist role"""
        await self.config.guild(ctx.guild).whitelist_role.set(role.id)
        await ctx.send(f"Whitelist role set to {role.name}")

    @commands.admin()
    @commands.command()
    async def mcwlsetrcon(self, ctx, host: str, port: int, password: str):
        """Set RCON credentials"""
        await self.config.guild(ctx.guild).rcon_host.set(host)
        await self.config.guild(ctx.guild).rcon_port.set(port)
        await self.config.guild(ctx.guild).rcon_password.set(password)
        await ctx.send("RCON credentials updated")

    @commands.command()
    async def mcwlsetname(self, ctx, mc_name: str):
        """Set your Minecraft username"""
        if not 3 <= len(mc_name) <= 16:
            return await ctx.send("Name must be between 3-16 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", mc_name):
            return await ctx.send("Name can only contain letters, numbers and underscores")
        
        guild = ctx.guild
        member = ctx.author
        
        current_name = await self.config.member(member).mc_name()
        role_id = await self.config.guild(guild).whitelist_role()
        
        if role_id:
            role = guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role)
                await ctx.send("Removed your whitelist role. Please have an admin re-add it after name change")
        
        await self.config.member(member).mc_name.set(mc_name)
        await ctx.send(f"MC name set to `{mc_name}`")
        
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(f"{member.mention} changed their MC name to `{mc_name}`")

    @commands.admin()
    @commands.command()
    async def mcwlremove(self, ctx, member: discord.Member):
        """Remove someone from the whitelist"""
        guild = ctx.guild
        role_id = await self.config.guild(guild).whitelist_role()
        
        if not role_id:
            return await ctx.send("Whitelist role not set")
        
        role = guild.get_role(role_id)
        if not role:
            return await ctx.send("Whitelist role not found")
        
        if role not in member.roles:
            return await ctx.send("User doesn't have the whitelist role")
        
        mc_name = await self.config.member(member).mc_name()
        await member.remove_roles(role)
        await ctx.send(f"Removed {member.mention} from whitelist")
        
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                msg = f"{member.mention} was removed from whitelist"
                if mc_name:
                    msg += f" (MC name: `{mc_name}`)"
                await log_channel.send(msg)

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
                    await log_channel.send(f"{after.mention} received whitelist role but has no MC name set")
                return
            
            success, response = await self.add_to_whitelist(guild, mc_name)
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if success:
                    await log_channel.send(f"Added `{mc_name}` to whitelist for {after.mention}")
                else:
                    await log_channel.send(f"Failed to add {mc_name}: {response}")
        
        # Role removed
        elif role in before.roles and role not in after.roles:
            mc_name = await self.config.member(after).mc_name()
            log_channel_id = await self.config.guild(guild).log_channel()
            
            if mc_name:
                success, response = await self.remove_from_whitelist(guild, mc_name)
                if log_channel_id:
                    log_channel = guild.get_channel(log_channel_id)
                    if success:
                        await log_channel.send(f"Removed `{mc_name}` from whitelist for {after.mention}")
                    else:
                        await log_channel.send(f"Failed to remove {mc_name}: {response}")

async def setup(bot):
    await bot.add_cog(MCWhitelist(bot))
