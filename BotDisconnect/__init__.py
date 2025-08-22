from .joinsound import JoinSound

async def setup(bot):
    await bot.add_cog(JoinSound(bot))
