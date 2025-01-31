from redbot.core import commands, Config
import discord

class BotKicker(commands.Cog):
    """Kicks all bots from voice channel when specific role user leaves"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "trigger_role_id": None
        }
        self.config.register_guild(**default_guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Check if user left a voice channel
        if before.channel is None or after.channel is not None:
            return
        
        guild = member.guild
        role_id = await self.config.guild(guild).trigger_role_id()
        
        # Check if role is configured
        if not role_id:
            return
        
        # Check if leaving member has the trigger role
        if not any(role.id == role_id for role in member.roles):
            return
        
        voice_channel = before.channel
        
        # Check if bot has permissions
        if not guild.me.guild_permissions.move_members:
            return
        
        # Disconnect all bots in the channel
        for voice_member in voice_channel.members:
            if voice_member.bot and voice_member != guild.me:
                try:
                    await voice_member.move_to(None)
                except discord.HTTPException:
                    pass
            elif voice_member.bot:
                try:
                    await voice_member.disconnect()
                except discord.HTTPException:
                    pass

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def botrole(self, ctx):
        """Configure the trigger role for bot kicking"""
        pass

    @botrole.command(name="set")
    async def set_role(self, ctx, role: discord.Role):
        """Set the role that triggers bot disconnection"""
        await self.config.guild(ctx.guild).trigger_role_id.set(role.id)
        await ctx.send(f"Trigger role set to {role.name}")

    @botrole.command(name="show")
    async def show_role(self, ctx):
        """Show current configured trigger role"""
        role_id = await self.config.guild(ctx.guild).trigger_role_id()
        if not role_id:
            await ctx.send("No trigger role configured!")
            return
        role = ctx.guild.get_role(role_id)
        if role:
            await ctx.send(f"Current trigger role: {role.name}")
        else:
            await ctx.send("Configured role not found! Please set a new one.")

async def setup(bot):
    await bot.add_cog(BotKicker(bot))
