from .mc_wl import MCWhitelist

def setup(bot):
    bot.add_cog(MCWhitelist(bot))
