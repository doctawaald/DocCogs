from redbot.core import commands
from discord.ext import tasks
import discord

class DisconnectNoMembers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_activity.start()  # Start de taak die de activiteit in stemkanalen controleert

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Dit controleert of de member het kanaal verlaat
        if before.channel is not None and len(before.channel.members) == 0:
            # Controleer of er geen leden meer in het kanaal zitten met roleid 1188440119624085614
            if not any(m for m in before.channel.members if any(role.id == 1188440119624085614 for role in m.roles)):
                await before.channel.guild.voice_client.disconnect()

    @tasks.loop(minutes=1)
    async def check_voice_activity(self):
        # Dit kan elke minuut worden uitgevoerd om in de gaten te houden
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if len(vc.members) == 0 or not any(m for m in vc.members if any(role.id == 1188440119624085614 for role in m.roles)):
                    # Als het kanaal geen leden meer heeft met de opgegeven role, laat de bot het kanaal verlaten
                    if guild.voice_client:
                        await guild.voice_client.disconnect()

    @commands.command()
    async def test_disconnect(self, ctx):
        """Test de disconnect-functionaliteit."""
        for guild in self.bot.guilds:
            if guild.voice_client:
                await guild.voice_client.disconnect()
        await ctx.send("Bot disconnected from all voice channels.")

def setup(bot):
    bot.add_cog(DisconnectNoMembers(bot))
