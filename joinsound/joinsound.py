import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List

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
    """Join sound bij voice-joins, met per-user overrides, optionele self-serve en robuuste voice-handling."""

    default_guild = {
        # gedrag
        "enabled": True,
        "ignore_bots": True,
        "min_humans": 1,
        "prefer_user_overrides": True,

        # guild default sound
        "source": "url",          # 'url' of 'file'
        "url": "",
        "file_name": "",          # relatieve bestandsnaam in cog data dir

        # volume & limieten
        "volume": 0.6,            # fader; standaard 0.0–2.0, plafond via max_volume
        "max_volume": 2.0,        # 1.0–4.0 (volume-plafond per guild)
        "overdrive": False,       # ffmpeg pre-gain boven 2.0
        "limiter": True,          # alimiter bij overdrive

        # auto disconnect
        "auto_disconnect_s": 8,   # clamp 2–600s

        # upload policy
        "max_filesize_mb": 1,     # hard limit (MB)
        "max_duration_s": 6,      # 0=uit
        "enforce_duration": True, # ffprobe check

        # per-user: user_id(str) -> {"kind": "file"|"url", "path"|"url": str, "disabled": bool}
        "user_sounds": {},

        # self-serve (members)
        "selfserve_enabled": False,
        "selfserve_roles": [],       # allow-list role ids (leeg = iedereen)
        "selfserve_allow_url": True
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB005EE51)
        self.config.register_guild(**self.default_guild)
        self._guild_states: Dict[int, GuildState] = {}
        base = cog_data_path(self)
        base.mkdir(parents=True, exist_ok=True)
        (base / "users").mkdir(parents=True, exist_ok=True)

    # -------------------- state helper --------------------

    def _state(self, guild: discord.Guild) -> GuildState:
        gs = self._guild_states.get(guild.id)
        if not gs:
            gs = GuildState(lock=asyncio.Lock())
            self._guild_states[guild.id] = gs
        return gs

    # -------------------- self-serve runtime check --------------------

    async def _check_selfserve(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        cfg = await self.config.guild(ctx.guild).all()
        if not cfg.get("selfserve_enabled", False):
            await ctx.send("Self-serve staat uit. Vraag een admin om `joinsound selfserve enable`.")
            return False
        # Admins mogen altijd
        if ctx.author.guild_permissions.manage_guild:
            return True
        roles_cfg: List[int] = list(cfg.get("selfserve_roles", []) or [])
        if not roles_cfg:
            return True  # iedereen mag
        author_role_ids = {r.id for r in getattr(ctx.author, "roles", [])}
        if any(rid in author_role_ids for rid in roles_cfg):
            return True
        await ctx.send("Je hebt geen rol die self-serve toestaat.")
        return False

    # -------------------- admin root --------------------

    @commands.group(name="joinsound")
    @commands.admin_or_permissions(manage_guild=True)
    async def joinsound(self, ctx: commands.Context):
        """Beheer JoinSound instellingen."""
        pass

    @joinsound.command(name="enable")
    async def _enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("JoinSound ingeschakeld.")

    @joinsound.command(name="disable")
    async def _disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("JoinSound uitgeschakeld.")

    @joinsound.command(name="set")
    async def _set(self, ctx: commands.Context, key: str, *, value: str):
        key = key.lower()
        if key == "url":
            await self.config.guild(ctx.guild).url.set(value.strip())
            await self.config.guild(ctx.guild).source.set("url")
            return await ctx.send(f"URL ingesteld en bron op url gezet:\n`{value.strip()}`")

        if key in ("volume", "vol"):
            try:
                vol = float(value)
            except ValueError:
                return await ctx.send("Geef een getal.")
            cfg = await self.config.guild(ctx.guild).all()
            maxvol = float(cfg.get("max_volume", 2.0))
            vol = max(0.0, min(maxvol, vol))
            await self.config.guild(ctx.guild).volume.set(vol)
            return await ctx.send(f"Volume op {vol:.2f} gezet (plafond {maxvol:.1f}).")

        if key in ("maxvol", "max_volume"):
            try:
                mv = float(value)
            except ValueError:
                return await ctx.send("Geef een getal 1.0–4.0.")
            mv = max(1.0, min(4.0, mv))
            cur = await self.config.guild(ctx.guild).volume()
            if cur > mv:
                await self.config.guild(ctx.guild).volume.set(mv)
            await self.config.guild(ctx.guild).max_volume.set(mv)
            return await ctx.send(f"Max volume-plafond op {mv:.1f}x gezet.")

        if key in ("overdrive", "od"):
            v = value.strip().lower()
            val = v in {"1", "true", "yes", "on", "aan"}
            await self.config.guild(ctx.guild).overdrive.set(val)
            return await ctx.send(f"Overdrive {'aan' if val else 'uit'}.")

        if key in ("limiter", "limit"):
            v = value.strip().lower()
            val = v in {"1", "true", "yes", "on", "aan"}
            await self.config.guild(ctx.guild).limiter.set(val)
            return await ctx.send(f"Limiter {'aan' if val else 'uit'}.")

        if key in ("timeout", "autodisconnect", "auto_disconnect_s"):
            try:
                secs = int(value)
            except ValueError:
                return await ctx.send("Geef een geheel aantal seconden.")
            secs = max(2, min(600, secs))
            await self.config.guild(ctx.guild).auto_disconnect_s.set(secs)
            return await ctx.send(f"Auto-disconnect op {secs}s gezet.")

        if key == "source":
            v = value.strip().lower()
            if v not in {"url", "file"}:
                return await ctx.send("Bron moet url of file zijn.")
            await self.config.guild(ctx.guild).source.set(v)
            return await ctx.send(f"Bron gezet op {v}.")

        if key in ("maxsize", "max_filesize_mb"):
            try:
                mb = float(value)
            except ValueError:
                return await ctx.send("Geef MB (0.2–8).")
            mb = max(0.2, min(8.0, mb))
            await self.config.guild(ctx.guild).max_filesize_mb.set(mb)
            return await ctx.send(f"Max uploadgrootte op {mb:.1f} MB gezet.")

        if key in ("maxdur", "max_duration_s"):
            try:
                sec = int(value)
            except ValueError:
                return await ctx.send("Geef seconden (0=uit, anders 2–30).")
            if sec != 0:
                sec = max(2, min(30, sec))
            await self.config.guild(ctx.guild).max_duration_s.set(sec)
            return await ctx.send(f"Max duur op {sec}s gezet (0 = uit).")

        if key in ("enforcedur", "enforce_duration"):
            v = value.strip().lower()
            val = v in {"1", "true", "yes", "on", "aan"}
            await self.config.guild(ctx.guild).enforce_duration.set(val)
            return await ctx.send(f"Duurcontrole {'aan' if val else 'uit'}.")

        if key in ("preferuser", "prefer_user_overrides"):
            v = value.strip().lower()
            val = v in {"1", "true", "yes", "on", "aan"}
            await self.config.guild(ctx.guild).prefer_user_overrides.set(val)
            return await ctx.send(f"Per-user override {'heeft voorrang' if val else 'heeft geen voorrang'}.")

        await ctx.send(
            "Keys: url, volume, maxvol, overdrive on|off, limiter on|off, "
            "timeout, source (url|file), maxsize, maxdur, enforcedur, preferuser on|off."
        )

    # ---------- self-serve admin controls ----------

    @joinsound.group(name="selfserve")
    async def _selfserve(self, ctx: commands.Context):
        """Self-serve (members) beheren."""
        pass

    @_selfserve.command(name="enable")
    async def _ss_enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).selfserve_enabled.set(True)
        await ctx.send("Self-serve ingeschakeld. Leden kunnen nu `mysound` gebruiken.")

    @_selfserve.command(name="disable")
    async def _ss_disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).selfserve_enabled.set(False)
        await ctx.send("Self-serve uitgeschakeld.")

    @_selfserve.command(name="allowurl")
    async def _ss_allowurl(self, ctx: commands.Context, state: str):
        val = state.strip().lower() in {"1", "true", "yes", "on", "aan"}
        await self.config.guild(ctx.guild).selfserve_allow_url.set(val)
        await ctx.send(f"Self-serve URLs {'toegestaan' if val else 'geblokkeerd'}.")

    @_selfserve.command(name="addrole")
    async def _ss_addrole(self, ctx: commands.Context, role: discord.Role):
        async with self.config.guild(ctx.guild).selfserve_roles() as roles:
            if role.id not in roles:
                roles.append(role.id)
        await ctx.send(f"Rol toegevoegd aan self-serve allowlist: {role.name}.")

    @_selfserve.command(name="delrole")
    async def _ss_delrole(self, ctx: commands.Context, role: discord.Role):
        async with self.config.guild(ctx.guild).selfserve_roles() as roles:
            with contextlib.suppress(ValueError):
                roles.remove(role.id)
        await ctx.send(f"Rol verwijderd uit self-serve allowlist: {role.name}.")

    @_selfserve.command(name="status")
    async def _ss_status(self, ctx: commands.Context):
        cfg = await self.config.guild(ctx.guild).all()
        roles = cfg.get("selfserve_roles", []) or []
        names: List[str] = []
        for rid in roles:
            r = ctx.guild.get_role(int(rid))
            if r:
                names.append(r.name)
        await ctx.send(
            "Self-serve: {onoff} | URL: {url} | Rollen: {roles}".format(
                onoff="aan" if cfg.get("selfserve_enabled", False) else "uit",
                url="toegestaan" if cfg.get("selfserve_allow_url", True) else "geblokkeerd",
                roles=", ".join(names) if names else "(iedereen)",
            )
        )

    # ---------- top-level guild-default upload ----------

    @joinsound.command(name="upload")
    async def _upload(self, ctx: commands.Context, *, name: Optional[str] = None):
        """Upload een MP3/WAV/OGG/M4A/WEBM als guild-default joinsound (met bijlage)."""
        cfg = await self.config.guild(ctx.guild).all()
        if not ctx.message.attachments:
            return await ctx.send("Voeg een MP3/WAV/OGG/M4A/WEBM bijlage toe.")

        att = ctx.message.attachments[0]
        lower = att.filename.lower()
        if not lower.endswith(VALID_EXTS):
            return await ctx.send("Ondersteunde extensies: .mp3 .wav .ogg .m4a .webm")

        limit_bytes = int(float(cfg["max_filesize_mb"]) * 1024 * 1024)
        if att.size and att.size > limit_bytes:
            return await ctx.send(f"Bestand groter dan {cfg['max_filesize_mb']:.1f} MB.")

        desired = (name or att.filename).strip()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", desired)
        ext = Path(lower).suffix
        if not safe.endswith(ext):
            safe += ext

        data_dir: Path = cog_data_path(self)
        target = data_dir / safe
        try:
            await att.save(target)
        except Exception as e:
            return await ctx.send(f"Opslaan mislukt: {type(e).__name__}: {e}")

        max_s = int(cfg.get("max_duration_s", 0))
        if max_s and bool(cfg.get("enforce_duration", True)):
            dur = await self._probe_duration(target)
            if dur is None:
                await ctx.send("ffprobe niet gevonden of geen duur uitleesbaar; length-check overgeslagen.")
            elif dur > max_s + 0.15:
                with contextlib.suppress(Exception):
                    target.unlink(missing_ok=True)
                return await ctx.send(f"Clip te lang: {dur:.2f}s > {max_s}s.")

        await self.config.guild(ctx.guild).file_name.set(target.name)
        await self.config.guild(ctx.guild).source.set("file")
        await ctx.send(f"Guild-default opgeslagen als `{target.name}` en bron op file gezet. Test met: `[p]joinsound test`")

    # ---------- per-user (admin) ----------

    @joinsound.group(name="user")
    @commands.admin_or_permissions(manage_guild=True)
    async def _usergroup(self, ctx: commands.Context):
        """Per-user joinsounds beheren (admin)."""
        pass

    @_usergroup.command(name="url")
    async def _user_url(self, ctx: commands.Context, member: discord.Member, url: str):
        async with self.config.guild(ctx.guild).user_sounds() as m:
            prev = m.get(str(member.id))
            if prev and prev.get("kind") == "file":
                self._try_delete_rel(prev.get("path"))
            m[str(member.id)] = {"kind": "url", "url": url.strip(), "disabled": False}
        await ctx.send(f"Per-user URL ingesteld voor {member.mention}.")

    @_usergroup.command(name="upload")
    async def _user_upload(self, ctx: commands.Context, member: discord.Member, *, name: Optional[str] = None):
        await self._handle_member_upload(ctx, member, name)

    @_usergroup.command(name="disable")
    async def _user_disable(self, ctx: commands.Context, member: discord.Member, state: str):
        val = state.strip().lower() in {"1", "true", "yes", "on", "aan", "enable"}
        async with self.config.guild(ctx.guild).user_sounds() as m:
            us = m.get(str(member.id))
            if not us:
                return await ctx.send("Deze user heeft nog geen per-user sound.")
            us["disabled"] = not val
        await ctx.send(f"Per-user sound voor {member.mention} {'ingeschakeld' if val else 'uitgeschakeld'}.")

    @_usergroup.command(name="remove")
    async def _user_remove(self, ctx: commands.Context, member: discord.Member):
        async with self.config.guild(ctx.guild).user_sounds() as m:
            us = m.pop(str(member.id), None)
        if us and us.get("kind") == "file":
            self._try_delete_rel(us.get("path"))
        await ctx.send(f"Per-user sound voor {member.mention} verwijderd.")

    @_usergroup.command(name="show")
    async def _user_show(self, ctx: commands.Context, member: discord.Member):
        cfg = await self.config.guild(ctx.guild).all()
        us = (cfg.get("user_sounds") or {}).get(str(member.id))
        if not us:
            return await ctx.send(f"{member.mention} heeft geen per-user sound.")
        if us.get("kind") == "url":
            await ctx.send(f"{member.mention}: URL `{us.get('url','')}` | disabled={us.get('disabled', False)}")
        else:
            await ctx.send(f"{member.mention}: FILE `{us.get('path','')}` | disabled={us.get('disabled', False)}")

    @_usergroup.command(name="list")
    async def _user_list(self, ctx: commands.Context):
        cfg = await self.config.guild(ctx.guild).all()
        m = cfg.get("user_sounds") or {}
        if not m:
            return await ctx.send("Geen per-user sounds ingesteld.")
        entries = []
        for uid, us in list(m.items())[:50]:
            kind = us.get("kind")
            disabled = us.get("disabled", False)
            desc = us.get("url", "") if kind == "url" else us.get("path", "")
            entries.append(f"<@{uid}> — {kind.upper()} — {'DISABLED' if disabled else 'ENABLED'} — {desc}")
        await ctx.send("Per-user sounds:\n" + "\n".join(entries))

    @_usergroup.command(name="test")
    async def _user_test(self, ctx: commands.Context, member: discord.Member):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Je zit niet in een voicekanaal.")
        cfg = await self.config.guild(ctx.guild).all()
        override = self._resolve_user_override(ctx.guild, cfg, member)
        if not override:
            return await ctx.send("Geen (ingeschakelde) per-user sound voor deze user.")
        await ctx.message.add_reaction("🎧")
        await self._play_in_channel(ctx.guild, ctx.author.voice.channel, invoked=True, override=override)
        await ctx.message.add_reaction("✅")

    # ---------- self-serve member commands ----------

    @commands.group(name="mysound")
    @commands.guild_only()
    async def mysound(self, ctx: commands.Context):
        """Beheer je eigen joinsound (als self-serve aanstaat)."""
        pass

    @mysound.command(name="upload")
    @commands.guild_only()
    async def _me_upload(self, ctx: commands.Context, *, name: Optional[str] = None):
        if not await self._check_selfserve(ctx):
            return
        await self._handle_member_upload(ctx, ctx.author, name)

    @mysound.command(name="url")
    @commands.guild_only()
    async def _me_url(self, ctx: commands.Context, url: str):
        if not await self._check_selfserve(ctx):
            return
        cfg = await self.config.guild(ctx.guild).all()
        if not cfg.get("selfserve_allow_url", True):
            return await ctx.send("URL instellen is uitgeschakeld door een admin. Upload een bestand.")
        async with self.config.guild(ctx.guild).user_sounds() as m:
            prev = m.get(str(ctx.author.id))
            if prev and prev.get("kind") == "file":
                self._try_delete_rel(prev.get("path"))
            m[str(ctx.author.id)] = {"kind": "url", "url": url.strip(), "disabled": False}
        await ctx.send("Je persoonlijke URL is ingesteld.")

    @mysound.command(name="remove")
    @commands.guild_only()
    async def _me_remove(self, ctx: commands.Context):
        if not await self._check_selfserve(ctx):
            return
        async with self.config.guild(ctx.guild).user_sounds() as m:
            us = m.pop(str(ctx.author.id), None)
        if us and us.get("kind") == "file":
            self._try_delete_rel(us.get("path"))
        await ctx.send("Je persoonlijke sound is verwijderd.")

    @mysound.command(name="show")
    @commands.guild_only()
    async def _me_show(self, ctx: commands.Context):
        if not await self._check_selfserve(ctx):
            return
        cfg = await self.config.guild(ctx.guild).all()
        us = (cfg.get("user_sounds") or {}).get(str(ctx.author.id))
        if not us:
            return await ctx.send("Je hebt nog geen persoonlijke sound.")
        if us.get("kind") == "url":
            await ctx.send(f"Jouw sound: URL `{us.get('url','')}`")
        else:
            await ctx.send(f"Jouw sound: FILE `{us.get('path','')}`")

    @mysound.command(name="test")
    @commands.guild_only()
    async def _me_test(self, ctx: commands.Context):
        if not await self._check_selfserve(ctx):
            return
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Je zit niet in een voicekanaal.")
        cfg = await self.config.guild(ctx.guild).all()
        override = self._resolve_user_override(ctx.guild, cfg, ctx.author)
        if not override:
            return await ctx.send("Je hebt geen (ingeschakelde) persoonlijke sound.")
        await ctx.message.add_reaction("🎧")
        await self._play_in_channel(ctx.guild, ctx.author.voice.channel, invoked=True, override=override)
        await ctx.message.add_reaction("✅")

    # -------------------- shared upload handler --------------------

    async def _handle_member_upload(self, ctx: commands.Context, member: discord.Member, name: Optional[str]):
        cfg = await self.config.guild(ctx.guild).all()
        if not ctx.message.attachments:
            return await ctx.send("Voeg een MP3/WAV/OGG/M4A/WEBM bijlage toe.")
        att = ctx.message.attachments[0]
        lower = att.filename.lower()
        if not lower.endswith(VALID_EXTS):
            return await ctx.send("Ondersteunde extensies: .mp3 .wav .ogg .m4a .webm")

        limit_bytes = int(float(cfg["max_filesize_mb"]) * 1024 * 1024)
        if att.size and att.size > limit_bytes:
            return await ctx.send(f"Bestand groter dan {cfg['max_filesize_mb']:.1f} MB.")

        desired = (name or att.filename).strip()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", desired)
        ext = Path(lower).suffix
        if not safe.endswith(ext):
            safe += ext

        data_dir: Path = cog_data_path(self) / "users"
        data_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{member.id}_{safe}"
        target = data_dir / target_name

        try:
            await att.save(target)
        except Exception as e:
            return await ctx.send(f"Opslaan mislukt: {type(e).__name__}: {e}")

        max_s: int = int(cfg.get("max_duration_s", 0))
        if max_s and bool(cfg.get("enforce_duration", True)):
            dur = await self._probe_duration(target)
            if dur is None:
                await ctx.send("ffprobe niet gevonden of geen duur uitleesbaar; length-check overgeslagen.")
            elif dur > max_s + 0.15:
                with contextlib.suppress(Exception):
                    target.unlink(missing_ok=True)
                return await ctx.send(f"Clip te lang: {dur:.2f}s > {max_s}s. Trim korter en upload opnieuw.")

        rel_path = f"users/{target_name}"
        async with self.config.guild(ctx.guild).user_sounds() as m:
            prev = m.get(str(member.id))
            if prev and prev.get("kind") == "file":
                self._try_delete_rel(prev.get("path"))
            m[str(member.id)] = {"kind": "file", "path": rel_path, "disabled": False}
        await ctx.send(f"File ingesteld voor {'jou' if member == ctx.author else member.mention}: `{target.name}`")

    # -------------------- info & test --------------------

    @joinsound.command(name="file")
    async def _fileinfo(self, ctx: commands.Context):
        cfg = await self.config.guild(ctx.guild).all()
        await ctx.send(
            "Source: {src} | Volume: {vol:.2f} | MaxVol: {mv:.1f}x | Overdrive: {od} | Limiter: {lm}\n"
            "File: {fn} | URL: {url}\n"
            "Max size: {ms:.1f} MB | Max duur: {md}s | Prefer user: {pref} | Self-serve: {ss}".format(
                src=cfg["source"],
                vol=cfg["volume"],
                mv=cfg["max_volume"],
                od="aan" if cfg["overdrive"] else "uit",
                lm="aan" if cfg["limiter"] else "uit",
                fn=cfg["file_name"] or "(niet ingesteld)",
                url=cfg["url"] or "(niet ingesteld)",
                ms=cfg["max_filesize_mb"],
                md=cfg["max_duration_s"],
                pref="ja" if cfg.get("prefer_user_overrides", True) else "nee",
                ss="aan" if cfg.get("selfserve_enabled", False) else "uit",
            )
        )

    @joinsound.command(name="test")
    async def _test(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Je zit niet in een voicekanaal.")
        await ctx.message.add_reaction("🎧")
        await self._play_in_channel(ctx.guild, ctx.author.voice.channel, invoked=True)
        await ctx.message.add_reaction("✅")

    # -------------------- event handler --------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
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

        override = None
        if conf.get("prefer_user_overrides", True):
            override = self._resolve_user_override(guild, conf, member)
        if not override:
            override = self._resolve_guild_default(conf)
        if not override:
            return

        state = self._state(guild)
        async with state.lock:
            if after.channel is None or after.channel != joined_channel:
                return

            now = time.time()
            if now < state.connect_cooldown_until:
                return

            vc: Optional[discord.VoiceClient] = guild.voice_client
            if vc and vc.is_connected():
                if vc.channel.id == joined_channel.id:
                    if self._is_busy(vc):
                        return
                    played = await self._safe_play(vc, conf, override)
                    if played and not self._is_busy(vc):
                        await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])
                    return
                else:
                    if self._is_busy(vc):
                        return
                    await self._safe_disconnect(vc)

            state.session += 1
            vc = await self._connect_once(joined_channel)
            if not vc:
                state.connect_cooldown_until = time.time() + 3.0
                return

            state.last_connected_channel_id = joined_channel.id
            played = await self._safe_play(vc, conf, override)
            if played and not self._is_busy(vc):
                await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])

    # -------------------- voice helpers --------------------

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

    # -------------------- resolution --------------------

    def _resolve_user_override(self, guild: discord.Guild, cfg: dict, member: discord.Member) -> Optional[Tuple[str, str]]:
        us = (cfg.get("user_sounds") or {}).get(str(member.id))
        if not us or us.get("disabled"):
            return None
        kind = us.get("kind")
        if kind == "url":
            url = (us.get("url") or "").strip()
            return ("url", url) if url else None
        elif kind == "file":
            rel = (us.get("path") or "").strip()
            if not rel:
                return None
            p = cog_data_path(self) / rel
            return ("file", str(p)) if p.exists() else None
        return None

    def _resolve_guild_default(self, cfg: dict) -> Optional[Tuple[str, str]]:
        src = cfg.get("source", "url")
        if src == "url":
            url = (cfg.get("url") or "").strip()
            return ("url", url) if url else None
        else:
            fname = (cfg.get("file_name") or "").strip()
            if not fname:
                return None
            p = cog_data_path(self) / fname
            return ("file", str(p)) if p.exists() else None

    # -------------------- playback --------------------

    def _ffmpeg_filter(self, mult: float, limiter: bool) -> str:
        chain = []
        if abs(mult - 1.0) > 1e-3:
            chain.append(f"volume={mult:.3f}")
        if limiter:
            chain.append("alimiter=limit=0.97")
        return ",".join(chain) if chain else ""

    async def _safe_play(self, vc: discord.VoiceClient, conf: dict, override: Tuple[str, str]) -> bool:
        if self._is_busy(vc):
            return False

        desired = float(conf.get("volume", 0.6))
        maxvol = float(conf.get("max_volume", 2.0))
        overdrive = bool(conf.get("overdrive", False))
        limiter = bool(conf.get("limiter", True))

        v = max(0.0, min(maxvol, desired))
        ff_pre_gain = 1.0
        pcm_vol = v
        use_ff_filter = False
        if v > 2.0:
            if overdrive:
                ff_pre_gain = v / 2.0
                pcm_vol = 2.0
                use_ff_filter = True
            else:
                pcm_vol = v

        kind, val = override
        try:
            if kind == "file":
                if use_ff_filter:
                    ffopts = {"options": f'-vn -filter:a "{self._ffmpeg_filter(ff_pre_gain, limiter)}"'}
                else:
                    ffopts = {"options": "-vn"}
                pcm = discord.FFmpegPCMAudio(val, **ffopts)
            else:
                if use_ff_filter:
                    ffopts = {"before_options": FFMPEG_BEFORE, "options": f'-vn -filter:a "{self._ffmpeg_filter(ff_pre_gain, limiter)}"'}
                else:
                    ffopts = {"before_options": FFMPEG_BEFORE, "options": "-vn"}
                pcm = discord.FFmpegPCMAudio(val, **ffopts)

            source = discord.PCMVolumeTransformer(pcm)
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

    async def _play_in_channel(self, guild: discord.Guild, channel: discord.VoiceChannel, invoked: bool = False, override: Optional[Tuple[str, str]] = None):
        conf = await self.config.guild(guild).all()
        if not conf["enabled"] and not invoked:
            return

        ov = override or self._resolve_guild_default(conf)
        if not ov:
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

            played = await self._safe_play(vc, conf, ov)
            if played and not self._is_busy(vc):
                await self._schedule_auto_disconnect(state, vc, conf["auto_disconnect_s"])

    # -------------------- utilities --------------------

    def _try_delete_rel(self, rel: Optional[str]) -> None:
        if not rel:
            return
        p = cog_data_path(self) / rel
        with contextlib.suppress(Exception):
            if p.is_file():
                p.unlink()

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
