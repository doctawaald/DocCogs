from .BotDisconnect import BotDisconnect

async def setup(bot):
    await bot.add_cog(BotDisconnect(bot))
