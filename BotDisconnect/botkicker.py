from redbot.core import commands, Config
import discord

class BotDisconnect(commands.Cog):
    """Auto-disconnect voice when no human users remain (bots don't count).

    - Safe disconnect: disables voice auto-reconnect before disconnecting.
    - Won't fight other cogs; only acts when the channel has 0 human members.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321)
        default_guild = {"enabled": True}
        self.config.register_guild(**default_guild)
        print("✅ BotDisconnect loaded (safe VC cleanup).")

    # Enable/disable toggle
    @commands.command()
    async def bdc_toggle(self, ctx):
        """Toggle BotDisconnect on/off (bot owner only)."""
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can toggle this.")
        enabled = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not enabled)
        await ctx.send(f"🧹 BotDisconnect is now {'enabled' if not enabled else 'disabled'}.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Only act when something meaningful changed
        if before.channel == after.channel:
            return

        guild = (before.channel or after.channel).guild if (before.channel or after.channel) else None
        if guild is None:
            return
        if not await self.config.guild(guild).enabled():
            return

        vc = guild.voice_client
        if not vc:
            return  # nothing to do

        # Target channel to inspect: the one the bot is (or was) in
        channel = vc.channel
        if not channel:
            return

        # Count humans (exclude bots)
        human_count = sum(1 for m in channel.members if not m.bot)

        # If no human users remain, cleanly disconnect
        if human_count == 0:
            try:
                if hasattr(vc, "_should_reconnect"):
                    vc._should_reconnect = False
                await vc.disconnect(force=True)
                print(f"🧹 BotDisconnect: disconnected from {channel} in guild {guild.id} (no humans).")
            except Exception as e:
                print(f"⚠️ BotDisconnect error: {e}")

