from redbot.core import commands, Config
import discord
import asyncio

class MultiCounter(commands.Cog):
    """Multi-channel counter system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123459999)
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
                    return message
                except (discord.NotFound, discord.Forbidden):
                    pass
                    
            # Create new message if none exists or existing message was deleted
            message = await channel.send(f"**Current count:** {count}")
            await self.config.channel(channel).message_id.set(message.id)
            return message
            
        except Exception as e:
            print(f"Error updating counter: {str(e)}")

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def setcount(self, ctx, amount: int):
        """Set the counter for this channel"""
        await self.config.channel(ctx.channel).counter.set(amount)
        await self.update_counter_message(ctx.channel)
        msg = await ctx.send(f"✅ Counter set to {amount}!")
        await asyncio.sleep(5)
        await msg.delete()

    @commands.command()
    async def count(self, ctx):
        """Show current count for this channel"""
        count = await self.config.channel(ctx.channel).counter()
        await ctx.send(f"Current count: **{count}**")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot or message.content.strip() != "+1":
                return

            # Check if channel has been initialized
            message_id = await self.config.channel(message.channel).message_id()
            if not message_id:
                return

            # Increment counter
            current = await self.config.channel(message.channel).counter()
            new_count = current + 1
            await self.config.channel(message.channel).counter.set(new_count)
            
            # Update persistent message
            await self.update_counter_message(message.channel)
            
            # Send temporary confirmation
            temp_msg = await message.channel.send(
                f"✅ Count increased to {new_count}!",
                delete_after=5
            )
            await message.delete()
            
        except Exception as e:
            print(f"Error handling +1: {str(e)}")

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def initcounter(self, ctx):
        """Initialize a counter in this channel"""
        await self.update_counter_message(ctx.channel)
        msg = await ctx.send("✅ Counter initialized in this channel!")
        await asyncio.sleep(5)
        await msg.delete()

async def setup(bot):
    await bot.add_cog(MultiCounter(bot))
