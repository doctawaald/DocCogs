from .counter import Counter

def setup(bot):
    bot.add_cog(Counter(bot))
