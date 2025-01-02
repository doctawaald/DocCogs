import discord
from discord.ext import commands, tasks

class ManageOtherBots(commands.Cog):  # Zorg ervoor dat het van commands.Cog erft
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_channels.start()  # Start de taak die het kanaal controleert

    def cog_unload(self):
        self.check_voice_channels.cancel()  # Annuleer de taak wanneer de cog wordt unloaded

    @tasks.loop(seconds=30)  # Taak die elke 30 seconden draait
    async def check_voice_channels(self):
        for guild in self.bot.guilds:  # Itereer door de guilds van de bot
            for voice_channel in guild.voice_channels:  # Itereer door de voice kanalen
                # Zoek naar leden met de rol "✅ Member" (pas dit aan naar de juiste rolnaam)
                target_role = discord.utils.get(guild.roles, name="✅ Member")
                role_members = [
                    member for member in voice_channel.members if target_role in member.roles
                ]

                # Als er geen leden met de opgegeven rol in het kanaal zitten, disconnect bots
                if not role_members:
                    for member in voice_channel.members:
                        if member.bot and member != self.bot.user:  # Zorg ervoor dat het een andere bot is dan deze
                            try:
                                await member.move_to(None)  # Disconnect de bot
                                print(f"Disconnected bot {member.name} from {voice_channel.name} in {guild.name}.")
                            except discord.Forbidden:
                                print(f"Geen toestemming om {member.name} te disconnecten.")
                            except discord.HTTPException as e:
                                print(f"Fout bij disconnecten van {member.name}: {e}")

    @check_voice_channels.before_loop
    async def before_check_voice_channels(self):
        await self.bot.wait_until_ready()  # Zorg ervoor dat de bot klaar is voordat de taak start

# Setup functie die door Redbot wordt gebruikt om de cog toe te voegen
async def setup(bot):
    await bot.add_cog(ManageOtherBots(bot))
