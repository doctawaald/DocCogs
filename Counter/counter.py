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
        count = await self.config.channel(channel).counter()
        message_id = await self.config.channel(channel).message_id()
        
        try:
            if message_id:
                message = await channel.fetch_message(message_id)
                await message.edit(content=f"**Current count:** {count}")
                return message
            else:
                message = await channel.send(f"**Current count:** {count}")
                await self.config.channel(channel).message_id.set(message.id)
                return message
        except (discord.NotFound, discord.Forbidden):
            message = await channel.send(f"**Current count:** {count}")
            await self.config.channel(message.channel).message_id.set(message.id)
            return message

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
        if message.author.bot or message.content.strip() != "+1":
            return

        # Ignore messages in channels without counter setup
        channel_data = await self.config.channel(message.channel).all()
        if channel_data["message_id"] is None:
            return

        async with self.config.channel(message.channel).counter() as counter:
            counter += 1
            
        # Update persistent counter message
        await self.update_counter_message(message.channel)
        
        # Send and delete temporary confirmation
        try:
            temp_msg = await message.channel.send(f"✅ Count increased to {counter}!", delete_after=5)
            await message.delete()
        except discord.Forbidden:
            pass

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
