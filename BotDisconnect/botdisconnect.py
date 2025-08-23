import asyncio
from contextlib import suppress
from typing import Optional, Set, Dict, Tuple, List

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red

DEFAULTS_GUILD = {
    "grace_seconds": 10,      # wachttijd na laatste non-bot user
    "enabled": True,
    "exclude_bot_ids": []     # bots die NIET automatisch gekickt worden
}

def chan_key(guild_id: int, channel_id: int) -> Tuple[int, int]:
    return (guild_id, channel_id)

class BotDisconnect(commands.Cog):
    """Disconnect alle bots wanneer er geen echte mensen meer in het kanaal zijn."""

    __version__ = "1.3.0"

    def __init__(self, bot: Red):
        self.bot: Red = bot
        self.config: Config = Config.get_conf(self, identifier=0xB077D15C0, force_registration=True)
        self.config.register_guild(**DEFAULTS_GUILD)

        # Debounce per (guild_id, channel_id)
        self._pending_tasks: Dict[Tuple[int, int], asyncio.Task] = {}
        # Periodieke failsafe loop
        self._loop_task: Optional[asyncio.Task] = self.bot.loop.create_task(self._periodic_scan())

    def cog_unload(self):
        if self._loop_task:
            self._loop_task.cancel()
        for t in list(self._pending_tasks.values()):
            t.cancel()
        self.bot.loop.create_task(self._disconnect_everywhere_on_unload())

    # ========== Commands ==========

    @commands.group(name="bdset", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset(self, ctx: commands.Context):
        """Instellingen voor BotDisconnect."""
        conf = await self.config.guild(ctx.guild).all()
        enabled = "aan" if conf["enabled"] else "uit"
        excl = conf.get("exclude_bot_ids", [])
        lines = [
            "**BotDisconnect**",
            f"- Status: **{enabled}**",
            f"- Wachttijd (grace): **{conf['grace_seconds']}s**",
            f"- Excludelijst: {', '.join(str(i) for i in excl) if excl else '(leeg)'}",
            "Subcommands: `bdset enable`, `bdset disable`, `bdset grace <seconden>`,",
            "`bdset exclude add <@bot|id>`, `bdset exclude remove <@bot|id>`, `bdset exclude list`"
        ]
        await ctx.send("\n".join(lines))

    @bdset.command(name="enable")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ BotDisconnect **ingeschakeld**.")

    @bdset.command(name="disable")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("⛔ BotDisconnect **uitgeschakeld**.")

    @bdset.command(name="grace")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_grace(self, ctx: commands.Context, seconds: int):
        seconds = max(0, min(300, seconds))
        await self.config.guild(ctx.guild).grace_seconds.set(seconds)
        await ctx.send(f"⏱️ Wachttijd ingesteld op **{seconds} seconden**.")

    @bdset.group(name="exclude", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_exclude(self, ctx: commands.Context):
        """Beheer de excludelijst (bot IDs die nooit gekickt worden)."""
        await ctx.send("Gebruik: `bdset exclude add <@bot|id>`, `bdset exclude remove <@bot|id>`, `bdset exclude list`")

    @bdset_exclude.command(name="add")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_exclude_add(self, ctx: commands.Context, target: discord.Member | int):
        bot_id = target.id if isinstance(target, discord.Member) else int(target)
        conf = self.config.guild(ctx.guild)
        data = await conf.exclude_bot_ids()
        if bot_id not in data:
            data.append(bot_id)
            await conf.exclude_bot_ids.set(data)
        await ctx.send(f"➕ Bot `{bot_id}` toegevoegd aan excludelijst.")

    @bdset_exclude.command(name="remove")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_exclude_remove(self, ctx: commands.Context, target: discord.Member | int):
        bot_id = target.id if isinstance(target, discord.Member) else int(target)
        conf = self.config.guild(ctx.guild)
        data = await conf.exclude_bot_ids()
        if bot_id in data:
            data.remove(bot_id)
            await conf.exclude_bot_ids.set(data)
            await ctx.send(f"➖ Bot `{bot_id}` verwijderd uit excludelijst.")
        else:
            await ctx.send("ℹ️ Die bot staat niet in de excludelijst.")

    @bdset_exclude.command(name="list")
    @checks.admin_or_permissions(manage_guild=True)
    async def bdset_exclude_list(self, ctx: commands.Context):
        data = await self.config.guild(ctx.guild).exclude_bot_ids()
        await ctx.send(f"📋 Excludelijst: {', '.join(map(str, data)) if data else '(leeg)'}")

    # ========== Events & core logic ==========

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # Bepaal welke kanalen geraakt zijn
        affected: Set[discord.VoiceChannel] = set()
        if before and before.channel and isinstance(before.channel, (discord.VoiceChannel, discord.StageChannel)):
            affected.add(before.channel)
        if after and after.channel and isinstance(after.channel, (discord.VoiceChannel, discord.StageChannel)):
            affected.add(after.channel)

        for ch in affected:
            await self._schedule_channel_check(ch)

    async def _schedule_channel_check(self, channel: discord.abc.Connectable):
        """Debounce: plan een check voor dit kanaal op basis van guild grace."""
        if not hasattr(channel, "guild"):
            return
        guild = channel.guild
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return

        key = chan_key(guild.id, channel.id)
        if key in self._pending_tasks:
            self._pending_tasks[key].cancel()

        async def runner():
            try:
                await asyncio.sleep(conf["grace_seconds"])
                await self._check_channel_and_disconnect(channel)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            finally:
                self._pending_tasks.pop(key, None)

        self._pending_tasks[key] = self.bot.loop.create_task(runner())

    async def _check_channel_and_disconnect(self, channel: discord.abc.Connectable):
        """Als in het kanaal geen non-bot members meer zijn: disconnect deze bot én andere bots."""
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return

        guild: discord.Guild = channel.guild
        conf = await self.config.guild(guild).all()

        members = list(channel.members)
        humans_present = any(m for m in members if not m.bot)
        if humans_present or not conf["enabled"]:
            return

        # 1) Disconnect deze bot (robuust)
        my_vc: Optional[discord.VoiceClient] = discord.utils.get(self.bot.voice_clients, guild=guild)
        if my_vc and my_vc.channel and my_vc.channel.id == channel.id:
            await self._safe_disconnect(my_vc)

        # 2) Disconnect andere bots in dit kanaal (ook bots zonder deze cog)
        #    Vereist 'Move Members' perm. We proberen per-bot move_to(None).
        #    Respecteer excludelijst.
        exclude_ids: List[int] = conf.get("exclude_bot_ids", []) or []
        me: discord.Member = guild.me  # type: ignore
        can_move = me.guild_permissions.move_members

        if not can_move:
            return  # Geen permissie; dan laten we het hierbij.

        for m in members:
            if not m.bot:
                continue
            if m.id == self.bot.user.id:
                continue  # onszelf al afgehandeld
            if m.id in exclude_ids:
                continue
            with suppress(Exception):
                # Dit disconnect andere bots proper (equivalent van mod/kick from VC)
                await asyncio.wait_for(m.move_to(None), timeout=5)

    async def _safe_disconnect(self, vc: discord.VoiceClient):
        """Betrouwbare disconnect met fallbacks om hangende sessies te voorkomen."""
        with suppress(Exception):
            if vc.is_playing():
                vc.stop()

        try:
            await asyncio.wait_for(vc.disconnect(force=True), timeout=5)
            return
        except (asyncio.TimeoutError, discord.ConnectionClosed, discord.GatewayNotFound, discord.HTTPException):
            pass
        except Exception:
            pass

        with suppress(Exception):
            await asyncio.wait_for(vc.guild.change_voice_state(channel=None), timeout=5)

        await asyncio.sleep(0.5)
        with suppress(Exception):
            await asyncio.wait_for(vc.disconnect(force=True), timeout=5)

    async def _periodic_scan(self):
        """Failsafe: scan elke 90s alle voicekanalen en ruim op."""
        try:
            while True:
                await asyncio.sleep(90)
                for guild in self.bot.guilds:
                    conf = await self.config.guild(guild).all()
                    if not conf["enabled"]:
                        continue
                    for ch in guild.channels:
                        if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                            await self._check_channel_and_disconnect(ch)
        except asyncio.CancelledError:
            pass

    async def _disconnect_everywhere_on_unload(self):
        """Opruiming bij unload: probeer actieve VC's proper te sluiten."""
        tasks = []
        for vc in list(self.bot.voice_clients):
            tasks.append(asyncio.create_task(self._safe_disconnect(vc)))
        if tasks:
            with suppress(Exception):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
