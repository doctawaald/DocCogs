from redbot.core import commands, Config
import discord

class Counter(commands.Cog):
    """A cog that counts "+1" messages in specific channels."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_channel(counter=0, message_id=None)

    @commands.command()
    async def setup_counter(self, ctx: commands.Context):
        """Set up the current channel for counting."""
        await self.config.channel(ctx.channel).counter.set(0)
        await self.config.channel(ctx.channel).message_id.set(None)
        await ctx.send(f"Counting setup complete for {ctx.channel.mention}.")

    @commands.command()
    async def set_counter(self, ctx: commands.Context, count: int):
        """Set the counter to a specific value in the current channel."""
        await self.config.channel(ctx.channel).counter.set(count)
        await self.update_count_message(ctx.channel)
        await ctx.send(f"Counter set to {count} in {ctx.channel.mention}.")

    @commands.command()
    async def show_counter(self, ctx: commands.Context):
        """Show the current counter value in this channel."""
        count = await self.config.channel(ctx.channel).counter()
        await ctx.send(f"Current count in {ctx.channel.mention}: {count}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the message is "+1"
        if message.content.strip() == "+1":
            await message.delete()

            channel = message.channel
            count = await self.config.channel(channel).counter()
            count += 1
            await self.config.channel(channel).counter.set(count)

            await self.update_count_message(channel)

    async def update_count_message(self, channel: discord.TextChannel):
        """Update or create the count message in the channel."""
        count = await self.config.channel(channel).counter()
        message_id = await self.config.channel(channel).message_id()

        # Try to fetch the previous message if it exists
        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                pass

        # Edit the existing message or send a new one
        if message:
            await message.edit(content=f"Current count: {count}")
        else:
            new_message = await channel.send(f"Current count: {count}")
            await self.config.channel(channel).message_id.set(new_message.id)

async def setup(bot):
    bot.add_cog(Counter(bot))
