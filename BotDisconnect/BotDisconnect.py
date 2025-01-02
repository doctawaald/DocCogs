import discord
from discord.ext import commands, tasks

class AutoDisconnect(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_channels.start()

    def cog_unload(self):
        self.check_voice_channels.cancel()

    @tasks.loop(seconds=30)  # Controleer elke 30 seconden
    async def check_voice_channels(self):
        for guild in self.bot.guilds:
            for voice_channel in guild.voice_channels:
                # Controleer of de bot in het voicekanaal zit
                if any(member.id == self.bot.user.id for member in voice_channel.members):
                    # Haal alle rollen van gebruikers in het kanaal
                    roles_in_channel = {
                        role for member in voice_channel.members for role in member.roles
                    }

                    # Controleer of een specifieke rol aanwezig is
                    target_role = discord.utils.get(guild.roles, name="✅ Member")
                    if target_role not in roles_in_channel:
                        # Disconnect de bot als de rol niet meer aanwezig is
                        vc = discord.utils.get(self.bot.voice_clients, guild=guild)
                        if vc and vc.channel == voice_channel:
                            await vc.disconnect()
                            print(f"Bot disconnected from {voice_channel.name} in {guild.name}.")

    @check_voice_channels.before_loop
    async def before_check_voice_channels(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(AutoDisconnect(bot))
