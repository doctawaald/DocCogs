import discord
from discord.ext import commands, tasks

class ManageOtherBots(commands.Cog):  # Zorg ervoor dat de class van 'commands.Cog' erft
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_channels.start()  # Start de taak die de kanalen elke 30 seconden controleert

    def cog_unload(self):
        self.check_voice_channels.cancel()  # Annuleer de taak bij het verwijderen van de cog

    @tasks.loop(seconds=30)  # Deze taak wordt elke 30 seconden uitgevoerd
    async def check_voice_channels(self):
        for guild in self.bot.guilds:  # Itereer door alle servers (guilds)
            for voice_channel in guild.voice_channels:  # Itereer door alle voice kanalen
                # Haal de rol "✅ Member" op uit de guild, vervang dit indien nodig
                target_role = discord.utils.get(guild.roles, name="✅ Member")
                role_members = [
                    member for member in voice_channel.members if target_role in member.roles
                ]

                # Als niemand met de rol in het kanaal is, disconnect alle bots behalve deze bot
                if not role_members:
                    for member in voice_channel.members:
                        if member.bot and member != self.bot.user:  # Controleer of het een andere bot is
                            try:
                                await member.move_to(None)  # Disconnect de bot uit het kanaal
                                print(f"Disconnected bot {member.name} from {voice_channel.name} in {guild.name}.")
                            except discord.Forbidden:
                                print(f"Geen toestemming om {member.name} te disconnecten.")
                            except discord.HTTPException as e:
                                print(f"Fout bij disconnecten van {member.name}: {e}")

    @check_voice_channels.before_loop
    async def before_check_voice_channels(self):
        await self.bot.wait_until_ready()  # Wacht totdat de bot is opgestart en klaar is

# Setup functie die door Redbot wordt gebruikt om de cog toe te voegen
async def setup(bot):
    await bot.add_cog(ManageOtherBots(bot))
