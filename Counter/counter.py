from redbot.core import commands, Config
import discord
import asyncio

class Counter(commands.Cog):
    """Maintains a counter for +1 reactions in a specific channel"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123459999)
        self.config.register_global(
            counter=0,
            channel_id=None,
            message_id=None  # Stores ID of the counter message
        )

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def setcountchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where +1 commands will be counted"""
        await self.config.channel_id.set(channel.id)
        await ctx.send(f"+1 counting channel set to {channel.mention}")

    async def update_counter_message(self, channel, new_count):
        """Edits or creates the persistent counter message"""
        message_id = await self.config.message_id()
        
        try:
            if message_id:
                # Try to edit existing message
                message = await channel.fetch_message(message_id)
                await message.edit(content=f"**Total +1's: {new_count}**")
                return message
            else:
                # Create new message if none exists
                message = await channel.send(f"**Total +1's: {new_count}**")
                await self.config.message_id.set(message.id)
                return message
        except (discord.NotFound, discord.Forbidden):
            # Message was deleted or bot can't edit, create new one
            message = await channel.send(f"**Total +1's: {new_count}**")
            await self.config.message_id.set(message.id)
            return message

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.strip() != "+1":
            return

        channel_id = await self.config.channel_id()
        
        if channel_id and message.channel.id == channel_id:
            # Increment counter
            current_count = await self.config.counter()
            new_count = current_count + 1
            await self.config.counter.set(new_count)

            # Update persistent counter message
            channel = self.bot.get_channel(channel_id)
            try:
                await self.update_counter_message(channel, new_count)
            except discord.HTTPException as e:
                print(f"Error updating counter message: {e}")

            # Send and delete temporary confirmation
            try:
                temp_msg = await message.channel.send(f"✅ Counter updated to {new_count}!", delete_after=5)
            except discord.HTTPException as e:
                print(f"Error sending temporary message: {e}")

    @commands.command()
    async def showcounter(self, ctx):
        """Show the current +1 count"""
        count = await self.config.counter()
        await ctx.send(f"Current +1 count: **{count}**")

async def setup(bot):
    await bot.add_cog(Counter(bot))
