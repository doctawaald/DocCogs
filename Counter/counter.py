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
    async def setcountchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where +1 commands will be counted"""
        await self.config.channel_id.set(channel.id)
        await ctx.send(f"+1 counting channel set to {channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages and messages without +1
        if message.author.bot or message.content.strip() != "+1":
            return

        # Get configured channel ID
        channel_id = await self.config.channel_id()
        
        # Check if message is in the correct channel
        if channel_id and message.channel.id == channel_id:
            # Get current counter value
            current_count = await self.config.counter()
            
            # Increment counter
            new_count = current_count + 1
            await self.config.counter.set(new_count)
            
            # Send response
            await message.channel.send(f"Counter updated! Total +1's: **{new_count}**")

    @commands.command()
    async def showcounter(self, ctx):
        """Show the current +1 count"""
        count = await self.config.counter()
        await ctx.send(f"Total +1's counted: **{count}**")

async def setup(bot):
    await bot.add_cog(Counter(bot))
