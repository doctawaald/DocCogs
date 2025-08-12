from .m00_core import BoozyBank

async def setup(bot):
    # Duidelijke console-log zodat je zeker weet dat setup bereikt wordt
    print("[BoozyBank] setup() called, adding cog...")
    await bot.add_cog(BoozyBank(bot))
    print("[BoozyBank] cog added.")
