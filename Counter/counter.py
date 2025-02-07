import discord
from redbot.core import commands, Config
from redbot.core.commands import mod_or_permissions

class Counter(commands.Cog):
    """Channel-specific counter cog with summary"""
    
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

    @commands.command(name="init-counter")
    async def init_counter(self, ctx):
        """Initialize a counter in the current channel"""
        if await self.config.channel(ctx.channel).enabled():
            await ctx.send("✅ A counter is already active in this channel!")
            return
            
        await self.config.channel(ctx.channel).enabled.set(True)
        await self.config.channel(ctx.channel).count.set(0)
        await self.config.channel(ctx.channel).message_id.set(None)
        await ctx.send("🔢 Counter initialized in this channel!")
        await self.update_summary(ctx.guild)

    @commands.command(name="view-counter")
    async def view_counter(self, ctx):
        """View the current count"""
        if not await self.config.channel(ctx.channel).enabled():
            await ctx.send("❌ No counter is active in this channel!")
            return
            
        count = await self.config.channel(ctx.channel).count()
        await ctx.send(f"📊 Current count: **{count}**")

    @commands.command(name="edit-counter")
    @mod_or_permissions(manage_messages=True)
    async def edit_counter(self, ctx, number: int):
        """Edit the current count (Mod only)"""
        if not await self.config.channel(ctx.channel).enabled():
            await ctx.send("❌ No counter is active in this channel!")
            return
            
        await self.config.channel(ctx.channel).count.set(number)
        
        # Update count message
        channel = ctx.channel
        msg_id = await self.config.channel(channel).message_id()
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=f"📊 Current count: **{number}**")
            except:
                pass
                
        await ctx.send(f"✅ Count updated to **{number}**!")
        await self.update_summary(ctx.guild)

    @commands.command(name="remove-counter")
    @mod_or_permissions(manage_messages=True)
    async def remove_counter(self, ctx):
        """Remove the counter (Mod only)"""
        if not await self.config.channel(ctx.channel).enabled():
            await ctx.send("❌ No counter is active in this channel!")
            return
            
        await self.config.channel(ctx.channel).clear()
        await ctx.send("🗑️ Counter removed from this channel!")
        await self.update_summary(ctx.guild)

    @commands.command(name="set-summary")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_summary_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for counter summaries"""
        await self.config.guild(ctx.guild).summary_channel_id.set(channel.id)
        await ctx.send(f"📑 Summary channel set to {channel.mention}! Updating summary...")
        await self.update_summary(ctx.guild)

    async def update_summary(self, guild):
        """Updates the summary message with all channel counts"""
        try:
            summary_channel_id = await self.config.guild(guild).summary_channel_id()
            if not summary_channel_id:
                return
            
            summary_channel = guild.get_channel(summary_channel_id)
            if not summary_channel:
                return

            if not summary_channel.permissions_for(guild.me).send_messages:
                return

            # Get all enabled channels in this guild
            channels_data = []
            for channel in guild.channels:
                if isinstance(channel, discord.TextChannel):
                    data = await self.config.channel(channel).all()
                    if data['enabled']:
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
                channel_list = "\n".join(f"• {ch.name}: **{count}**" for ch, count in channels)
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
        except Exception as e:
            print(f"Error updating summary: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handles +1 messages in enabled channels"""
        try:
            if message.author.bot or message.content.strip() != "+1":
                return
                
            channel = message.channel
            config = self.config.channel(channel)
            
            if not await config.enabled():
                return

            # Check permissions
            if not channel.permissions_for(channel.guild.me).manage_messages:
                return

            try:
                await message.delete()
            except:
                return

            # Update count
            new_count = await config.count() + 1
            await config.count.set(new_count)

            # Update count message
            msg_id = await config.message_id()
            try:
                if msg_id:
                    msg = await channel.fetch_message(msg_id)
                    await msg.edit(content=f"📊 Current count: **{new_count}**")
                else:
                    msg = await channel.send(f"📊 Current count: **{new_count}**")
                    await config.message_id.set(msg.id)
            except:
                msg = await channel.send(f"📊 Current count: **{new_count}**")
                await config.message_id.set(msg.id)

            # Send confirmation embed
            embed = discord.Embed(
                description=f"✅ Count updated to **{new_count}**!",
                color=discord.Color.green()
            )
            confirm_msg = await channel.send(embed=embed)
            await confirm_msg.delete(delay=5)
            
            await self.update_summary(message.guild)
        except Exception as e:
            print(f"Error handling +1 message: {e}")

async def setup(bot):
    await bot.add_cog(Counter(bot))
