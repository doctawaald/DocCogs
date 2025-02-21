from .mcwl import MCWL

async def setup(bot):
    await bot.add_cog(MCWL(bot))
