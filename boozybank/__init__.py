from .boozybank import BoozyBank

async def setup(bot):
    await bot.add_cog(BoozyBank(bot))
