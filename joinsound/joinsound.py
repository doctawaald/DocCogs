import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
VALID_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".webm")

@dataclass
class GuildState:
    lock: asyncio.Lock
    last_connected_channel_id: Optional[int] = None
    session: int = 0
    disconnect_task: Optional[asyncio.Task] = None
    connect_cooldown_until: float = 0.0  # epoch seconds

class JoinSound(commands.Cog):
    """Speelt een join sound wanneer een user een voice channel joint."""

    default_guild = {
        "enabled": True,
        "url": "",
        "volume": 0.6,            # 0.0–2.0 standaard; plafond is max_volume
        "max_volume": 2.0,        # 1.0–4.0 (plafond voor volume-setting)
        "overdrive": False,       # gebruik ffmpeg pre-gain als er >2.0 nodig is
        "limiter": True,          # alimiter na overdrive om clippen te beperken
        "auto_disconnect_s": 8,   # disconnect als we enkel voor joinsound joined zijn
        "ignore_bots": True,
        "min_humans": 1,
        "source": "url",          # 'url' of 'file'
        "file_name": "",
        "max_filesize_mb": 1,     # upload limiet
        "max_duration_s": 6,      # 0=uit
        "enforce_duration": True  # ffprobe check
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB005EE51)
        self.config.register_guild(**self.default_guild)
        self._guild_states: Dict[int, GuildState] = {}
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
    async def _set(self, ctx: commands.Context, key: str, *, value: str):
        key = key.lower()
        if key == "url":
            await self.config.guild(ctx.guild).url.set(value.strip())
            await self.config.guild(ctx.guild).source.set("url")
            await ctx.send(f"🔗 URL ingesteld en bron op **url** gezet:\n`{value.strip()}`")

        elif key in ("volume", "vol"):
            try:
                vol = float(value)
            except ValueError:
                return await ctx.send("Geef een getal.")
            cfg = await self.config.guild(ctx.guild).all()
            maxvol = float(cfg.get("max_volume", 2.0))
            vol = max(0.0, min(maxvol, vol))
            await self.config.guild(ctx.guild).volume.set(vol)
            await ctx.send(f"🔊 Volume (fader) op **{vol:.2f}** gezet. (Plafond {maxvol:.1f})")

        elif key in ("maxvol", "max_volume"):
            try:
                mv = float(value)
            except ValueError:
                return await ctx.send("Geef een getal **1.0–4.0**.")
            mv = max(1.0, min(4.0, mv))
            # als huidig volume erboven zit -> clamp het ook
            cur = await self.config.guild(ctx.guild).volume()
            if cur > mv:
                await self.config.guild(ctx.guild).volume.set(mv)
            await self.config.guild(ctx.guild).max_volume.set(mv)
            await ctx.send(f"🧢 Max volume-plafond op **{mv:.1f}x** gezet.")

        elif key in ("overdrive", "od"):
            v = value.strip().lower()
            val = v in {"1","true","yes","on","aan"}
            await self.config.guild(ctx.guild).overdrive.set(val)
            await ctx.send(f"⚡ Overdrive **{'aan' if val else 'uit'}**. (Pre-gain via FFmpeg voor >2.0)")

        elif key in ("limiter", "limit"):
            v = value.strip().lower()
            val = v in {"1","true","yes","on","aan"}
            await self.config.guild(ctx.guild).limiter.set(val)
            await ctx.send(f"🛡️ Limiter **{'aan' if val else 'uit'}**.")

        elif key in ("timeout", "autodisconnect", "auto_disconnect_s"):
            try:
                secs = int(value)
            except ValueError:
                return await ctx.send("Geef een geheel aantal seconden.")
            secs = max(2, min(600, secs))  # 2–600s (10 min)
            await self.config.guild(ctx.guild).auto_disconnect_s.set(secs)
            await ctx.send(f"⏱️ Auto-disconnect op **{secs}s** gezet.")

        elif key == "source":
            v = value.strip().lower()
            if v not in {"url", "file"}:
                return await ctx.send("Bron moet **url** of **file** zijn.")
            await self.config.guild(ctx.guild).source.set(v)
            await ctx.send(f"🎚️ Bron gezet op **{v}**.")

        elif key in ("maxsize", "max_filesize_mb"):
            try:
                mb = float(value)
            except ValueError:
                return await ctx.send("Geef MB (0.2–8).")
            mb = max(0.2, min(8.0, mb))
            await self.config.guild(ctx.guild).max_filesize_mb.set(mb)
            await ctx.send(f"📦 Max uploadgrootte op **{mb:.1f} MB** gezet.")

        elif key in ("maxdur", "max_duration_s"):
            try:
                sec = int(value)
            except ValueError:
                return await ctx.send("Geef seconden (0=uit, anders 2–30).")
            if sec != 0:
                sec = max(2, min(30, sec))
            await self.config.guild(ctx.guild).max_duration_s.set(sec)
            await ctx.send(f"⏱️ Max duur op **{sec}s** gezet (0 = uit).")

        elif key in ("enforcedur", "enforce_duration"):
            v = value.strip().lower()
            val = v in {"1","true","yes","on","aan"}
            await self.config.guild(ctx.guild).enforce_duration.set(val)
            await ctx.send(f"⏱️ Duurcontrole **{'aan' if val else 'uit'}**.")

        else:
            await ctx.send(
                "Keys: `url`, `volume`, `maxvol`, `overdrive on|off`, `limiter on|off`, "
                "`timeout`, `source (url|file)`, `maxsize`, `maxdur`, `enforcedur`."
            )

    @joinsound.command(name="upload")
    async def _upload(self, ctx: commands.Context, *, name: Optional[str] = None):
        """
        Upload een MP3/WAV/OGG/M4A/WEBM als joinsound.
        Gebruik: stuur een bijlage mee met dit commando.
        """
        cfg = await self.config.guild(ctx.guild).all()
        if not ctx.message.attachments:
            return await ctx.send("⚠️ Voeg een **MP3/WAV/OGG/M4A/WEBM** bijlage toe.")

        att = ctx.message.attachments[0]
        lower = att.filename.lower()
        if not lower.endswith(VALID_EXTS):
            return await ctx.send("❌ Ondersteunde extensies: **.mp3 .wav .ogg .m4a .webm**")

        # Hard size-limit
        limit_bytes = int(float(cfg["max_filesize_mb"]) * 1024 * 1024)
        if att.size and att.size > limit_bytes:
            return await ctx.send(f"❌ Bestand groter dan **{cfg['max_filesize_mb']:.1f} MB**.")

        desired = name.strip() if name else att.filename
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", desired)
        ext = Path(lower).suffix
        if not safe.endswith(ext):
            safe += ext

        data_dir: Path = cog_data_path(self)
        target = data_dir / safe

        try:
            await att.save(target)
        except Exception as e:
            return await ctx.send(f"❌ Opslaan mislukt: `{type(e).__name__}: {e}`")

        # Optional: duration check via ffprobe
        max_s: int = int(cfg.get("max_duration_s", 0))
        enforce = bool(cfg.get("enforce_duration", True))
        if max_s and enforce:
            dur = await self._probe_duration(target)
            if dur is None:
                await ctx.send("ℹ️ `ffprobe` niet gevonden of geen duur uitleesbaar; sla length-check over.")
            else:
                if dur > max_s + 0.15:
                    with contextlib.suppress(Exception):
                        target.unlink(missing_ok=True)
                    return await ctx.send(
                        f"❌ Clip te lang: **{dur:.2f}s** > **{max_s}s**. Trim korter en upload opnieuw."
                    )

        await self.config.guild(ctx.guild).file_name.set(target.name)
        await self.config.guild(ctx.guild).source.set("file")
        await ctx.send(f"✅ Opgeslagen als `{target.name}` en bron op **file** gezet.\n"
                       f"Test met: `[p]joinsound test`")

    @joinsound.command(name="file")
    async def _fileinfo(self, ctx: commands.Context):
        """Toon info over het huidige lokale bestand."""
        cfg = await self.config.guild(ctx.guild).all()
        await ctx.send(
            "🔎 Source: **{src}** | 🔊 Volume: **{vol:.2f}** | 🧢 MaxVol: **{mv:.1f}x**\n"
            "⚡ Overdrive: **{od}** | 🛡️ Limiter: **{lm}**\n"
            "📁 File: `{fn}` | 🔗 URL: `{url}`\n"
            "📦 Max size: **{ms:.1f} MB** | ⏱️ Max duur: **{md}s**".format(
                src=cfg["source"],
                vol=cfg["volume"],
                mv=cfg["max_volume"],
                od="aan" if cfg["overdrive"] else "uit",
                lm="aan" if cfg["limiter"] else "uit",
                fn=cfg["file_name"] or "(niet ingesteld)",
                url=cfg["url"] or "(niet ingesteld)",
                ms=cfg["max_filesize_mb"],
                md=cfg["max_duration_s"],
            )
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
            # Re-validate
            if after.channel is None or after.channel != joined_channel:
                return

            # Respect cooldown (bv. na 4006)
            now = time.time()
            if now < state.connect_cooldown_until:
                return

            vc: Optional[discord.VoiceClient] = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id == joined_channel.id:
                    if self._is_busy(vc):
                        return
                    played = await self._safe_play(vc, conf)
                    if played and not self._is_busy(vc):
                        await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])
                    return
                else:
                    if self._is_busy(vc):
                        return
                    await self._safe_disconnect(vc)

            # Nieuwe sessie
            state.session += 1
            vc = await self._connect_once(joined_channel)
            if not vc:
                state.connect_cooldown_until = time.time() + 3.0
                return

            state.last_connected_channel_id = joined_channel.id
            played = await self._safe_play(vc, conf)
            if played and not self._is_busy(vc):
                await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])

    # ===================== Voice helpers =====================

    def _is_busy(self, vc: discord.VoiceClient) -> bool:
        with contextlib.suppress(Exception):
            if vc.is_playing() or vc.is_paused():
                return True
        return False

    async def _connect_once(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        try:
            if channel is None:
                return None
            return await channel.connect(reconnect=False, self_deaf=True)
        except asyncio.CancelledError:
            return None
        except Exception:
            return None

    async def _schedule_auto_disconnect(self, state: GuildState, vc: discord.VoiceClient, seconds: int):
        if state.disconnect_task and not state.disconnect_task.done():
            state.disconnect_task.cancel()
            with contextlib.suppress(Exception):
                await state.disconnect_task

        seconds = max(2, min(600, int(seconds)))  # 2–600s
        session_id = state.session

        async def _runner():
            try:
                await asyncio.sleep(seconds)
                cur_vc = getattr(vc.guild, "voice_client", None)
                if session_id != state.session:
                    return
                if cur_vc is not vc:
                    return
                if not vc.is_connected():
                    return
                if self._is_busy(vc):
                    return
                await self._safe_disconnect(vc)
            except asyncio.CancelledError:
                return
            except Exception:
                return

        state.disconnect_task = asyncio.create_task(_runner())

    def _ffmpeg_filter(self, mult: float, limiter: bool) -> str:
        """
        Bouw de -filter:a string.
        mult: gain multiplier (1.0 = geen pre-gain)
        limiter: of we alimiter toepassen.
        """
        chain = []
        if abs(mult - 1.0) > 1e-3:
            chain.append(f"volume={mult:.3f}")
        if limiter:
            chain.append("alimiter=limit=0.97")  # mild limiter tegen clippen
        return ",".join(chain) if chain else ""

    async def _safe_play(self, vc: discord.VoiceClient, conf: dict) -> bool:
        if self._is_busy(vc):
            return False

        src = conf.get("source", "url")
        desired = float(conf.get("volume", 0.6))
        maxvol = float(conf.get("max_volume", 2.0))
        overdrive = bool(conf.get("overdrive", False))
        limiter = bool(conf.get("limiter", True))

        # Clamp naar plafond
        v = max(0.0, min(maxvol, desired))

        # Strategie:
        # - t/m 2.0: gebruik PCMVolumeTransformer (snappy, low-latency)
        # - boven 2.0: als overdrive aan staat -> ffmpeg pre-gain = v/2.0, PCM vol = 2.0
        #   anders: laat PCM boven 2.0 toe (kan harder clippen op client); we accepteren dat.
        ff_pre_gain = 1.0
        pcm_vol = v
        use_ff_filter = False
        if v > 2.0:
            if overdrive:
                ff_pre_gain = v / 2.0
                pcm_vol = 2.0
                use_ff_filter = True
            else:
                # Geen overdrive: direct PCMVolumeTransformer > 2.0 (kan clippen)
                pcm_vol = v

        try:
            ffopts = {}
            filter_str = self._ffmpeg_filter(ff_pre_gain, limiter) if use_ff_filter else ""
            if src == "file":
                path = cog_data_path(self) / (conf.get("file_name") or "")
                if not path.exists():
                    return False
                if filter_str:
                    ffopts = {"options": f'-vn -filter:a "{filter_str}"'}
                else:
                    ffopts = {"options": "-vn"}
                pcm = discord.FFmpegPCMAudio(str(path), **ffopts)
            else:
                url: str = conf.get("url") or ""
                if not url:
                    return False
                if filter_str:
                    ffopts = {"before_options": FFMPEG_BEFORE, "options": f'-vn -filter:a "{filter_str}"'}
                else:
                    ffopts = {"before_options": FFMPEG_BEFORE, "options": "-vn"}
                pcm = discord.FFmpegPCMAudio(url, **ffopts)

            source = discord.PCMVolumeTransformer(pcm)
            # Discord.py accepteert technisch >1.0; we ondersteunen tot max_volume (≤4.0)
            source.volume = pcm_vol
        except Exception:
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
            now = time.time()
            if now < state.connect_cooldown_until:
                return

            vc = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    if self._is_busy(vc):
                        return
                    await self._safe_disconnect(vc)

            state.session += 1

            if not (vc and vc.is_connected()):
                vc = await self._connect_once(channel)
                if not vc:
                    state.connect_cooldown_until = time.time() + 3.0
                    return

            played = await self._safe_play(vc, conf)
            if played and not self._is_busy(vc):
                await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])

    # ===================== Utilities =====================

    async def _probe_duration(self, path: Path) -> Optional[float]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                return None
            s = out.decode("utf-8", "ignore").strip()
            return float(s)
        except Exception:
            return None
