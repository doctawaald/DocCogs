from redbot.core import commands, Config
import discord
import asyncio

class Counter(commands.Cog):
    """Multi-channel counter system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=234567899)
        self.config.register_channel(
            counter=0,
            message_id=None
        )

    async def update_counter_message(self, channel):
        """Updates or creates the counter message for a channel"""
        try:
            count = await self.config.channel(channel).counter()
            message_id = await self.config.channel(channel).message_id()
            
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(content=f"**Current count:** {count}")
                    return True
                except discord.NotFound:
                    pass  # Message was deleted
                
            # Create new message if needed
            message = await channel.send(f"**Current count:** {count}")
            await self.config.channel(channel).message_id.set(message.id)
            return True
            
        except Exception as e:
            print(f"Error updating counter: {str(e)}")
            return False

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def setcount(self, ctx, amount: int):
        """Set the counter for this channel"""
        await self.config.channel(ctx.channel).counter.set(amount)
        await self.update_counter_message(ctx.channel)
        msg = await ctx.send(f"✅ Counter set to {amount}!")
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command()
    async def count(self, ctx):
        """Show current count for this channel"""
        count = await self.config.channel(ctx.channel).counter()
        await ctx.send(f"Current count: **{count}**")

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def initcounter(self, ctx):
        """Initialize a counter in this channel"""
        await self.update_counter_message(ctx.channel)
        msg = await ctx.send("✅ Counter initialized!")
        await asyncio.sleep(3)
        await msg.delete()

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot or message.content.strip() != "+1":
                return

            # Check if channel has counter initialized
            if not await self.config.channel(message.channel).message_id():
                return

            # Atomic increment
            async with self.config.channel(message.channel).counter() as counter:
                counter += 1
                new_count = counter

            # Update display
            if await self.update_counter_message(message.channel):
                try:
                    await message.delete()
                    await message.channel.send(f"✅ Count: {new_count}", delete_after=3)
                except discord.Forbidden:
                    pass
                
        except Exception as e:
            print(f"Error: {str(e)}")

async def setup(bot):
    await bot.add_cog(Counter(bot))
