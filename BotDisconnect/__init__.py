class DisconnectNoMembers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_voice_activity.start()  # Start de taak die de activiteit in stemkanalen controleert
