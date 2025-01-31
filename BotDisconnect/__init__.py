from .botkicker import BotKicker

async def setup(bot):
    await bot.add_cog(BotKicker(bot))
