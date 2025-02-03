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
            
            # Try to edit existing message
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(content=f"**Current count:** {count}")
                    return True
                except discord.NotFound:
                    # Message was deleted, create new one
                    message = await channel.send(f"**Current count:** {count}")
                    await self.config.channel(channel).message_id.set(message.id)
                    return True
                except discord.Forbidden:
                    print(f"Missing permissions to edit messages in {channel.name}")
                    return False
            
            # Create new message if none exists
            message = await channel.send(f"**Current count:** {count}")
            await self.config.channel(channel).message_id.set(message.id)
            return True
            
        except Exception as e:
            print(f"Error updating counter message: {str(e)}")
            return False

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot:
                return

            # Only process +1 commands
            if message.content.strip() != "+1":
                return

            # Check if channel has been initialized
            message_id = await self.config.channel(message.channel).message_id()
            if not message_id:
                return

            # Atomic increment using Red's config system
            async with self.config.channel(message.channel).counter() as counter:
                counter += 1
                new_count = counter

            # Update counter message
            success = await self.update_counter_message(message.channel)
            
            if success:
                # Delete user's +1 message
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                
                # Send temporary confirmation
                temp_msg = await message.channel.send(
                    f"✅ Count increased to {new_count}!",
                    delete_after=5
                )
            else:
                await message.channel.send("❌ Failed to update counter!", delete_after=5)

        except Exception as e:
            print(f"Error handling +1: {str(e)}")

    # Keep other commands (setcount, count, initcounter) from previous version
    # ... [rest of the commands remain unchanged] ...

async def setup(bot):
    await bot.add_cog(MultiCounter(bot))
