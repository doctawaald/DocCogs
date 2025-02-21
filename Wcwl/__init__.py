from .mcwl import Mcwl

async def setup(bot):
    cog = Mcwl(bot)
    await cog.initialize()  # For proper initialization
    await bot.add_cog(cog)
