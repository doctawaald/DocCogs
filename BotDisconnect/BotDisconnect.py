import discord
from discord.ext import commands, tasks

class ManageOtherBots(commands.Cog):  # Correcte erfstructuur van commands.Cog
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_channels.start()

    def cog_unload(self):
        self.check_voice_channels.cancel()

    @tasks.loop(seconds=30)
    async def check_voice_channels(self):
        for guild in self.bot.guilds:
            for voice_channel in guild.voice_channels:
                target_role = discord.utils.get(guild.roles, name="✅ Member")  # Pas dit aan naar de juiste rol
                role_members = [
                    member for member in voice_channel.members if target_role in member.roles
                ]

                if not role_members:
                    for member in voice_channel.members:
                        if member.bot and member != self.bot.user:
                            try:
                                await member.move_to(None)  # Disconnect de bot
                                print(f"Disconnected bot {member.name} from {voice_channel.name} in {guild.name}.")
                            except discord.Forbidden:
                                print(f"Geen toestemming om {member.name} te disconnecten.")
                            except discord.HTTPException as e:
                                print(f"Fout bij disconnecten van {member.name}: {e}")

    @check_voice_channels.before_loop
    async def before_check_voice_channels(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ManageOtherBots(bot))  # Voeg de cog correct toe
