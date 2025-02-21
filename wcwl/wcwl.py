import json
import discord
from aiomcrcon import Client
from aiomcrcon.errors import IncorrectPasswordError, RCONConnectionError
from discord import Embed
from redbot.core import Config, commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu

_ = Translator("Mcwl", __file__)

@cog_i18n(_)
class Mcwl(commands.Cog):
    """Minecraft Whitelist Management Cog"""

    __version__ = "3.1.1"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=110320200153)
        
        default_guild = {
            "players": {},
            "path_to_server": "",
            "rcon": ("localhost", 25575, ""),
            "auto_role_id": None,
            "auto_whitelisted": {},
        }
        self.config.register_guild(**default_guild)
        self.config.register_global(notification=0)

    async def initialize(self):
        await self.bot.wait_until_red_ready()
        await self._send_pending_notifications()
        await self._initialize_auto_whitelist()

    def format_help_for_context(self, ctx: commands.Context) -> str:
        return f"{super().format_help_for_context(ctx)}\n\nVersion: {self.__version__}"

    async def red_delete_data_for_user(self, *, requester, user_id):
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            if str(user_id) in guild_data["players"]:
                async with self.config.guild(guild).players() as players:
                    del players[str(user_id)]
            
            if str(user_id) in guild_data["auto_whitelisted"]:
                async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                    del auto_whitelisted[str(user_id)]

    @commands.group(name="mcwl")
    async def mcwl(self, ctx):
        """Minecraft whitelist management commands"""

    @commands.guildowner()
    @mcwl.command()
    async def setup(self, ctx, host: str, port: int, password: str):
        """Set up RCON connection"""
        await ctx.message.delete()
        await self.config.guild(ctx.guild).rcon.set((host, port, password))
        
        try:
            async with Client(host, port, password) as client:
                response = await client.send_cmd("help")
                if not response[0]:
                    raise RCONConnectionError
        except RCONConnectionError:
            await ctx.send(_("❌ Connection failed. Check server IP/port."))
        except IncorrectPasswordError:
            await ctx.send(_("❌ Invalid RCON password."))
        else:
            await ctx.send(_("✅ Server connection configured successfully!"))

    @mcwl.command(name="add")
    async def whitelist_add(self, ctx, minecraft_name: str):
        """Add yourself to whitelist"""
        async with self.config.guild(ctx.guild).players() as players:
            if str(ctx.author.id) in players:
                await ctx.send(_("⚠️ You're already whitelisted! Use `{}mcwl remove` first.").format(ctx.clean_prefix))
                return
            
            players[str(ctx.author.id)] = {"name": minecraft_name}
        
        host, port, password = await self.config.guild(ctx.guild).rcon()
        async with Client(host, port, password) as client:
            response = await client.send_cmd(f"whitelist add {minecraft_name}")
        await ctx.send(f"`{response[0]}`")

    @mcwl.command()
    async def remove(self, ctx):
        """Remove yourself from whitelist"""
        async with self.config.guild(ctx.guild).players() as players:
            if str(ctx.author.id) not in players:
                await ctx.send(_("❌ You're not in the whitelist!"))
                return
            
            name = players[str(ctx.author.id)]["name"]
            del players[str(ctx.author.id)]
        
        host, port, password = await self.config.guild(ctx.guild).rcon()
        async with Client(host, port, password) as client:
            response = await client.send_cmd(f"whitelist remove {name}")
        await ctx.send(f"`{response[0]}`")

    @mcwl.command(name="list")
    async def whitelist_list(self, ctx):
        """Show current whitelist"""
        host, port, password = await self.config.guild(ctx.guild).rcon()
        async with Client(host, port, password) as client:
            response = await client.send_cmd("whitelist list")
        
        embed = Embed(title=_("Whitelisted Players"), description=response[0])
        await ctx.send(embed=embed)

    @commands.guildowner()
    @mcwl.command()
    async def autorole(self, ctx, role: discord.Role):
        """Set auto-whitelist role"""
        await self.config.guild(ctx.guild).auto_role_id.set(role.id)
        await ctx.send(_("✅ Auto-whitelist role set to: {}").format(role.mention))

    @commands.guildowner()
    @mcwl.command()
    async def removeautorole(self, ctx):
        """Remove auto-whitelist role"""
        await self.config.guild(ctx.guild).auto_role_id.set(None)
        await ctx.send(_("✅ Auto-whitelist role removed"))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Handle member leaving"""
        guild = member.guild
        config = await self.config.guild(guild).all()
        
        # Remove manual entry
        if str(member.id) in config["players"]:
            host, port, password = config["rcon"]
            async with Client(host, port, password) as client:
                await client.send_cmd(f"whitelist remove {config['players'][str(member.id)]['name']}")
            async with self.config.guild(guild).players() as players:
                del players[str(member.id)]
        
        # Remove auto entry
        if str(member.id) in config["auto_whitelisted"]:
            host, port, password = config["rcon"]
            async with Client(host, port, password) as client:
                await client.send_cmd(f"whitelist remove {config['auto_whitelisted'][str(member.id)]['name']}")
            async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                del auto_whitelisted[str(member.id)]

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Handle role changes"""
        guild = after.guild
        role_id = await self.config.guild(guild).auto_role_id()
        if not role_id:
            return
        
        auto_role = guild.get_role(role_id)
        if not auto_role:
            return
        
        host, port, password = await self.config.guild(guild).rcon()
        
        # Role added
        if auto_role not in before.roles and auto_role in after.roles:
            async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                if str(after.id) not in auto_whitelisted:
                    name = after.name
                    async with Client(host, port, password) as client:
                        await client.send_cmd(f"whitelist add {name}")
                    auto_whitelisted[str(after.id)] = {"name": name}
        
        # Role removed
        elif auto_role in before.roles and auto_role not in after.roles:
            async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                if str(after.id) in auto_whitelisted:
                    name = auto_whitelisted[str(after.id)]["name"]
                    async with Client(host, port, password) as client:
                        await client.send_cmd(f"whitelist remove {name}")
                    del auto_whitelisted[str(after.id)]

    async def _send_pending_notifications(self):
        if await self.config.notification() == 0:
            await self.bot.send_to_owners(
                "MCWL: Auto-whitelist feature initialized. Set up with `mcwl autorole`!"
            )
            await self.config.notification.set(1)

    async def _initialize_auto_whitelist(self):
        for guild in self.bot.guilds:
            role_id = await self.config.guild(guild).auto_role_id()
            if not role_id:
                continue
            
            auto_role = guild.get_role(role_id)
            if not auto_role:
                continue
            
            host, port, password = await self.config.guild(guild).rcon()
            async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                for member in auto_role.members:
                    if str(member.id) not in auto_whitelisted:
                        try:
                            async with Client(host, port, password) as client:
                                await client.send_cmd(f"whitelist add {member.name}")
                            auto_whitelisted[str(member.id)] = {"name": member.name}
                        except Exception as error:
                            print(f"Auto-whitelist init error: {error}")

async def setup(bot):
    cog = Mcwl(bot)
    await cog.initialize()
    bot.add_cog(cog)
