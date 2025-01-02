from .bot_voice_disconnect import BotVoiceDisconnect

async def setup(bot):
    await bot.add_cog(BotVoiceDisconnect(bot))
