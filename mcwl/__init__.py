from .mc_wl import MCWhitelist

__red_end_user_data_statement__ = "This cog does not store user data."

async def setup(bot):
    """Load the MCWhitelist cog"""
    cog = MCWhitelist(bot)
    await bot.add_cog(cog)
