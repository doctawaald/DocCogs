from redbot.core import commands
from discord.ext import tasks
import discord

class DisconnectBots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot_ready = False

    async def cog_load(self):
        """Zorg ervoor dat de taak pas start als de bot verbonden is."""
        if self.bot.is_ready():
            self.bot_ready = True
            self.check_bots.start()
        else:
            # Wacht tot de bot volledig verbonden is voordat je de taak start
            await self.bot.wait_until_ready()
            self.bot_ready = True
            self.check_bots.start()

    def cog_unload(self):
        """Stop de taak als de cog wordt verwijderd."""
        if self.bot_ready:
            self.check_bots.cancel()

    @tasks.loop(minutes=5)
    async def check_bots(self):
        """Loop die bots uit kanalen verwijdert waar geen leden met de rol aanwezig zijn."""
        for channel in self.bot.guilds[0].voice_channels:
            members_in_channel = [member for member in channel.members if member.guild_permissions.administrator is False]

            if not any(role.id == 1188440119624085614 for member in members_in_channel for role in member.roles):
                for bot in channel.guild.members:
                    if bot.bot:  # Als de bot in het kanaal is
                        if bot in channel.members:
                            await bot.move_to(None)  # Bot verlaat het kanaal

    @commands.command()
    async def force_disconnect(self, ctx):
        """Forces the disconnection of bots from voice channels with no users having roleid 1188440119624085614."""
        for channel in ctx.guild.voice_channels:
            members_in_channel = [member for member in channel.members if member.guild_permissions.administrator is False]

            if not any(role.id == 1188440119624085614 for member in members_in_channel for role in member.roles):
                for bot in channel.guild.members:
                    if bot.bot:  # Controleer of het een bot is en als deze in het kanaal is
                        if bot in channel.members:
                            await bot.move_to(None)  # Bot verlaat het kanaal
                await ctx.send(f"Bots disconnected from {channel.name}.")
