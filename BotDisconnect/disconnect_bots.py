from redbot.core import commands
from discord.ext import tasks
import discord

class DisconnectBots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot_ready = False  # Variable to track if bot is ready

    async def cog_load(self):
        """Start de taak pas als de bot volledig is geladen."""
        await self.bot.wait_until_ready()  # Wacht tot de bot klaar is
        self.bot_ready = True
        self.check_bots.start()  # Start de taak pas als de bot klaar is

    def cog_unload(self):
        """Stop de taak als de cog wordt verwijderd."""
        if self.bot_ready:
            self.check_bots.cancel()  # Stop de taak wanneer de cog wordt unloaded

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
        """Forceert het disconnecten van bots uit voice kanalen zonder leden met de specifieke rol."""
        for channel in ctx.guild.voice_channels:
            members_in_channel = [member for member in channel.members if member.guild_permissions.administrator is False]

            if not any(role.id == 1188440119624085614 for member in members_in_channel for role in member.roles):
                for bot in channel.guild.members:
                    if bot.bot:  # Controleer of het een bot is en als deze in het kanaal is
                        if bot in channel.members:
                            await bot.move_to(None)  # Bot verlaat het kanaal
                await ctx.send(f"Bots disconnected from {channel.name}.")
