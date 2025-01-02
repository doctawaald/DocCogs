from .BotDisconnect import ManageOtherBots  # Importeer de class met de juiste naam

async def setup(bot):
    await bot.add_cog(ManageOtherBots(bot))  # Zorg ervoor dat de cog goed wordt toegevoegd
