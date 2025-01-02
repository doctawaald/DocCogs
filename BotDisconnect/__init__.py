from .BotDisconnect import ManageOtherBots

async def setup(bot):
    await bot.add_cog(ManageOtherBots(bot))
