import discord
from redbot.core import commands
from discord.ext import tasks

class DisconnectBots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_vacant_channels.start()  # Start de taak om kanalen te controleren

    @tasks.loop(minutes=5)  # Controleer elke 5 minuten
    async def check_vacant_channels(self):
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                # Verkrijg alle leden met de opgegeven roleid
                members_with_role = [member for member in channel.members if '1188440119624085614' in [role.id for role in member.roles]]
                
                # Als er geen leden zijn met de juiste rol, laat de bots disconnecten
                if not members_with_role:
                    for bot in channel.members:
                        if bot.bot:  # Controleer of de member een bot is
                            await bot.move_to(None)  # Verplaats de bot uit het kanaal

    @commands.command()
    async def test_disconnect(self, ctx):
        """Test de disconnect functie door een kanaal te controleren."""
        for channel in ctx.guild.voice_channels:
            # Verkrijg alle leden met de opgegeven roleid
            members_with_role = [member for member in channel.members if '1188440119624085614' in [role.id for role in member.roles]]
            
            if not members_with_role:
                await ctx.send(f"Geen leden met de rol in kanaal {channel.name}. Bots zullen disconnecten.")
                for bot in channel.members:
                    if bot.bot:
                        await bot.move_to(None)
                break
        else:
            await ctx.send("Geen kanalen gevonden zonder leden met de opgegeven rol.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Bevestig dat de cog geladen is en start de check."""
        print(f"{self.bot.user} is klaar om bots te disconnecten!")
    
def setup(bot):
    bot.add_cog(DisconnectBots(bot))
