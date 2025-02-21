from .mcwl import Mcwl

async def setup(bot):
    await bot.add_cog(Mcwl(bot))
