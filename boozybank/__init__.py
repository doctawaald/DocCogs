from .boozybank import BoozyBank
async def setup(bot):
    cog = BoozyBank(bot)
    await bot.add_cog(cog)
