from redbot.core import commands
from discord.ext import tasks
import discord

class DisconnectBots(commands.Cog):  # Verander 'Cog' naar 'commands.Cog'
    def __init__(self, bot):
        self.bot = bot
        self.check_bots.start()

    def cog_unload(self):
        self.check_bots.cancel()

    @tasks.loop(minutes=5)
    async def check_bots(self):
        for channel in self.bot.guilds[0].voice_channels:  # Verkrijgt de voice kanalen van de eerste guild
            # Haal alle leden op die in het kanaal zijn
            members_in_channel = [member for member in channel.members if member.guild_permissions.administrator is False]

            # Check als er geen leden met de specifieke roleid 1188440119624085614 meer zijn
            if not any(role.id == 1188440119624085614 for member in members_in_channel for role in member.roles):
                # Als er geen leden meer zijn, disconnect de bot uit het kanaal
                for bot in channel.guild.members:
                    if bot.bot:  # Controleer of het een bot is en als deze in het kanaal is
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
