from .disconnect_bots import DisconnectBots

def setup(bot):
    bot.add_cog(DisconnectBots(bot))  # Geen 'await' hier, dit is synchroon
