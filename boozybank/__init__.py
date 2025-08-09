from .m00_core import BoozyBank

async def setup(bot):
    await bot.add_cog(BoozyBank(bot))


