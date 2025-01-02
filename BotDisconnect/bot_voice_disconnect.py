from redbot.core import commands, Config
from discord.ext import tasks
import discord

class BotVoiceDisconnect(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, 0)
        self.check_voice_activity.start()

    def cog_unload(self):
        self.check_voice_activity.cancel()

    @tasks.loop(seconds=60)  # Elke minuut checken
    async def check_voice_activity(self):
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                # Kijk of er bots in het kanaal zitten
                if any(member.bot for member in channel.members):
                    # Check of er leden met de rol ✅ Member aanwezig zijn
                    member_with_role = any(
                        member for member in channel.members if '✅ Member' in [role.name for role in member.roles]
                    )
                    if not member_with_role:
                        # Haal de bot uit het kanaal als er geen leden met de rol ✅ Member zijn
                        for bot_member in channel.members:
                            if bot_member.bot:
                                await bot_member.move_to(None)
                                await channel.send(f"{bot_member.name} is gedisconnect omdat er geen gebruikers met de rol ✅ Member meer zijn.")
    
    @commands.command(name="force_disconnect")
    @commands.has_permissions(administrator=True)
    async def force_disconnect(self, ctx):
        """Forceer de bot om te disconnecten uit een voice kanaal."""
        for channel in ctx.guild.voice_channels:
            for bot_member in channel.members:
                if bot_member.bot:
                    await bot_member.move_to(None)
                    await ctx.send(f"{bot_member.name} is gedisconnect.")
                    return
        await ctx.send("Er zijn geen bots om te disconnecten.")
