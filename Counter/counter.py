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
            new_message = None

            # Try to edit existing message
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(content=f"**Current count:** {count}")
                    return message
                except discord.NotFound:
                    print(f"Message {message_id} not found, creating new one")
                    new_message = await channel.send(f"**Current count:** {count}")
                except discord.Forbidden:
                    print(f"Missing permissions to edit message in {channel.name}")
                    return

            # Create new message if needed
            if not message_id or new_message:
                new_message = new_message or await channel.send(f"**Current count:** {count}")
                await self.config.channel(channel).message_id.set(new_message.id)
                return new_message

        except Exception as e:
            print(f"Error updating counter message: {str(e)}")

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
            async with self.config.channel(message.channel).counter() as counter:
                counter += 1
                new_count = counter

            # Update persistent message
            updated = await self.update_counter_message(message.channel)
            if updated:
                # Send temporary confirmation
                temp_msg = await message.channel.send(
                    f"✅ Count increased to {new_count}!",
                    delete_after=5
                )
                await message.delete()
            else:
                await message.channel.send("❌ Failed to update counter message!", delete_after=5)

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
