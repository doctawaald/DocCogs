import asyncio
import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_NET_OPTIONS = {"before_options": FFMPEG_BEFORE, "options": "-vn"}
FFMPEG_FILE_OPTIONS = {"options": "-vn"}  # lokaal bestand: reconnect flags niet nodig

VALID_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".webm")

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
        "min_humans": 1,         # speel alleen als er minstens 1 human joined (excl bots)
        "source": "url",         # 'url' of 'file'
        "file_name": ""          # relatieve bestandsnaam in cog data dir
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB005EE51)
        self.config.register_guild(**self.default_guild)
        self._guild_states: Dict[int, GuildState] = {}
        # zorg dat de datamap bestaat
        try:
            cog_data_path(self).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

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
            await self.config.guild(ctx.guild).source.set("url")
            await ctx.send(f"🔗 URL ingesteld en bron op **url** gezet:\n`{value.strip()}`")
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
            await ctx.send(f"⏱️ Auto-disconnect op **{secs}s** gezet.")
        elif key == "source":
            v = value.strip().lower()
            if v not in {"url", "file"}:
                return await ctx.send("Bron moet **url** of **file** zijn.")
            await self.config.guild(ctx.guild).source.set(v)
            await ctx.send(f"🎚️ Bron gezet op **{v}**.")
        else:
            await ctx.send("Onbekende sleutel. Gebruik `url`, `volume`, `timeout`, of `source` (url|file).")

    @joinsound.command(name="upload")
    async def _upload(self, ctx: commands.Context, *, name: Optional[str] = None):
        """
        Upload een MP3/WAV/OGG/M4A/WEBM als joinsound.
        Gebruik: stuur een bijlage mee met dit commando.
        """
        if not ctx.message.attachments:
            return await ctx.send("⚠️ Voeg een **MP3/WAV/OGG/M4A/WEBM** toe als bijlage bij je bericht.")

        att = ctx.message.attachments[0]
        lower = att.filename.lower()
        if not lower.endswith(VALID_EXTS):
            return await ctx.send("❌ Ondersteunde extensies: **.mp3 .wav .ogg .m4a .webm**")

        # optionele simpele limiet om te voorkomen dat er hele albums geüpload worden
        if att.size and att.size > 10 * 1024 * 1024:
            return await ctx.send("❌ Bestand is groter dan 10MB. Gebruik een kortere clip.")

        # Sanitize bestandsnaam
        desired = name.strip() if name else att.filename
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", desired)
        # forceer extensie uit attachment
        ext = Path(lower).suffix
        if not safe.endswith(ext):
            safe += ext

        data_dir: Path = cog_data_path(self)
        target = data_dir / safe

        try:
            await att.save(target)
        except Exception as e:
            return await ctx.send(f"❌ Opslaan mislukt: `{type(e).__name__}: {e}`")

        await self.config.guild(ctx.guild).file_name.set(target.name)
        await self.config.guild(ctx.guild).source.set("file")
        await ctx.send(f"✅ Bestaat opgeslagen als `{target.name}` en bron op **file** gezet.\n"
                       f"Test met: `[p]joinsound test`")

    @joinsound.command(name="file")
    async def _fileinfo(self, ctx: commands.Context):
        """Toon info over het huidige lokale bestand."""
        cfg = await self.config.guild(ctx.guild).all()
        src = cfg["source"]
        fname = cfg["file_name"] or "(niet ingesteld)"
        url = cfg["url"] or "(niet ingesteld)"
        await ctx.send(
            f"🔎 Source: **{src}**\n"
            f"📁 File: `{fname}`\n"
            f"🔗 URL: `{url}`"
        )

    @joinsound.command(name="test")
    async def _test(self, ctx: commands.Context):
        """Speel de joinsound nu in jouw voice channel (zonder te wachten op een join-event)."""
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
        if member is None or member.guild is None:
            return
        guild: discord.Guild = member.guild

        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return

        if conf["ignore_bots"] and member.bot:
            return

        joined_channel = after.channel
        left_channel = before.channel
        if joined_channel is None or joined_channel == left_channel:
            return

        if conf["min_humans"] > 0:
            humans = [m for m in joined_channel.members if not m.bot]
            if len(humans) < conf["min_humans"]:
                return

        state = self._state(guild)
        async with state.lock:
            if after.channel is None or after.channel != joined_channel:
                return

            vc: Optional[discord.VoiceClient] = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id == joined_channel.id:
                    if self._is_busy(vc):
                        return
                    await self._safe_play(vc, conf)
                    return
                else:
                    if self._is_busy(vc):
                        return
                    await self._safe_disconnect(vc)

            vc = await self._connect_with_backoff(guild, joined_channel)
            if not vc:
                return

            state.last_connected_channel_id = joined_channel.id

            played = await self._safe_play(vc, conf)
            if played and not self._is_busy(vc):
                await self._auto_disconnect_after(vc, conf["auto_disconnect_s"])

    # ===================== Voice helpers =====================

    def _is_busy(self, vc: discord.VoiceClient) -> bool:
        with contextlib.suppress(Exception):
            if vc.is_playing() or vc.is_paused():
                return True
        return False

    async def _connect_with_backoff(
        self, guild: discord.Guild, channel: discord.VoiceChannel
    ) -> Optional[discord.VoiceClient]:
        delays = (0.0, 1.5)
        for idx, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                if channel is None:
                    return None
                vc = await channel.connect(reconnect=False, self_deaf=True)
                return vc
            except asyncio.CancelledError:
                return None
            except Exception:
                if idx == len(delays) - 1:
                    return None
        return None

    async def _safe_play(self, vc: discord.VoiceClient, conf: dict) -> bool:
        src = conf.get("source", "url")
        try:
            if src == "file":
                fname = (conf.get("file_name") or "").strip()
                if not fname:
                    return False
                path = cog_data_path(self) / fname
                if not path.exists():
                    return False
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(str(path), **FFMPEG_FILE_OPTIONS)
                )
            else:
                url: str = conf.get("url") or ""
                if not url:
                    return False
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(url, **FFMPEG_NET_OPTIONS)
                )
            source.volume = float(conf.get("volume", 0.6))
        except Exception:
            return False

        if self._is_busy(vc):
            return False

        done = asyncio.Event()

        def _after_play(err: Optional[Exception]):
            done.set()

        try:
            vc.play(source, after=_after_play)
        except Exception:
            return False

        try:
            await asyncio.wait_for(done.wait(), timeout=30)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                vc.stop()
            return True
        return True

    async def _auto_disconnect_after(self, vc: discord.VoiceClient, seconds: int):
        seconds = max(2, min(120, int(seconds)))
        await asyncio.sleep(seconds)
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
        conf = await self.config.guild(guild).all()
        if not conf["enabled"] and not invoked:
            return

        state = self._state(guild)
        async with state.lock:
            vc = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    if self._is_busy(vc):
                        return
                    await self._safe_disconnect(vc)
            if not (vc and vc.is_connected()):
                vc = await self._connect_with_backoff(guild, channel)
                if not vc:
                    return
            played = await self._safe_play(vc, conf)
            if played and not self._is_busy(vc):
                await self._auto_disconnect_after(vc, conf["auto_disconnect_s"])
