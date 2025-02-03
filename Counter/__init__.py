def __init__(self, bot):
    self.bot = bot
    self.config = Config.get_conf(self, identifier=1234567890)
    self.config.register_channel(counter=0, message_id=None)

