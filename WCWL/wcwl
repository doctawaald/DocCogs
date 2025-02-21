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
    __version__ = "1.0.0"

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nVersion: {self.__version__}"

    async def red_delete_data_for_user(self, *, requester, user_id):
        data = await self.config.all_guilds()
        for guild_id in data:
            guild_data = data[guild_id]
            if str(user_id) in guild_data["players"]:
                path = guild_data["path_to_server"]
                with open(path) as json_file:
                    file = json.load(json_file)
                for e in file:
                    if e["uuid"] == guild_data["players"][str(user_id)]["uuid"]:
                        del file[file.index(e)]
                        with open(f"{path}whitelist.json", "w") as json_file:
                            json.dump(file, json_file, indent=4)
                del guild_data["players"][str(user_id)]
                await self.config.guild_from_id(guild_id).players.set(guild_data["players"])
            if str(user_id) in guild_data["auto_whitelisted"]:
                del guild_data["auto_whitelisted"][str(user_id)]
                await self.config.guild_from_id(guild_id).auto_whitelisted.set(guild_data["auto_whitelisted"])

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=110320200153)
        default_guild = {
            "players": {},
            "path_to_server": "",
            "rcon": ("localhost", "25575", ""),
            "auto_role_id": None,
            "auto_whitelisted": {},
        }
        self.config.register_guild(**default_guild)
        self.config.register_global(notification=0)
        self.bot = bot

    async def initialize(self):
        await self.bot.wait_until_red_ready()
        await self._send_pending_owner_notifications(self.bot)
        for guild in self.bot.guilds:
            auto_role_id = await self.config.guild(guild).auto_role_id()
            if not auto_role_id:
                continue
            auto_role = guild.get_role(auto_role_id)
            if not auto_role:
                continue
            for member in guild.members:
                if auto_role in member.roles:
                    async with self.config.guild(guild).auto_whitelisted() as auto_whitelisted:
                        if str(member.id) not in auto_whitelisted:
                            minecraft_name = member.name
                            host, port, passw = await self.config.guild(guild).rcon()
                            try:
                                async with Client(host, port, passw) as c:
                                    await c.send_cmd(f"whitelist add {minecraft_name}")
                                auto_whitelisted[str(member.id)] = {"name": minecraft_name}
                            except Exception as e:
                                print(f"Error initializing auto-whitelist for {member.name}: {e}")

    async def _send_pending_owner_notifications(self, bot):
        if await self.config.notification() == 0:
            await bot.send_to_owners(
                "MCWL: Auto-whitelist role feature added. Set it up with `[p]mcwl autorole`."
            )
            await self.config.notification.set(1)

    # [Rest of the code remains the same except for the following changes:]

    @commands.group(name="mcwl")
    async def mcwl(self, ctx):
        """Minecraft whitelist management commands"""
        pass

    # Changed all @whitelister.command() decorators to @mcwl.command()
    @commands.guildowner()
    @mcwl.command()
    async def setup(self, ctx, host: str, port: int, *, password: str):
        """Set up MCWL"""
        # ... (rest of setup command remains same)

    @mcwl.command(name="add")
    async def hinzufuegen(self, ctx, name: str):
        # ... (rest of add command remains same)

    @commands.admin()
    @mcwl.command()
    async def addmin(self, ctx, name: str):
        # ... (rest of addmin command remains same)

    # [All other commands updated similarly...]

    @commands.guildowner()
    @mcwl.command()
    async def autorole(self, ctx, role: discord.Role):
        """Set auto-whitelist role"""
        # ... (rest of autorole command remains same)

    # [Updated remaining command decorators and references...]

    @commands.guildowner()
    @commands.command()
    async def mccommand(self, ctx, *, command):
        """Run a Minecraft server command"""
        # ... (rest of mccommand remains same)
