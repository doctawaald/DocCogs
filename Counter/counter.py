from redbot.core import commands, Config
import discord

class Counter(commands.Cog):
    """Maintains a counter for +1 reactions in a specific channel"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123459999)
        self.config.register_global(
            counter=0,
            channel_id=None
        )

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def checkchannel(self, ctx):
        """Debug: Show configured channel ID"""
        channel_id = await self.config.channel_id()
        await ctx.send(f"Configured channel ID: {channel_id} (Current channel ID: {ctx.channel.id})")

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def setcountchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where +1 commands will be counted"""
        await self.config.channel_id.set(channel.id)
        await ctx.send(f"+1 counting channel set to {channel.mention} (ID: {channel.id})")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # Debug: Print basic message info
            print(f"Message received: {message.content} in {message.channel.id}")

            if message.author.bot:
                print("Ignored: Bot message")
                return

            if message.content.strip() != "+1":
                print(f"Ignored: Content '{message.content}' doesn't match +1")
                return

            channel_id = await self.config.channel_id()
            print(f"Configured channel ID: {channel_id} | Current channel ID: {message.channel.id}")

            if not channel_id:
                print("Ignored: No channel configured")
                return

            if message.channel.id != channel_id:
                print("Ignored: Wrong channel")
                return

            async with self.config.counter() as counter:
                counter += 1
                total = counter
                print(f"Counter updated to: {total}")

            await message.channel.send(f"Counter updated! Total +1's: **{total}**")
            
        except Exception as e:
            print(f"ERROR: {str(e)}")

    @commands.command()
    async def showcounter(self, ctx):
        """Show the current +1 count"""
        count = await self.config.counter()
        channel_id = await self.config.channel_id()
        await ctx.send(f"Total +1's counted: **{count}**\nConfigured channel ID: {channel_id}")

async def setup(bot):
    await bot.add_cog(Counter(bot))
