import discord
from redbot.core import commands, Config
from redbot.core.commands import mod_or_permissions

class Counter(commands.Cog):
    """Channel-specific counter cog with summary channel"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=12345, force_registration=True)
        self.config.register_channel(
            enabled=False,
            count=0,
            message_id=None
        )
        self.config.register_guild(
            summary_channel_id=None,
            summary_message_id=None
        )

    # [Previous commands remain unchanged, add these new commands and modifications]

    @commands.command(name="set-summary")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_summary_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for counter summaries"""
        await self.config.guild(ctx.guild).summary_channel_id.set(channel.id)
        await ctx.send(f"📑 Summary channel set to {channel.mention}! Updating summary...")
        await self.update_summary(ctx.guild)

    async def update_summary(self, guild):
        """Updates the summary message with all channel counts"""
        summary_channel_id = await self.config.guild(guild).summary_channel_id()
        if not summary_channel_id:
            return
        
        summary_channel = guild.get_channel(summary_channel_id)
        if not summary_channel:
            return

        if not summary_channel.permissions_for(guild.me).send_messages:
            return

        # Get all enabled channels and their counts
        all_channels = await self.config.all_channels()
        channels_data = []
        for channel_id, data in all_channels.items():
            channel = guild.get_channel(channel_id)
            if channel and data['enabled']:
                channels_data.append((channel, data['count']))

        # Organize by category
        categories = {}
        for channel, count in channels_data:
            category_name = channel.category.name if channel.category else "No Category"
            if category_name not in categories:
                categories[category_name] = []
            categories[category_name].append((channel, count))

        # Create embed
        embed = discord.Embed(title="Channel Counters Summary", color=discord.Color.blurple())
        for category, channels in sorted(categories.items()):
            channel_list = "\n".join(f"• {ch.mention}: **{count}**" for ch, count in channels)
            embed.add_field(name=category, value=channel_list, inline=False)

        # Update or create summary message
        summary_msg_id = await self.config.guild(guild).summary_message_id()
        try:
            if summary_msg_id:
                msg = await summary_channel.fetch_message(summary_msg_id)
                await msg.edit(embed=embed)
                return
        except:
            pass  # Message was deleted, create new one

        msg = await summary_channel.send(embed=embed)
        await self.config.guild(guild).summary_message_id.set(msg.id)

    # [Modify existing commands to call update_summary]

    @commands.Cog.listener()
    async def on_message(self, message):
        # [Existing on_message code...]
        
        # After updating count:
        await self.update_summary(message.guild)

    @commands.command(name="init-counter")
    async def init_counter(self, ctx):
        # [Existing init-counter code...]
        
        await self.update_summary(ctx.guild)

    @commands.command(name="edit-counter")
    @mod_or_permissions(manage_messages=True)
    async def edit_counter(self, ctx, number: int):
        # [Existing edit-counter code...]
        
        await self.update_summary(ctx.guild)

    @commands.command(name="remove-counter")
    @mod_or_permissions(manage_messages=True)
    async def remove_counter(self, ctx):
        # [Existing remove-counter code...]
        
        await self.update_summary(ctx.guild)

async def setup(bot):
    await bot.add_cog(Counter(bot))
