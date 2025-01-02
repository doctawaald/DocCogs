from discord.ext import commands, tasks
import discord

class BotVoiceDisconnect(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_activity.start()

    def cog_unload(self):
        self.check_voice_activity.cancel()

    @tasks.loop(seconds=60)  # Elke minuut checken
    async def check_voice_activity(self):
        role_id = 1188440119624085614  # Vervang dit door je daadwerkelijke RoleID
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                # Check of er bots in het kanaal zitten
                if any(member.bot for member in channel.members):
                    # Kijk of er nog gebruikers met de specifieke RoleID aanwezig zijn
                    member_with_role = any(
                        member for member in channel.members if role_id in [role.id for role in member.roles]
                    )
                    if not member_with_role:
                        # Disconnect alle bots als er geen gebruikers met de opgegeven rol zijn
                        for bot_member in channel.members:
                            if bot_member.bot:
                                try:
                                    await bot_member.move_to(None)  # Verplaats de bot naar 'None' (disconnect)
                                    await channel.send(f"{bot_member.name} is gedisconnect omdat er geen gebruikers met de rol ✅ Member meer zijn.")
                                except Exception as e:
                                    await channel.send(f"Er was een probleem met het disconnecten van {bot_member.name}: {str(e)}")

    @commands.command(name="force_disconnect")
    @commands.has_permissions(administrator=True)
    async def force_disconnect(self, ctx):
        """Forceer de bot om te disconnecten uit een voice kanaal."""
        role_id = 1188440119624085614  # Vervang dit door je daadwerkelijke RoleID
        bots_disconnected = False
        for channel in ctx.guild.voice_channels:
            # Loop door de leden in het kanaal en disconnect alle bots
            for bot_member in channel.members:
                if bot_member.bot:
                    # Controleer of er geen gebruikers met de specifieke rol zijn
                    member_with_role = any(
                        member for member in channel.members if role_id in [role.id for role in member.roles]
                    )
                    if not member_with_role:
                        try:
                            await bot_member.move_to(None)  # Verplaats de bot naar geen kanaal (disconnect)
                            bots_disconnected = True
                            await ctx.send(f"{bot_member.name} is gedisconnect uit kanaal {channel.name}.")
                        except Exception as e:
                            await ctx.send(f"Er is een fout opgetreden bij het disconnecten van {bot_member.name}: {str(e)}")
    
        if not bots_disconnected:
            await ctx.send("Er zijn geen bots om te disconnecten.")
        else:
            await ctx.send("Alle bots die gedisconnect moesten worden, zijn nu uit de kanalen gehaald.")
