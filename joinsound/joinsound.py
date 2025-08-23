import asyncio
import contextlib
from dataclasses import dataclass
from typing import Dict, Optional

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = {"before_options": FFMPEG_BEFORE, "options": "-vn"}

@dataclass
class GuildState:
    lock: asyncio.Lock
    last_connected_channel_id: Optional[int] = None

class JoinSound(commands.Cog):
    """Speelt een join sound wanneer een user een voice channel joint."""

    default_guild = {
        "enabled": True,
        "url": "",
        "volume": 0.6,           # 0.0 - 1.0
        "auto_disconnect_s": 8,  # na zoveel seconden disconnecten als we alleen voor de join sound connecten
        "ignore_bots": True,
        "min_humans": 1          # speel alleen als er minstens 1 human joined (excl bots)
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB005EE51)
        self.config.register_guild(**self.default_guild)
        self._guild_states: Dict[int, GuildState] = {}

    def _state(self, guild: discord.Guild) -> GuildState:
        gs = self._guild_states.get(guild.id)
        if not gs:
            gs = GuildState(lock=asyncio.Lock())
            self._guild_states[guild.id] = gs
        return gs

    # ===================== Commands =====================

    @commands.group(name="joinsound")
    @commands.admin_or_permissions(manage_guild=True)
    async def joinsound(self, ctx: commands.Context):
        """Beheer JoinSound instellingen."""
        pass

    @joinsound.command(name="enable")
    async def _enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ JoinSound **ingeschakeld**.")

    @joinsound.command(name="disable")
    async def _disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("⏸️ JoinSound **uitgeschakeld**.")

    @joinsound.command(name="set")
    async def _set(
        self,
        ctx: commands.Context,
        key: str,
        *,
        value: str
    ):
        key = key.lower()
        if key == "url":
            await self.config.guild(ctx.guild).url.set(value.strip())
            await ctx.send(f"🔗 URL ingesteld op:\n`{value.strip()}`")
        elif key in ("volume", "vol"):
            try:
                vol = float(value)
            except ValueError:
                return await ctx.send("Geef een getal tussen 0.0 en 1.0.")
            vol = max(0.0, min(1.0, vol))
            await self.config.guild(ctx.guild).volume.set(vol)
            await ctx.send(f"🔊 Volume op **{vol:.2f}** gezet.")
        elif key in ("timeout", "autodisconnect", "auto_disconnect_s"):
            try:
                secs = int(value)
            except ValueError:
                return await ctx.send("Geef een geheel aantal seconden.")
            secs = max(2, min(120, secs))
            await self.config.guild(ctx.guild).auto_disconnect_s.set(secs)
            await ctx.send(f"⏱️ Auto‑disconnect op **{secs}s** gezet.")
        else:
            await ctx.send("Onbekende sleutel. Gebruik `url`, `volume`, of `timeout`.")

    @joinsound.command(name="test")
    async def _test(self, ctx: commands.Context):
        """Speel de joinsound nu in jouw voice channel (zonder te wachten op een join-event)."""
        url = await self.config.guild(ctx.guild).url()
        if not url:
            return await ctx.send("Stel eerst een URL in met `[p]joinsound set url <url>`.")
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Je zit niet in een voicekanaal.")
        await ctx.message.add_reaction("🎧")
        await self._play_in_channel(ctx.guild, ctx.author.voice.channel, invoked=True)
        await ctx.message.add_reaction("✅")

    # ===================== Event handler =====================

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # Ignore DMs or guild-less
        if member is None or member.guild is None:
            return
        guild: discord.Guild = member.guild

        # Settings
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return

        # Ignore bot joins if configured
        if conf["ignore_bots"] and member.bot:
            return

        # We only care about real joins (into a channel)
        joined_channel = after.channel
        left_channel = before.channel
        if joined_channel is None or joined_channel == left_channel:
            # No join, move to None, or move within the same channel
            return

        # Optional: only trigger when at least `min_humans` non-bots are present (incl. the joiner)
        if conf["min_humans"] > 0:
            humans = [m for m in joined_channel.members if not m.bot]
            if len(humans) < conf["min_humans"]:
                return

        # Serialize per guild to avoid race conditions (double connect / double play)
        state = self._state(guild)
        async with state.lock:
            # Re-check after lock (user might have already left)
            if after.channel is None or after.channel != joined_channel:
                return

            # If the bot is already connected and playing music elsewhere, skip!
            vc: Optional[discord.VoiceClient] = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id == joined_channel.id:
                    # Same channel: okay to play if not currently playing music
                    if self._is_busy(vc):
                        return
                    await self._safe_play(vc, conf)
                    return
                else:
                    # Different channel
                    if self._is_busy(vc):
                        # Busy (likely music) → do not yank it around.
                        return
                    # Idle elsewhere → disconnect first
                    await self._safe_disconnect(vc)

            # Connect (with backoff) only if user still in the channel
            vc = await self._connect_with_backoff(guild, joined_channel)
            if not vc:
                return  # couldn’t connect; bail quietly

            state.last_connected_channel_id = joined_channel.id

            played = await self._safe_play(vc, conf)
            # If we connected solely for the join sound, and we're not playing anything else, disconnect nicely
            if played and not self._is_busy(vc):
                await self._auto_disconnect_after(vc, conf["auto_disconnect_s"])

    # ===================== Voice helpers =====================

    def _is_busy(self, vc: discord.VoiceClient) -> bool:
        """True als er iets speelt of gepauzeerd is."""
        with contextlib.suppress(Exception):
            if vc.is_playing() or vc.is_paused():
                return True
        return False

    async def _connect_with_backoff(
        self, guild: discord.Guild, channel: discord.VoiceChannel
    ) -> Optional[discord.VoiceClient]:
        """Probeer 2x te connecten met kleine backoff. Abort als user al weg is."""
        delays = (0.0, 1.5)
        for idx, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            # Abort if no longer valid (channel empty of humans? we still allow if only bots? keep simple: continue)
            try:
                # channel might be stale; fetch fresh from cache is fine
                if channel is None:
                    return None
                vc = await channel.connect(reconnect=False, self_deaf=True)
                return vc
            except asyncio.CancelledError:
                return None
            except Exception:
                # swallow and try again
                if idx == len(delays) - 1:
                    return None
        return None

    async def _safe_play(self, vc: discord.VoiceClient, conf: dict) -> bool:
        """Speel de ingestelde URL; return True als er effectief gespeeld werd."""
        url: str = conf["url"]
        if not url:
            return False
        # Als er al iets speelt, doe niets
        if self._is_busy(vc):
            return False
        try:
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS))
            source.volume = float(conf["volume"])
        except Exception:
            # ffmpeg input fail
            return False

        done = asyncio.Event()

        def _after_play(err: Optional[Exception]):
            # We kunnen hier niet awaiten; zet alleen de flag.
            done.set()

        try:
            vc.play(source, after=_after_play)
        except Exception:
            return False

        # Wacht (met timeout) tot het klaar is of een error komt
        try:
            await asyncio.wait_for(done.wait(), timeout=15)
        except asyncio.TimeoutError:
            # Forceer stop als ffmpeg hangt
            with contextlib.suppress(Exception):
                vc.stop()
            return True
        return True

    async def _auto_disconnect_after(self, vc: discord.VoiceClient, seconds: int):
        seconds = max(2, min(120, int(seconds)))
        await asyncio.sleep(seconds)
        # Alleen disconnecten als we nog steeds idle zijn
        if not vc.is_connected():
            return
        if self._is_busy(vc):
            return
        await self._safe_disconnect(vc)

    async def _safe_disconnect(self, vc: discord.VoiceClient):
        with contextlib.suppress(Exception):
            if vc.is_playing():
                vc.stop()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(vc.disconnect(force=True), timeout=5)

    async def _play_in_channel(
        self, guild: discord.Guild, channel: discord.VoiceChannel, invoked: bool = False
    ):
        """Helper voor testcommand: forceer play in channel met dezelfde guards."""
        conf = await self.config.guild(guild).all()
        if not conf["enabled"] and not invoked:
            return

        state = self._state(guild)
        async with state.lock:
            vc = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    if self._is_busy(vc):
                        # Als bezig: niet forceren in test; geef liever netjes op
                        return
                    await self._safe_disconnect(vc)
            if not (vc and vc.is_connected()):
                vc = await self._connect_with_backoff(guild, channel)
                if not vc:
                    return
            played = await self._safe_play(vc, conf)
            if played and not self._is_busy(vc):
                await self._auto_disconnect_after(vc, conf["auto_disconnect_s"])
