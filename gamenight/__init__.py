from .gamenight import setup as cog_setup

__red_end_user_data_statement__ = "Deze cog slaat tijdelijk User IDs op in het geheugen voor het stemmen, maar bewaart niets permanent op schijf."

async def setup(bot):
    await cog_setup(bot)
