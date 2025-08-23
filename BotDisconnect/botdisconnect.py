from redbot.core import commands
import discord
import asyncio
import traceback


class BotDisconnect(commands.Cog):
    """Disconnect all bots if no humans are left in a VC."""

    def __init__(self, bot):
        self.bot = bot
        print("✅ BotDisconnect loaded (safe VC cleanup).")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        # We only care if someone leaves or moves
        if before.channel == after.channel:
            return

        # If a channel lost a member, check that channel
        channel = before.channel
        if channel is None:
            return

        # Quick settle: sometimes events fire in bursts
        await asyncio.sleep(1.0)

        humans = [m for m in channel.members if not m.bot]
        if humans:
            return  # Still at least one human

        # No humans left: disconnect bots
        print(f"🔌 No humans in {channel.name} → disconnecting all bots.")
        for bot_member in [m for m in channel.members if m.bot]:
            vc = bot_member.guild.voice_client
            if vc and vc.is_connected():
                try:
                    if hasattr(vc, "_should_reconnect"):
                        vc._should_reconnect = False
                    await vc.disconnect(force=True)
                    print(f"✅ Disconnected {bot_member.display_name} from {channel.name}")
                except Exception as e:
                    print(f"⚠️ Error disconnecting {bot_member.display_name}: {e}")
                    traceback.print_exc()
