from .wcwl import WCWL  # Matches uppercase class name

async def setup(bot):
    cog = WCWL(bot)  # Use uppercase class name
    await cog.initialize()
    await bot.add_cog(cog)
