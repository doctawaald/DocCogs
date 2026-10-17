from redbot.core import commands, Config
from collections import defaultdict
from contextlib import asynccontextmanager
import discord
from discord.ext import tasks
import re
import difflib
import asyncio
import random
import time
import logging
import json
from datetime import datetime, timedelta, timezone

from .games import GAMES  # Separate game list

log = logging.getLogger("red.gamenight")


class ConfigBusyError(RuntimeError):
    """The shared Config lock did not become available in time."""


class RSVPView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        custom_id="gn_rsvp_select",
        placeholder="Wanneer ben je online?",
        options=[
            discord.SelectOption(label="Vroeger (voor 20:00)", emoji="🕰️", value="Earlier"),
            discord.SelectOption(label="20:00", emoji="🕗", value="20:00"),
            discord.SelectOption(label="20:30", emoji="🕣", value="20:30"),
            discord.SelectOption(label="21:00", emoji="🕘", value="21:00"),
            discord.SelectOption(label="21:30", emoji="🕤", value="21:30"),
            discord.SelectOption(label="22:00", emoji="🕙", value="22:00"),
            discord.SelectOption(label="22:30", emoji="🕥", value="22:30"),
            discord.SelectOption(label="23:00", emoji="🕚", value="23:00"),
            discord.SelectOption(label="Later (na 23:00)", emoji="🦉", value="Later"),
            discord.SelectOption(label="Vandaag niet aanwezig", emoji="❌", value="No")
        ]
    )
    async def rsvp_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            # Select instances are shared; use this click's own payload.
            val = interaction.data["values"][0]
            # Determine the correct cog to handle this interaction.
            # If this view is a zombie from a previous reload, forward to the active cog.
            active_cog = self.cog.bot.get_cog("GameNight")
            if active_cog is not None:
                await active_cog.handle_rsvp(interaction, val)
            else:
                # No active GameNight cog found — respond gracefully
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ De GameNight-plugin is niet geladen.", ephemeral=True
                    )
        except discord.errors.InteractionResponded:
            pass  # Already responded — safe to ignore
        except Exception as e:
            # Catch-all: make sure Discord always gets a response to avoid "interaction failed"
            log.exception("RSVP callback failed (interaction=%s)", interaction.id)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Er ging iets mis. Probeer het opnieuw.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "⚠️ Er ging iets mis. Probeer het opnieuw.", ephemeral=True
                    )
            except Exception:
                pass  # Nothing more we can do

class CloseVoteView(discord.ui.View):
    """A view with a green 'Close Vote' button, attached to the 'all votes in' notification."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        custom_id="gn_close_vote_btn",
        label="Stemming sluiten",
        style=discord.ButtonStyle.success,
        emoji="🛑"
    )
    async def close_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Acknowledge before permission checks, message edits or Config work.
            # Complete this private response on every branch below.
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            # Redbot admin roles need not have Discord's Administrator permission.
            # Accept both, plus bot owners, like the command's admin requirement.
            bot = self.cog.bot
            allowed = (
                interaction.user.guild_permissions.administrator
                or await bot.is_owner(interaction.user)
                or await bot.is_admin(interaction.user)
            )
            if not allowed:
                await interaction.edit_original_response(content="⛔ Alleen boteigenaars, ingestelde Redbot-beheerders of Discord-beheerders kunnen de stemming sluiten.")
                return

            active_cog = self.cog.bot.get_cog("GameNight")
            if active_cog is None:
                await interaction.edit_original_response(content="⚠️ De GameNight-plugin is niet geladen.")
                return

            if not active_cog.is_open:
                await interaction.edit_original_response(content="⛔ De stemming is al gesloten.")
                return

            # Disable the button on the message
            button.disabled = True
            button.label = "Stemming gesloten ✅"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            # Close the vote using shared logic
            await active_cog._do_close_vote(interaction.channel)
            await interaction.edit_original_response(content="✅ De stemming is gesloten. De uitslag staat in het kanaal.")

        except discord.errors.InteractionResponded:
            pass
        except Exception as e:
            log.exception("Close Vote interaction failed (interaction=%s)", interaction.id)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Er ging iets mis. Probeer het opnieuw.", ephemeral=True
                    )
                else:
                    await interaction.edit_original_response(
                        content="⚠️ Er ging iets mis bij het sluiten. Controleer het kanaal en het botlog voordat je het opnieuw probeert."
                    )
            except Exception:
                pass

# Build alias lookup once at import time
GAME_ALIASES = {name: data["aliases"] for name, data in GAMES.items()}

# Player count threshold for the "too many players" warning
TOO_MANY_PLAYERS_THRESHOLD = 4

# RSVP time values that can be parsed into a clock time (HH:MM format)
# "Earlier" and "Later" are special and get mapped to fixed fallback times.
RSVP_TIME_MAP = {
    "Earlier": "20:00",
    "20:00": "20:00",
    "20:30": "20:30",
    "21:00": "21:00",
    "21:30": "21:30",
    "22:00": "22:00",
    "22:30": "22:30",
    "23:00": "23:00",
    "Later": "23:30",
}


class GameNight(commands.Cog):
    """Organiseer gameavonden met geheime stemmen, aanwezigheden en statistieken."""

    def __init__(self, bot):
        self.bot = bot
        self.votes = {}
        self.is_open = False

        # For the RSVP check
        self.vote_message = None
        self.vote_channel = None
        self.all_voted_notified = False
        self.too_many_notified = False  # Track whether the "too many players" warning has been sent
        self._all_voted_msg: discord.Message | None = None
        self._close_lock = asyncio.Lock()
        self._rsvp_embed_lock = asyncio.Lock()
        self._penalty_warning_lock = asyncio.Lock()
        self._completion_lock = asyncio.Lock()

        # Message tracking for auto-cleanup
        self.tracked_messages: list[discord.Message] = []
        self._cleanup_task: asyncio.Task | None = None
        self._auto_close_task: asyncio.Task | None = None
        self._reminder_task: asyncio.Task | None = None
        self._smart_reminder_task: asyncio.Task | None = None
        self._smart_reminder_sent: bool = False

        # Auto-open tracking
        self._auto_opened_date: str | None = None  # ISO date string e.g. "2026-06-20"

        # Database setup
        self.config = Config.get_conf(self, identifier=847372839210)
        default_global = {
            "game_wins": {},
            "total_sessions": 0,
            "weighted_mode": True,
            "veto_mode": False,
            "is_open": False,
            "votes": {},
            # Keep this a scalar in Redbot Config; results are JSON strings.
            "session_result": None,
            "skip_history": {},
            "skip_limit": 2,
            "session_skip_users": [],
            "penalty_session": None,
            "penalty_warnings": {},
            "penalty_warning_message": None,
            "penalty_notice_message": None,
            "penalty_notice_users": [],
            "temporary_pings": {},
            "pending_message_deletions": {},
            "all_voted_message": None,
            "completion_state_migrated": False,
            "veto_penalties": {},
            "active_veto_penalties": [],
            "vote_message": None,
            "tracked_messages": [],
            "cleanup_time": None,
            "cleanup_delay_hours": 12.0,
            "reminder_time": None,
            "reminder_delay_hours": 2.0,
            "smart_reminder_offset_minutes": 60,
            "smart_reminder_enabled": True,
            "smart_reminder_sent": False,
            "players": {},
            "auto_open_enabled": False,
            "auto_open_time": "18:00",
            "auto_open_days": [4, 5],
            "auto_open_channel_id": None,
            "auto_close_hours": 16.0,
            "auto_close_time": None,
            "auto_opened_date": None
        }
        self.config.register_global(**default_global)

    @asynccontextmanager
    async def _config_transaction(self):
        # Own the lock outside Redbot's context manager: its __aenter__ may
        # fail during reading, before its __aexit__ can release the lock.
        lock = self.config.get_lock()
        try:
            await asyncio.wait_for(lock.acquire(), timeout=10)
        except asyncio.TimeoutError as exc:
            raise ConfigBusyError("GameNight Config lock unavailable for 10 seconds") from exc
        try:
            async with self.config.all(acquire_lock=False) as data:
                yield data
        finally:
            lock.release()

    async def _get_or_restore_vote_message(self):
        """Retrieve or restore the cached vote message and channel, supporting startup recovery."""
        if self.vote_message and self.vote_channel:
            return self.vote_channel, self.vote_message
            
        vote_msg_data = await self.config.vote_message()
        if not vote_msg_data:
            return None, None
            
        channel_id, msg_id = vote_msg_data
        try:
            channel = self.vote_channel
            if not channel:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                self.vote_channel = channel
                
            msg = self.vote_message
            if not msg:
                msg = await channel.fetch_message(msg_id)
                self.vote_message = msg
                
            return channel, msg
        except Exception:
            return None, None

    async def handle_rsvp(self, interaction: discord.Interaction, time_val: str):
        # A failed/expired acknowledgement must not discard the user's selection.
        acknowledged = interaction.response.is_done()
        if not acknowledged:
            received_age = (datetime.now(timezone.utc) - interaction.created_at).total_seconds()
            ack_started = time.monotonic()
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                acknowledged = True
            except discord.InteractionResponded:
                acknowledged = True
            except (discord.HTTPException, asyncio.TimeoutError):
                log.exception("RSVP acknowledgement failed (interaction=%s, age=%.2fs)",
                              interaction.id,
                              (datetime.now(timezone.utc) - interaction.created_at).total_seconds())
            finally:
                ack_duration = time.monotonic() - ack_started
                if received_age >= 2 or ack_duration >= 1:
                    log.warning("Slow RSVP acknowledgement: interaction=%s, age_at_handler=%.2fs, acknowledgement_duration=%.2fs, acknowledged=%s",
                                interaction.id, received_age, ack_duration, acknowledged)

        saved = False
        try:
            if not self.is_open:
                if acknowledged:
                    await interaction.edit_original_response(content="De stemming is momenteel gesloten.")
                return
                
            async with self._config_transaction() as data:
                uid = str(interaction.user.id)
                data["players"][uid] = time_val
                if time_val == "No":
                    data["penalty_warnings"].pop(uid, None)
                    msg = "❌ Je staat vandaag als **afwezig** geregistreerd."
                else:
                    display_time = {"Earlier": "vóór 20:00", "Later": "na 23:00"}.get(time_val, time_val)
                    msg = f"✅ Je staat als aanwezig geregistreerd vanaf **{display_time}**!"
                    
            saved = True
            penalty_embed = None
            if time_val != "No" and str(interaction.user.id) in await self.config.active_veto_penalties():
                penalty_embed = self._veto_blocked_embed()
            # Confirmation delivery and public UI updates are independent of storage.
            if acknowledged:
                try:
                    await interaction.edit_original_response(content=msg, embed=penalty_embed)
                except (discord.HTTPException, asyncio.TimeoutError):
                    log.exception("RSVP saved but confirmation failed (interaction=%s)", interaction.id)
            
            # Update the embed
            await self._update_rsvp_embed()
            
            # Reschedule the smart reminder based on the new earliest RSVP time
            await self._reschedule_smart_reminder()
            
            # Check completion
            await self.check_completion()
        except discord.errors.InteractionResponded:
            pass  # Already handled — safe to ignore
        except Exception as e:
            log.exception("RSVP processing failed (interaction=%s, saved=%s)", interaction.id, saved)
            # Last resort: make sure the user gets feedback
            try:
                await interaction.followup.send(
                    ("⚠️ Je aanmelding is opgeslagen, maar het bericht kon niet worden bijgewerkt."
                     if saved else "⚠️ Je aanmelding kon niet worden opgeslagen. Probeer het opnieuw."), ephemeral=True
                )
            except Exception:
                pass

    async def _update_rsvp_embed(self):
        # Read current players only after earlier edits finish, so a slow edit
        # cannot overwrite a newer player's selection with an older snapshot.
        async with self._rsvp_embed_lock:
            await self._edit_rsvp_embed()

    async def _edit_rsvp_embed(self):
        channel, msg = await self._get_or_restore_vote_message()
        if not channel or not msg:
            return
            
        try:
            if not msg.embeds:
                return
                
            embed = msg.embeds[0].copy()
            players = await self.config.players()
            limit = await self.config.skip_limit()
            rule = ("Passen: onbeperkt." if limit is None else
                    f"Passen: maximaal {limit} keer per kalendermaand.")
            if embed.description:
                embed.description = re.sub(r"(?:Skipping|Passen): [^\n]*", rule, embed.description)
            
            # Rebuild the fields
            embed.clear_fields()
            embed.add_field(
                name="Speel je vanavond mee?",
                value="Kies hieronder je verwachte aankomsttijd.\nKies ❌ als je niet kunt meedoen.",
                inline=False,
            )
            embed.add_field(
                name="⚠️ Stemdeadline en straf",
                value=("Stem uiterlijk **10 minuten vóór de vroegste starttijd**. Bekijk je waarschuwing voor je exacte deadline.\n"
                       "Mis je de deadline? De volgende avond waarop je aanwezig bent: **geen negatieve stem** en een **eerste keuze van 2 punten** bij gewogen stemmen.\n"
                       "Een geaccepteerde `!pass` telt ook. Er wordt nooit automatisch een pass afgetrokken."),
                inline=False,
            )
            
            joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
            absent_players = {uid: t_val for uid, t_val in players.items() if t_val == "No"}
            penalty_session = await self.config.penalty_session()
            penalties = await self.config.veto_penalties()
            
            if joining_players:
                # Format player list
                player_lines = []
                for uid, t_val in joining_players.items():
                    has_voted = int(uid) in self.votes
                    if has_voted:
                        pos, neg = self.votes[int(uid)]
                        status_emoji = "🎲" if (not pos and not neg) else "🎮"
                    else:
                        status_emoji = "🔒" if penalty_session and penalties.get(uid) == penalty_session else "❓"
                    display_time = {"Earlier": "vóór 20:00", "Later": "na 23:00"}.get(t_val, t_val)
                    player_lines.append(f"• <@{uid}> - {display_time} {status_emoji}")
                    
                embed.add_field(
                    name=f"🎮 Spelers en aankomsttijd ({len(joining_players)})",
                    value="\n".join(player_lines),
                    inline=False
                )
                
            if absent_players:
                # Format absent player list
                absent_lines = []
                for uid in absent_players.keys():
                    absent_lines.append(f"• <@{uid}>")
                    
                embed.add_field(
                    name=f"❌ Afwezig ({len(absent_players)})",
                    value="\n".join(absent_lines),
                    inline=False
                )
                
            self.vote_message = await msg.edit(embed=embed)
        except Exception as e:
            log.exception("Could not update RSVP message")

    async def cog_load(self):
        """Restore state from config when the bot reboots."""
        # Older releases stored a dict under a key registered as None. Convert it
        # before Config.all() attempts Redbot's recursive default merge.
        legacy_result = await self.config.session_result()
        if isinstance(legacy_result, dict):
            await self.config.session_result.set(json.dumps(legacy_result) if legacy_result else None)
        self.is_open = await self.config.is_open()
        
        raw_votes = await self.config.votes()
        self.votes = {int(k): v for k, v in raw_votes.items()}
        
        # Restore auto-opened date so we don't double-open after a reboot
        self._auto_opened_date = await self.config.auto_opened_date()
        
        # We don't eagerly load/fetch the message here during startup hook because the channel cache
        # might not be fully loaded. Instead, the lazy loader _get_or_restore_vote_message recovers it on-demand.
        self.vote_channel = None
        self.vote_message = None

        cleanup_time = await self.config.cleanup_time()
        if cleanup_time:
            now = time.time()
            delay = max(0, cleanup_time - now)
            self._cleanup_task = asyncio.create_task(self._schedule_cleanup(delay_seconds=delay))

        # Restore auto-close timer if one was scheduled
        auto_close_time = await self.config.auto_close_time()
        if auto_close_time:
            now = time.time()
            delay = max(0, auto_close_time - now)
            self._auto_close_task = asyncio.create_task(self._schedule_auto_close(delay_seconds=delay))

        reminder_time = await self.config.reminder_time()
        if reminder_time and self.is_open and await self.config.reminder_delay_hours() > 0:
            now = time.time()
            delay = max(0, reminder_time - now)
            self._reminder_task = asyncio.create_task(self._schedule_reminder(delay_seconds=delay))
        else:
            await self.config.reminder_time.set(None)

        self._smart_reminder_sent = await self.config.smart_reminder_sent()
        if self.is_open:
            self._smart_reminder_task = asyncio.create_task(self._restore_smart_reminder())

        # Clean up any duplicate RSVPViews/CloseVoteViews from previous reloads
        for view in list(self.bot.persistent_views):
            if view.__class__.__name__ in ("RSVPView", "CloseVoteView"):
                try:
                    view.stop()
                except Exception:
                    pass
                try:
                    self.bot.persistent_views.remove(view)
                except Exception:
                    pass
                    
        if hasattr(self.bot, "_connection") and hasattr(self.bot._connection, "_persistent_views"):
            for view in list(self.bot._connection._persistent_views):
                if view.__class__.__name__ in ("RSVPView", "CloseVoteView"):
                    try:
                        view.stop()
                    except Exception:
                        pass
                    try:
                        self.bot._connection._persistent_views.remove(view)
                    except Exception:
                        pass

        # Store view references so we can stop them on unload to prevent duplicates
        self.rsvp_view = RSVPView(self)
        self.bot.add_view(self.rsvp_view)
        self.close_vote_view = CloseVoteView(self)
        self.bot.add_view(self.close_vote_view)

        # Start the auto-open background loop
        self._auto_open_loop.start()
        self._penalty_loop.start()

    def cog_unload(self):
        """Clean up active persistent views and running tasks on cog unload."""
        if hasattr(self, 'rsvp_view'):
            self.rsvp_view.stop()
        if hasattr(self, 'close_vote_view'):
            self.close_vote_view.stop()
        if hasattr(self, '_cleanup_task') and self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if hasattr(self, '_auto_close_task') and self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
        if hasattr(self, '_reminder_task') and self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if hasattr(self, '_smart_reminder_task') and self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        if self._auto_open_loop.is_running():
            self._auto_open_loop.cancel()
        if self._penalty_loop.is_running():
            self._penalty_loop.cancel()

    async def _track(self, msg: discord.Message):
        """Register a message for the post-session cleanup."""
        if msg is not None:
            self.tracked_messages.append(msg)
            async with self.config.tracked_messages() as tracked:
                tracked.append([msg.channel.id, msg.id])

    async def _send_temporary_ping(self, channel, users):
        """Ping separately from the embed; recover overdue deletions after reboot."""
        if not users:
            return
        message = await channel.send(
            content=" ".join(f"<@{uid}>" for uid in users) + "\nDit bericht dient alleen als ping en wordt na 1 minuut automatisch verwijderd.", delete_after=60,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        async with self.config.temporary_pings() as pending:
            pending[str(message.id)] = [channel.id, time.time() + 60]

    async def _cleanup_temporary_pings(self):
        for message_id, (channel_id, deadline) in (await self.config.temporary_pings()).items():
            if time.time() < deadline:
                continue
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                await channel.get_partial_message(int(message_id)).delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception("Could not delete temporary ping %s", message_id)
                continue
            async with self.config.temporary_pings() as pending:
                pending.pop(message_id, None)

    async def _clear_completion_message(self):
        try:
            await self._migrate_completion_message()
        except (discord.HTTPException, discord.Forbidden):
            log.exception("Could not recover legacy completion message during cleanup")
        reference = await self.config.all_voted_message()
        message = self._all_voted_msg
        if reference:
            await self._delete_message_or_retry(*reference, message=message)
        elif message:
            await self._delete_message_or_retry(message.channel.id, message.id, message=message)
        await self.config.all_voted_message.set(None)
        self._all_voted_msg = None
        self.all_voted_notified = False

    async def _delete_message_or_retry(self, channel_id, message_id, *, message=None):
        """Persist cleanup before Discord I/O; a failed deletion must not stop voting."""
        key = f"{channel_id}:{message_id}"
        async with self.config.pending_message_deletions() as pending:
            pending[key] = [channel_id, message_id]
        try:
            if message is None:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                message = channel.get_partial_message(message_id)
            await message.delete()
        except discord.NotFound:
            pass
        except (discord.HTTPException, discord.Forbidden):
            log.exception("Message deletion failed; will retry %s", key)
            return
        async with self.config.pending_message_deletions() as pending:
            pending.pop(key, None)

    async def _retry_message_deletions(self):
        for channel_id, message_id in (await self.config.pending_message_deletions()).values():
            await self._delete_message_or_retry(channel_id, message_id)

    async def _migrate_completion_message(self):
        """Recover a ready message created before its dedicated Config reference existed."""
        if await self.config.completion_state_migrated():
            return
        reference = await self.config.all_voted_message()
        vote_reference = await self.config.vote_message()
        if not reference and vote_reference:
            for channel_id, message_id in await self.config.tracked_messages():
                if channel_id != vote_reference[0] or message_id <= vote_reference[1]:
                    continue
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    continue
                if not any(getattr(item, "custom_id", None) == "gn_close_vote_btn"
                           for row in message.components for item in row.children):
                    continue
                if reference:
                    await self._delete_message_or_retry(channel_id, message_id, message=message)
                else:
                    reference = [channel_id, message_id]
                    await self.config.all_voted_message.set(reference)
        await self.config.completion_state_migrated.set(True)

    async def _schedule_cleanup(self, delay_seconds: float):
        """Wait `delay_seconds` then bulk-delete all tracked messages, fetching channels if uncached."""
        await asyncio.sleep(delay_seconds)
        await self._do_cleanup()
        await self.config.cleanup_time.set(None)

    async def _schedule_auto_close(self, delay_seconds: float):
        """Wait `delay_seconds` then auto-close the vote and clean up all tracked messages.

        This is a fallback in case nobody ever calls !gn close (e.g. nobody showed up).
        """
        await asyncio.sleep(delay_seconds)

        await self.config.auto_close_time.set(None)

        if not self.is_open:
            # Vote was already closed manually — just clean up leftover messages
            await self._do_cleanup()
            return

        # Close the vote
        self.is_open = False
        await self._clear_completion_message()
        await self.config.is_open.set(False)
        await self._sync_penalty_warning(clear=True)
        self.all_voted_notified = False
        self.too_many_notified = False

        # Remove the RSVP view from the embed
        channel, msg = await self._get_or_restore_vote_message()
        if msg:
            try:
                await msg.edit(view=None)
            except (discord.NotFound, discord.HTTPException):
                pass

        # Cancel voting reminders
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        await self.config.reminder_time.set(None)

        # Clean up all tracked messages
        await self._finish_veto_penalties(channel)
        await self._do_cleanup()

    async def _do_cleanup(self):
        """Delete all tracked messages and clear the tracking list."""
        tracked = await self.config.tracked_messages()
        for channel_id, msg_id in tracked:
            try:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                if channel:
                    msg = channel.get_partial_message(msg_id)
                    await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        self.tracked_messages.clear()
        await self.config.tracked_messages.set([])

    async def _schedule_reminder(self, delay_seconds: float):
        """Wait `delay_seconds` then ping everyone who RSVP'd but hasn't voted yet."""
        await asyncio.sleep(delay_seconds)
        
        if not self.is_open:
            return
            
        channel, msg = await self._get_or_restore_vote_message()
        if not channel:
            return
            
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        missing_uids = await self._missing_voters(joining_players)
        
        if missing_uids:
            pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
            embed = discord.Embed(
                title="⏳ Vergeet niet te stemmen!",
                description=(
                    f"Hey {pings},\n\n"
                    f"Je staat als aanwezig voor vanavond, maar hebt nog niet gestemd!\n"
                    f"Stuur mij een **DM** met je keuzes, zodat we kunnen bepalen wat we spelen.\n\n"
                    f"Voorbeeld: `!vote Fortnite, Palworld` 🤫"
                ),
                color=discord.Color.yellow(),
            )
            reminder_msg = await channel.send(embed=embed)
            await self._track(reminder_msg)
            await self._send_temporary_ping(channel, missing_uids)
            
        await self.config.reminder_time.set(None)

    def _get_earliest_rsvp_datetime(self, players: dict) -> datetime | None:
        """Find the earliest RSVP clock time among joining players and return it as a datetime for today."""
        # Use CET/CEST (UTC+2 in summer, UTC+1 in winter) — we use the bot's local time
        now = datetime.now()
        earliest = None
        
        for uid, t_val in players.items():
            if t_val == "No":
                continue
            mapped = RSVP_TIME_MAP.get(t_val)
            if not mapped:
                continue
            hour, minute = map(int, mapped.split(":"))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if earliest is None or candidate < earliest:
                earliest = candidate
                
        return earliest

    async def _restore_smart_reminder(self):
        await self.bot.wait_until_ready()
        # Rescheduling must not cancel this restoration task itself.
        if self._smart_reminder_task is asyncio.current_task():
            self._smart_reminder_task = None
            await self._reschedule_smart_reminder()

    async def _reschedule_smart_reminder(self):
        """(Re)schedule the smart reminder based on the earliest RSVP time minus the configured offset."""
        # Don't reschedule if the smart reminder was already sent this session
        if self._smart_reminder_sent:
            return
            
        smart_enabled = await self.config.smart_reminder_enabled()
        if not smart_enabled or not self.is_open:
            return
            
        # Cancel any existing smart reminder task
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
            self._smart_reminder_task = None
        
        players = await self.config.players()
        earliest = self._get_earliest_rsvp_datetime(players)
        if earliest is None:
            return
            
        offset_minutes = await self.config.smart_reminder_offset_minutes()
        reminder_dt = earliest - timedelta(minutes=offset_minutes)
        now = datetime.now()
        delay_seconds = (reminder_dt - now).total_seconds()
        
        if delay_seconds <= 0:
            # The reminder time has already passed — fire it immediately
            self._smart_reminder_task = asyncio.create_task(self._fire_smart_reminder(earliest, offset_minutes))
        else:
            self._smart_reminder_task = asyncio.create_task(self._schedule_smart_reminder(delay_seconds, earliest, offset_minutes))

    async def _schedule_smart_reminder(self, delay_seconds: float, earliest_dt: datetime, offset_minutes: int):
        """Wait `delay_seconds` then fire the smart reminder."""
        await asyncio.sleep(delay_seconds)
        await self._fire_smart_reminder(earliest_dt, offset_minutes)

    async def _fire_smart_reminder(self, earliest_dt: datetime, offset_minutes: int):
        """Send the smart reminder to all RSVP'd players who haven't voted yet."""
        if not self.is_open or self._smart_reminder_sent:
            return
            
        channel, msg = await self._get_or_restore_vote_message()
        if not channel:
            return
            
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        missing_uids = await self._missing_voters(joining_players)
        
        if not missing_uids:
            return  # Everyone already voted, no need for a reminder
            
        earliest_str = earliest_dt.strftime("%H:%M")
        
        # Format the offset nicely
        if offset_minutes >= 60:
            hours = offset_minutes // 60
            mins = offset_minutes % 60
            if mins > 0:
                offset_text = f"{hours}h{mins}m"
            else:
                offset_text = f"{hours} uur"
        else:
            offset_text = f"{offset_minutes} minuten"
        
        pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
        embed = discord.Embed(
            title="🔔 De gameavond begint binnenkort!",
            description=(
                f"Hey {pings},\n\n"
                f"De eerste speler wordt verwacht om **{earliest_str}** — over **{offset_text}**!\n"
                f"Je staat als aanwezig, maar hebt **nog geen games gekozen**.\n\n"
                f"Stuur mij een **DM** met je keuzes:\n"
                f"Voorbeeld: `!vote Fortnite, Palworld` 🤫"
            ),
            color=discord.Color.orange(),
        )
        reminder_msg = await channel.send(embed=embed)
        self._smart_reminder_sent = True
        await self.config.smart_reminder_sent.set(True)
        await self._track(reminder_msg)

        await self._send_temporary_ping(channel, missing_uids)

    def _veto_blocked_embed(self):
        return discord.Embed(
            title="🔒 Stemstraf tijdens deze gameavond",
            description=("Je hebt tijdens een eerdere gameavond de stemdeadline gemist.\n\n"
                         "**Je kunt nog steeds op games stemmen:** `!vote Fortnite, Minecraft`\n"
                         "Je negatieve stem (`# Game`) is deze ronde niet beschikbaar. "
                         "Verwijder die en stuur je stem opnieuw.\n\n"
                         "Bij gewogen stemmen telt je eerste keuze voor **2 in plaats van 3 punten**. "
                         "De straf eindigt na deze ronde als je aanwezig bent, tenzij je opnieuw een deadline mist."),
            color=discord.Color.red(),
        )

    async def _finish_veto_penalties(self, channel):
        """Serve a penalty only during a later session in which the user attends."""
        restored = []
        async with self._config_transaction() as data:
            for uid in data["active_veto_penalties"]:
                attending = data["players"].get(uid) != "No" and (
                    uid in data["players"] or uid in data["votes"])
                if attending and data["veto_penalties"].get(uid) != data["penalty_session"]:
                    if uid in data["veto_penalties"]:
                        del data["veto_penalties"][uid]
                        restored.append(uid)
            data["active_veto_penalties"] = []
        if restored and channel:
            embed = discord.Embed(
                title="✅ Stemstraf afgelopen",
                description=("Je straf van één ronde is afgelopen. De volgende gameavond mag je weer een negatieve stem gebruiken "
                             "als veto is ingeschakeld, en telt je eerste keuze weer voor 3 punten bij gewogen stemmen."),
                color=discord.Color.green(),
            )
            try:
                await self._track(await channel.send(
                    content=" ".join(f"<@{uid}>" for uid in restored), embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)))
            except discord.HTTPException:
                log.exception("Could not announce restored veto rights")

    @tasks.loop(seconds=30)
    async def _penalty_loop(self):
        try:
            await self._retry_message_deletions()
            await self._cleanup_temporary_pings()
            async with self._close_lock:
                await self._check_vote_deadlines()
        except Exception:
            log.exception("Vote deadline check failed")

    @_penalty_loop.before_loop
    async def _before_penalty_loop(self):
        await self.bot.wait_until_ready()

    async def _sync_penalty_warning(self, *, proposals=None, clear=False):
        """Maintain one persistent warning with only people still waiting to vote."""
        async with self._penalty_warning_lock:
            data = await self.config.all()
            deadlines = dict(data["penalty_warnings"])
            deadlines.update(proposals or {})
            waiting = {uid: deadline for uid, deadline in deadlines.items()
                       if self.is_open and not clear
                       and uid in data["players"] and data["players"][uid] != "No"
                       and int(uid) not in self.votes
                       and data["veto_penalties"].get(uid) != data["penalty_session"]}
            reference = data["penalty_warning_message"]
            # Remove obsolete deadlines even if no message/channel is available.
            # Proposed deadlines are only committed after the warning is delivered.
            async with self._config_transaction() as current:
                for uid in list(current["penalty_warnings"]):
                    if (clear or not self.is_open or uid not in current["players"]
                            or current["players"][uid] == "No" or int(uid) in self.votes
                            or current["veto_penalties"].get(uid) == current["penalty_session"]):
                        current["penalty_warnings"].pop(uid, None)
            if not waiting and not reference:
                return
            channel, _ = await self._get_or_restore_vote_message()
            if reference:
                channel = self.bot.get_channel(reference[0]) or await self.bot.fetch_channel(reference[0])
            if not channel:
                return
            message = channel.get_partial_message(reference[1]) if reference else None
            if not waiting:
                if message:
                    try:
                        await message.delete()
                    except discord.NotFound:
                        pass
                    await self.config.penalty_warning_message.set(None)
                return
            groups = defaultdict(list)
            for uid, deadline in waiting.items():
                groups[int(deadline)].append(f"<@{uid}>")
            deadline_text = "\n".join(
                f"**<t:{deadline}:t> (<t:{deadline}:R>)** — {', '.join(users)}"
                for deadline, users in sorted(groups.items()))
            embed = discord.Embed(
                title="⚠️ Stem op tijd — voorkom een straf",
                description=("Deze aanwezige spelers hebben **nog niet gestemd**.\n\n"
                             f"**Stemdeadlines**\n{deadline_text}\n\n"
                             "Stuur een DM: `!vote Fortnite, Minecraft`. Een geaccepteerde `!pass` telt ook, "
                             "binnen je maandlimiet. Kun je niet meedoen? Kies **Vandaag niet aanwezig**.\n\n"
                             "**Niet gestemd vóór je deadline?** Tijdens de **volgende gameavond waarop je aanwezig bent**, "
                             "vervalt je negatieve stem (`# Game`) en telt je eerste keuze voor "
                             "**2 in plaats van 3 punten** bij gewogen stemmen. Er wordt geen pass afgetrokken."),
                color=discord.Color.orange(),
            )
            if message:
                try:
                    await message.edit(content=None, embed=embed,
                        allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))
                except discord.NotFound:
                    message = None
            if message is None:
                message = await channel.send(embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                await self.config.penalty_warning_message.set([channel.id, message.id])
                await self._track(message)
            # A deadline becomes enforceable only after the warning was delivered.
            async with self._config_transaction() as current:
                if self.is_open and current["penalty_session"] == data["penalty_session"]:
                    for uid, deadline in waiting.items():
                        if (current["players"].get(uid, "No") != "No" and int(uid) not in self.votes
                                and current["veto_penalties"].get(uid) != current["penalty_session"]):
                            current["penalty_warnings"][uid] = deadline
            new_users = [uid for uid in waiting if uid not in data["penalty_warnings"]]
            await self._send_temporary_ping(channel, new_users)

    async def _sync_penalty_notice(self, channel):
        """One announcement for all penalties incurred this round, including late voters."""
        data = await self.config.all()
        users = sorted(uid for uid, session in data["veto_penalties"].items()
                       if session == data["penalty_session"])
        if not users:
            return
        reference = data["penalty_notice_message"]
        if reference and users == data["penalty_notice_users"]:
            return
        mentions = ", ".join(f"<@{uid}>" for uid in users)
        embed = discord.Embed(
            title="🔒 Deadline gemist — straf bij de volgende gameavond",
            description=(f"**Spelers:** {mentions}\n\n"
                         "Deze spelers stonden als aanwezig geregistreerd en stemden niet vóór hun aangekondigde deadline.\n\n"
                         "**De volgende gameavond waarop deze spelers aanwezig zijn: geen negatieve stem (`# Game`) en de eerste "
                         "keuze telt voor 2 in plaats van 3 punten bij gewogen stemmen.**\n"
                         "Je mag gewoon meespelen en positief stemmen. De straf eindigt na die ronde, "
                         "tenzij je opnieuw een deadline mist.\n\n"
                         "Je mag vanavond nog stemmen, maar dat maakt de straf niet ongedaan. "
                         "**Er is geen pass afgetrokken.**"),
            color=discord.Color.red(),
        )
        message = None
        if reference:
            notice_channel = self.bot.get_channel(reference[0]) or await self.bot.fetch_channel(reference[0])
            message = notice_channel.get_partial_message(reference[1])
            try:
                await message.edit(content=None, embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))
            except discord.NotFound:
                message = None
        if message is None:
            message = await channel.send(embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            await self.config.penalty_notice_message.set([channel.id, message.id])
            await self._track(message)
        await self.config.penalty_notice_users.set(users)
        await self._send_temporary_ping(channel, [uid for uid in users if uid not in data["penalty_notice_users"]])

    async def _check_vote_deadlines(self):
        if not self.is_open:
            return
        channel, message = await self._get_or_restore_vote_message()
        if not channel:
            return
        data = await self.config.all()
        # Existing sessions from before this feature are not punished retroactively.
        if not data["penalty_session"]:
            return
        players = data["players"]
        earliest = self._get_earliest_rsvp_datetime(players)
        if earliest is None:
            await self._sync_penalty_warning()
            return
        # Keep clock-only RSVPs anchored to the day this session opened, including after reboot.
        opened = datetime.fromtimestamp(int(data["penalty_session"]) / 1_000_000_000)
        earliest = earliest.replace(year=opened.year, month=opened.month, day=opened.day)
        now = time.time()
        before_warning_window = now < earliest.timestamp() - 30 * 60
        proposals = {}
        penalties_added = False
        for uid, eta in players.items():
            if eta == "No" or int(uid) in self.votes:
                continue
            if data["veto_penalties"].get(uid) == data["penalty_session"]:
                continue
            warning = data["penalty_warnings"].get(uid)
            if before_warning_window and warning is None:
                continue
            target = earliest.timestamp() - 10 * 60
            # Never bring a previously announced deadline forward. Moving the start
            # later extends it and triggers an updated warning.
            if warning is None or target > warning:
                deadline = max(target, now + 10 * 60)
                proposals[uid] = deadline
            elif now >= warning:
                # Recheck after any network awaits; a vote or withdrawal wins the race.
                async with self._config_transaction() as current:
                    if (not self.is_open or current["players"].get(uid) == "No"
                            or int(uid) in self.votes
                            or current["penalty_warnings"].get(uid) != warning):
                        continue
                    current["veto_penalties"][uid] = current["penalty_session"]
                    penalties_added = True
        await self._sync_penalty_notice(channel)
        await self._sync_penalty_warning(proposals=proposals)
        if penalties_added:
            await self._update_rsvp_embed()
            await self.check_completion()

    def normalize_game_name(self, user_input):
        clean_input = user_input.strip().lower()
        if not clean_input:
            return None, False

        for official_name, aliases in GAME_ALIASES.items():
            if clean_input == official_name.lower() or clean_input in aliases:
                return official_name, False

        all_possibilities = {name.lower(): name for name in GAME_ALIASES}
        for name, aliases in GAME_ALIASES.items():
            for a in aliases:
                all_possibilities[a] = name

        matches = difflib.get_close_matches(clean_input, all_possibilities.keys(), n=1, cutoff=0.6)

        if matches:
            return all_possibilities[matches[0]], True

        return user_input.strip().title(), False

    async def _get_rsvp_count(self) -> int | None:
        """Returns the current number of users who have set an ETA, or None if unavailable."""
        channel, msg = await self._get_or_restore_vote_message()
        if not msg or not channel:
            return None
        players = await self.config.players()
        joining_players = [uid for uid, t_val in players.items() if t_val != "No"]
        return len(joining_players)

    async def _missing_voters(self, players):
        session = await self.config.penalty_session()
        penalties = await self.config.veto_penalties()
        return [uid for uid, eta in players.items()
                if eta != "No" and int(uid) not in self.votes
                and not (session and penalties.get(uid) == session)]

    async def check_completion(self):
        async with self._completion_lock:
            await self._check_completion_locked()

    async def _check_completion_locked(self):
        """Checks whether everyone who has an ETA has actually voted.
        Also sends a warning when more than TOO_MANY_PLAYERS_THRESHOLD players are present.
        """
        await self._sync_penalty_warning()
        if not self.is_open:
            return

        channel, msg = await self._get_or_restore_vote_message()
        if not msg or not channel:
            return

        await self._migrate_completion_message()
        reference = await self.config.all_voted_message()
        if reference and self._all_voted_msg is None:
            try:
                saved_channel = self.bot.get_channel(reference[0]) or await self.bot.fetch_channel(reference[0])
                self._all_voted_msg = await saved_channel.fetch_message(reference[1])
                self.all_voted_notified = True
            except discord.NotFound:
                await self.config.all_voted_message.set(None)
                self.all_voted_notified = False

        try:
            players = await self.config.players()
            joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
            player_count = len(joining_players)

            # ── "Too many players" warning ──────────────────────────────────
            if player_count > TOO_MANY_PLAYERS_THRESHOLD:
                if not self.too_many_notified:
                    self.too_many_notified = True
                    embed = discord.Embed(
                        title="⚠️ Veel spelers vanavond!",
                        description=(
                            f"Er staan nu **{player_count} spelers** als aanwezig geregistreerd.\n"
                            f"Games voor maximaal **{TOO_MANY_PLAYERS_THRESHOLD} spelers** "
                            f"zijn nu **minder geschikt**. 🚫\n\n"
                            "Houd bij het stemmen rekening met het maximale aantal spelers!"
                        ),
                        color=discord.Color.orange(),
                    )
                    warn_msg = await channel.send(embed=embed)
                    await self._track(warn_msg)
            else:
                # Player count dropped back down — reset so the warning can fire again if needed
                self.too_many_notified = False

            # ── Minimum threshold for the "all votes in" check ──────────────
            # Only evaluate once at least 3 people have RSVP'd.
            if player_count < 3:
                await self._clear_completion_message()
                return

            # Check who is still missing a vote
            missing = await self._missing_voters(joining_players)

            if not missing:
                # Everyone has voted — send the notification (only once)
                if not self.all_voted_notified:

                    # Clean up old all_voted notification if one was sent previously
                    if self._all_voted_msg:
                        try:
                            await self._all_voted_msg.delete()
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                        self._all_voted_msg = None

                    embed = discord.Embed(
                        title="✅ De stemming kan gesloten worden!",
                        description="Alle aanwezigen hebben gestemd, gepast of een straf gekregen voor het missen van hun deadline.\nKlik hieronder om de stemming te sluiten en de uitslag te bekijken!",
                        color=discord.Color.green(),
                    )
                    all_voted_msg = await channel.send(embed=embed, view=CloseVoteView(self))
                    self._all_voted_msg = all_voted_msg
                    await self.config.all_voted_message.set([channel.id, all_voted_msg.id])
                    self.all_voted_notified = True
                    await self._track(all_voted_msg)
            else:
                # The completion announcement is no longer true; remove it entirely.
                await self._clear_completion_message()

        except discord.NotFound:
            pass  # Message was deleted
        except Exception as e:
            print(f"Error checking completion: {e}")



    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        """Beheer de gameavond, stemming, herinneringen en instellingen."""
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        """Schakel gewogen stemmen (3-2-1 punten) in of uit."""
        current = await self.config.weighted_mode()
        await self.config.weighted_mode.set(not current)
        status = "**AAN** (3-2-1)" if not current else "**UIT** (1-1-1)"
        await ctx.send(f"⚖️ Gewogen stemmen staat nu {status}.")

    @gamenight.command(name="veto")
    @commands.admin_or_permissions(administrator=True)
    async def gn_veto(self, ctx):
        """Schakel de negatieve stem met # in of uit."""
        current = await self.config.veto_mode()
        await self.config.veto_mode.set(not current)
        status = "**INGESCHAKELD** 💀" if not current else "**UITGESCHAKELD** ☮️"
        await ctx.send(f"🛡️ Veto staat nu {status}.")

    async def _do_open_vote(self, channel: discord.TextChannel, trigger_message: discord.Message = None):
        """Shared logic to open a new voting session in the given channel.
        
        Parameters
        ----------
        channel : discord.TextChannel
            The channel to post the voting embed in.
        trigger_message : discord.Message, optional
            The command message that triggered the open (tracked for cleanup).
        """
        # Replacing an open round is not completion of a penalty. Only recover
        # unfinished bookkeeping here when the previous round was closed.
        await self._sync_penalty_warning(clear=True)
        if not self.is_open:
            await self._finish_veto_penalties(channel)
        await self._clear_completion_message()
        async with self._config_transaction() as data:
            data["penalty_session"] = str(time.time_ns())
            data["all_voted_message"] = None
            data["completion_state_migrated"] = True
            data["penalty_warnings"] = {}
            data["penalty_notice_message"] = None
            data["penalty_notice_users"] = []
            data["active_veto_penalties"] = list(data["veto_penalties"])
        self.is_open = True
        self.votes.clear()
        self.all_voted_notified = False
        self.too_many_notified = False  # Reset at the start of each new voting round
        self._smart_reminder_sent = False  # Reset for the new session
        self._all_voted_msg = None
        
        await self.config.is_open.set(True)
        await self.config.votes.set({})
        await self.config.session_result.set(None)
        await self.config.session_skip_users.set([])
        await self.config.smart_reminder_sent.set(False)
        await self.config.vote_message.set(None)
        await self.config.tracked_messages.set([])
        await self.config.cleanup_time.set(None)
        await self.config.players.set({})

        # Cancel any leftover cleanup/reminder/smart-reminder task and start fresh
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        self.tracked_messages.clear()

        weighted = await self.config.weighted_mode()
        veto = await self.config.veto_mode()
        skip_limit = await self.config.skip_limit()
        skip_rule = ("Passen: onbeperkt." if skip_limit is None else
                     f"Passen: maximaal {skip_limit} keer per kalendermaand.")

        rules = "🥇 3 punten | 🥈 2 punten | 🥉 1 pt" if weighted else "Elke positieve stem telt voor 1 punt."

        if veto:
            veto_text = "\n💀 **VETO INGESCHAKELD:** gebruik `#` voor een negatieve stem op een game (-1 punt)."
            example = "`!vote Minecraft, Fortnite, Palworld # Roblox`"
        else:
            veto_text = ""
            example = "`!vote Minecraft, Fortnite, Palworld`"

        embed = discord.Embed(
            title="🎮 Stemmen voor de gameavond is geopend!",
            description=f"Stuur mij een **DM** met je keuzes.\nVoorbeeld: {example}\nGeen voorkeur? Stuur `!pass` of `!vote pass` 🎲\n{skip_rule}\n\n{rules}{veto_text}",
            color=discord.Color.green(),
        )
        # The RSVP question
        embed.add_field(
            name="Speel je vanavond mee?",
            value="Kies hieronder je verwachte aankomsttijd.\nKies ❌ als je niet kunt meedoen.",
            inline=False,
        )
        embed.add_field(
            name="⚠️ Stem op tijd — voorkom een straf",
            value=("Speel je mee? Stem uiterlijk **10 minuten vóór de vroegste starttijd**.\n"
                   "Je krijgt 30 minuten vóór de start een waarschuwing. Late aanmelders krijgen minstens 10 minuten na hun waarschuwing.\n"
                   "Niet op tijd gestemd? De volgende gameavond waarop je aanwezig bent, vervalt je **negatieve stem** "
                   "en telt je eerste keuze voor **2 in plaats van 3 punten** bij gewogen stemmen. "
                   "Een geaccepteerde `!pass` telt ook; er wordt nooit automatisch een pass afgetrokken."),
            inline=False,
        )

        msg = await channel.send(embed=embed, view=RSVPView(self))
        self.vote_message = msg
        self.vote_channel = channel
        await self.config.vote_message.set([channel.id, msg.id])

        await self._track(msg)  # Track the open-vote embed
        if trigger_message:
            await self._track(trigger_message)  # Track the command message

        # Schedule voting reminder (only if delay > 0, i.e. not disabled)
        delay_hours = await self.config.reminder_delay_hours()
        if delay_hours > 0:
            delay_seconds = delay_hours * 3600
            reminder_time = time.time() + delay_seconds
            await self.config.reminder_time.set(reminder_time)
            self._reminder_task = asyncio.create_task(self._schedule_reminder(delay_seconds=delay_seconds))

        # Schedule auto-close fallback (closes vote + cleans up if nobody ever calls !gn close)
        if self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
        auto_close_hours = await self.config.auto_close_hours()
        if auto_close_hours > 0:
            auto_close_seconds = auto_close_hours * 3600
            auto_close_at = time.time() + auto_close_seconds
            await self.config.auto_close_time.set(auto_close_at)
            self._auto_close_task = asyncio.create_task(self._schedule_auto_close(delay_seconds=auto_close_seconds))

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        """Open een nieuwe stemronde voor de gameavond."""
        try:
            await self._do_open_vote(ctx.channel, trigger_message=ctx.message)
        except ConfigBusyError:
            log.exception("Cannot open GameNight: Config lock is blocked")
            await ctx.send("⚠️ De GameNight-opslag is geblokkeerd. Herstart de volledige bot (niet alleen deze cog) en probeer opnieuw. Je opgeslagen gegevens hoeven niet gewist te worden.")

    async def _do_close_vote(self, channel: discord.TextChannel):
        """Shared logic for closing a vote session (used by !gn close and the Close Vote button)."""
        async with self._close_lock:
            if not self.is_open:
                return

            self.is_open = False
            await self._clear_completion_message()
            await self.config.is_open.set(False)
            await self._sync_penalty_warning(clear=True)
            self.all_voted_notified = False
            self.too_many_notified = False

            # Remove view from vote message to prevent further RSVPs
            vote_channel, msg = await self._get_or_restore_vote_message()
            if msg:
                try:
                    await msg.edit(view=None)
                except discord.NotFound:
                    pass
                    
            closing_msg = await channel.send("🛑 **De stemming is gesloten!** De uitslag wordt berekend...")
            await self._track(closing_msg)
            await self._show_results(channel, finalize=True)
            await self._finish_veto_penalties(channel)

            # Schedule cleanup
            delay_hours = await self.config.cleanup_delay_hours()
            delay_seconds = delay_hours * 3600
            cleanup_time = time.time() + delay_seconds
            await self.config.cleanup_time.set(cleanup_time)

            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
            self._cleanup_task = asyncio.create_task(self._schedule_cleanup(delay_seconds=delay_seconds))

            # Cancel auto-close fallback (vote was closed manually, no need for the fallback)
            if self._auto_close_task and not self._auto_close_task.done():
                self._auto_close_task.cancel()
            await self.config.auto_close_time.set(None)

            # Cancel voting reminders
            if self._reminder_task and not self._reminder_task.done():
                self._reminder_task.cancel()
            if self._smart_reminder_task and not self._smart_reminder_task.done():
                self._smart_reminder_task.cancel()
            await self.config.reminder_time.set(None)

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        """Sluit de stemming en publiceer de uitslag."""
        if not self.is_open:
            return await ctx.send("⛔ De stemming is al gesloten.")
        await self._track(ctx.message)  # Track the !gn close command itself
        await self._do_close_vote(ctx.channel)

    @commands.command()
    async def vote(self, ctx, *, games_input: str):
        """Stem via DM: !vote Minecraft, Fortnite, Palworld. Voeg eventueel # Roblox toe als veto."""
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, stuur dit alsjeblieft in een DM! 🤫", delete_after=5
            )

        if not self.is_open:
            return await ctx.send("⛔ De stemming is momenteel gesloten.")

        # Check if player doesn't care / passes on voting
        pass_keywords = {
            "pass", "skip", "dontcare", "dont care", "idc", "whatever",
            "maaktnietuit", "maakt niet uit", "omhetit", "om het even",
            "geen voorkeur", "alles", "meedoen", "geenvoorkeur"
        }
        if games_input.strip().lower() in pass_keywords:
            return await self._register_pass(ctx)

        veto_enabled = await self.config.veto_mode()
        weighted_mode = await self.config.weighted_mode()
        penalized = str(ctx.author.id) in await self.config.active_veto_penalties()

        pos_input = games_input
        neg_input = None

        if "#" in games_input:
            if not veto_enabled:
                return await ctx.send("⛔ Veto is uitgeschakeld. Je kunt vandaag geen `#` gebruiken.")
            if penalized:
                return await ctx.send(embed=self._veto_blocked_embed())

            parts = games_input.split("#", 1)
            pos_input = parts[0]
            neg_input = parts[1]

        # 1. Positive votes
        raw_pos_games = pos_input.split(",")
        clean_pos_games = []
        corrections = []

        for g in raw_pos_games:
            if g.strip():
                final_name, was_corrected = self.normalize_game_name(g)
                if final_name:
                    clean_games_already = [x.lower() for x in clean_pos_games]
                    if final_name.lower() not in clean_games_already:
                        clean_pos_games.append(final_name)
                        if was_corrected:
                            corrections.append(f"'{g.strip()}' ➡️ **{final_name}**")

        clean_pos_games = clean_pos_games[:3]

        # 2. Negative vote (split on comma, take only the first)
        clean_neg_game = None
        if neg_input and neg_input.strip():
            raw_neg_games = neg_input.split(",")
            for g in raw_neg_games:
                if g.strip():
                    final_name, was_corrected = self.normalize_game_name(g)
                    if final_name:
                        clean_neg_game = final_name
                        if was_corrected:
                            corrections.append(f"'{g.strip()}' ➡️ **{final_name}**")
                        break

        if not clean_pos_games and not clean_neg_game:
            return await ctx.send("Geen geldige games gevonden. Gebruik: `!vote Minecraft, Fortnite # Palworld`")

        self.votes[ctx.author.id] = (clean_pos_games, clean_neg_game)
        await self.config.votes.set({str(k): v for k, v in self.votes.items()})

        msg = "✅ **Stemmen ontvangen!**\n"
        if corrections:
            msg += "\n🪄 *Automatisch gecorrigeerd:* " + ", ".join(corrections) + "\n\n"

        msg += "**Jouw keuzes:**\n"
        for i, game in enumerate(clean_pos_games):
            if weighted_mode:
                points = 2 if penalized and i == 0 else 3 - i
                msg += f"#{i+1} **{game}** (+{points} punten)\n"
            else:
                msg += f"- **{game}** (+1 punt)\n"

        if clean_neg_game:
            msg += f"💀 **{clean_neg_game}** (-1 punt)\n"
        if penalized:
            msg += ("\n🔒 **Stemstraf actief:** geen negatieve stem; "
                    "je eerste keuze telt voor 2 in plaats van 3 punten bij gewogen stemmen.\n")

        # ── Personal warning: flag games that don't fit the current group size ──
        player_count = await self._get_rsvp_count()
        if player_count is not None and player_count > 0:
            bad_games = []
            for game in clean_pos_games:
                max_p = GAMES.get(game, {}).get("max_players")
                if max_p is not None and player_count > max_p:
                    bad_games.append(f"**{game}** (max {max_p} spelers)")
            if bad_games:
                msg += (
                    f"\n⚠️ **Let op!** Met **{player_count} aanwezige spelers** vanavond "
                    f"zijn deze games mogelijk minder geschikt:\n"
                    + "\n".join(f"🚫 {g}" for g in bad_games)
                )

        await ctx.send(msg)

        # Update the RSVP embed to reflect the player's updated voting status (🎮 emoji)
        await self._update_rsvp_embed()

        # Immediately check whether this was the last missing voter
        await self.check_completion()

    @commands.command(name="pass", aliases=["dontcare", "nopref"])
    async def pass_vote(self, ctx):
        """Geef aan dat je meespeelt zonder voorkeur voor een game."""
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, stuur dit alsjeblieft in een DM! 🤫", delete_after=5
            )

        if not self.is_open:
            return await ctx.send("⛔ De stemming is momenteel gesloten.")

        await self._register_pass(ctx)

    @gamenight.command(name="pass", aliases=["dontcare", "nopref"])
    async def gn_pass_cmd(self, ctx):
        """Geef aan dat je meespeelt zonder voorkeur voor een game."""
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, stuur dit alsjeblieft in een DM! 🤫", delete_after=5
            )
        if not self.is_open:
            return await ctx.send("⛔ De stemming is momenteel gesloten.")

        await self._register_pass(ctx)

    @gamenight.command(name="skiplimit")
    @commands.is_owner()
    async def gn_skiplimit(self, ctx, value: str = None):
        """Alleen voor de eigenaar: bekijk of wijzig de maandlimiet voor passen. Gebruik een getal, 0 om te blokkeren of off voor onbeperkt."""
        if value is not None:
            value = value.strip().lower()
            if value == "off":
                limit = None
            elif value.isascii() and value.isdigit() and len(value) <= 6:
                limit = int(value)
            else:
                return await ctx.send("❌ Gebruik `!gn skiplimit <aantal>` (0–999999), of `!gn skiplimit off` voor onbeperkt passen.")
            await self.config.skip_limit.set(limit)
        limit = await self.config.skip_limit()
        status = "onbeperkt" if limit is None else f"{limit} per speler per kalendermaand"
        await ctx.send(f"🎲 Passlimiet: **{status}**. Blijft bewaard na een herstart. Eerdere passes blijven meetellen; een geaccepteerde pass in deze ronde blijft geldig.")
        if value is not None:
            await self._update_rsvp_embed()

    def _skip_rejection(self, history, today, limit=2):
        """Use the same local calendar as the game-night scheduler."""
        dates = [datetime.fromisoformat(value).date() for value in history]
        if limit is not None and sum(d.year == today.year and d.month == today.month for d in dates) >= limit:
            return f"⛔ Je maandlimiet van {limit} passes is bereikt. Stem op een game."
        return None

    async def _register_pass(self, ctx):
        """Helper to register a player as present without voting preferences."""
        if not self.is_open:
            return await ctx.send("⛔ De stemming is momenteel gesloten.")
        uid = str(ctx.author.id)
        today = datetime.now().date()
        rejection = None
        # Check and consume quota together, including repeated/concurrent commands.
        async with self._config_transaction() as data:
            limit = data["skip_limit"]
            history = data["skip_history"].setdefault(uid, [])
            if uid not in data["session_skip_users"]:
                rejection = self._skip_rejection(history, today, limit)
                if rejection is None:
                    history.append(today.isoformat())
                    data["session_skip_users"].append(uid)
            if rejection is None:
                self.votes[ctx.author.id] = ([], None)
                data["votes"] = {str(k): v for k, v in self.votes.items()}
            used = sum(value[:7] == today.strftime("%Y-%m") for value in history)
        if rejection:
            return await ctx.send(rejection)

        # Check if the player already RSVP'd
        players = await self.config.players()
        has_rsvpd = str(ctx.author.id) in players and players[str(ctx.author.id)] != "No"

        msg = (
            "🎲 **Je stem staat op 'Geen voorkeur'!**\n"
            "Je pass is geregistreerd, zonder voorkeur voor specifieke games.\n"
            "We hoeven niet meer op je stem te wachten. Veel plezier vanavond! 🥳"
        )
        allowance = "onbeperkt" if limit is None else str(limit)
        msg += f"\n\nGebruikte passes deze maand: **{used}/{allowance}**. Je stem wijzigen geeft geen pass terug."
        if not has_rsvpd:
            msg += "\n\n⚠️ *Vergeet niet je verwachte aankomsttijd te kiezen in het keuzemenu in het gameavondkanaal!*"
        else:
            msg += "\n\n*(Toch een voorkeur? Je kunt nog stemmen met `!vote Minecraft, Fortnite`)*"

        await ctx.send(msg)

        # Update the RSVP embed to reflect the player's updated voting status (🎲 emoji)
        await self._update_rsvp_embed()

        # Immediately check whether this completes all voting
        await self.check_completion()

    @gamenight.command(name="reset")
    @commands.admin_or_permissions(administrator=True)
    async def gn_reset(self, ctx):
        """Wis de huidige stemronde. Geschiedenis, passverbruik en openstaande straffen blijven bewaard."""
        self.is_open = False
        await self._clear_completion_message()
        await self._sync_penalty_warning(clear=True)
        # Reset cancels a session; it must not count as serving a veto penalty.
        await self.config.active_veto_penalties.set([])
        await self.config.penalty_warnings.set({})
        await self.config.penalty_session.set(None)
        await self.config.penalty_notice_message.set(None)
        await self.config.penalty_notice_users.set([])
        self.votes.clear()
        self.vote_message = None
        self.vote_channel = None
        self.all_voted_notified = False
        self.too_many_notified = False
        
        await self.config.is_open.set(False)
        await self.config.votes.set({})
        await self.config.session_result.set(None)
        await self.config.session_skip_users.set([])
        await self.config.smart_reminder_sent.set(False)
        await self.config.vote_message.set(None)
        await self.config.tracked_messages.set([])
        await self.config.cleanup_time.set(None)
        await self.config.reminder_time.set(None)
        self._smart_reminder_sent = False

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        await self.config.auto_close_time.set(None)
            
        await ctx.send("🧹 **De stemronde is gewist.** Geschiedenis, passverbruik en openstaande straffen blijven bewaard.")

    @gamenight.command(name="cleanup")
    @commands.admin_or_permissions(administrator=True)
    async def gn_cleanup(self, ctx, time_str: str):
        """Stel in na hoeveel tijd de stemberichten worden opgeruimd (bijvoorbeeld 1h of 30m)."""
        time_str = time_str.lower().strip()
        hours = 0.0
        
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', time_str)
        if not match:
            return await ctx.send("❌ Ongeldige invoer. Gebruik bijvoorbeeld `1h` of `30m`.")
            
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            hours = val
        elif unit == 'm':
            hours = val / 60.0
            
        await self.config.cleanup_delay_hours.set(hours)
        await ctx.send(f"⏱️ Opruimvertraging ingesteld op **{time_str}**.")

    @gamenight.command(name="remindertime")
    @commands.admin_or_permissions(administrator=True)
    async def gn_remindertime(self, ctx, time_str: str):
        """Stel de vaste herinnering na !gn open in (bijvoorbeeld 2h, 30m of 0 om uit te schakelen)."""
        time_str = time_str.lower().strip()
        
        # Allow '0' to disable the fixed reminder
        if time_str == "0":
            await self.config.reminder_delay_hours.set(0)
            await self.config.reminder_time.set(None)
            if self._reminder_task and not self._reminder_task.done():
                self._reminder_task.cancel()
            return await ctx.send("❌ De vaste herinnering is **uitgeschakeld**.")
        
        hours = 0.0
        
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', time_str)
        if not match:
            return await ctx.send("❌ Ongeldige invoer. Gebruik `2h`, `30m` of `0` om uit te schakelen.")
            
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            hours = val
        elif unit == 'm':
            hours = val / 60.0
            
        await self.config.reminder_delay_hours.set(hours)
        await ctx.send(f"⏱️ Vaste herinnering ingesteld op **{time_str}** na `!gn open`.")
    @gamenight.command(name="smartreminder")
    @commands.admin_or_permissions(administrator=True)
    async def gn_smartreminder(self, ctx, *, args: str = None):
        """Stel de slimme herinnering vóór de vroegste aankomsttijd in.
        
        Gebruik:
            !gn smartreminder 1h      — Herinner 1 uur vóór de vroegste aankomsttijd
            !gn smartreminder 30m     — Herinner 30 minuten vóór de vroegste aankomsttijd
            !gn smartreminder on      — Schakel de slimme herinnering in
            !gn smartreminder off     — Schakel de slimme herinnering uit
            !gn smartreminder         — Toon de huidige instellingen
        """
        if args is None:
            # Toon de huidige instellingen
            enabled = await self.config.smart_reminder_enabled()
            offset = await self.config.smart_reminder_offset_minutes()
            status = "✅ AAN" if enabled else "❌ UIT"
            
            if offset >= 60:
                hours = offset // 60
                mins = offset % 60
                offset_str = f"{hours}h{mins}m" if mins else f"{hours}h"
            else:
                offset_str = f"{offset}m"
            
            await ctx.send(
                f"🔔 **Slimme herinnering**\n"
                f"Status: {status}\n"
                f"Tijd vooraf: **{offset_str}** vóór de vroegste aankomsttijd\n\n"
                f"Gebruik `!gn smartreminder 1h` om de tijd vooraf in te stellen,\n"
                f"`!gn smartreminder on/off` om in of uit te schakelen."
            )
            return
        
        args = args.strip().lower()
        
        if args == "on":
            await self.config.smart_reminder_enabled.set(True)
            await self._reschedule_smart_reminder()
            return await ctx.send("✅ De slimme herinnering staat **AAN**.")
        
        if args == "off":
            await self.config.smart_reminder_enabled.set(False)
            # Cancel running smart reminder
            if self._smart_reminder_task and not self._smart_reminder_task.done():
                self._smart_reminder_task.cancel()
            return await ctx.send("❌ De slimme herinnering staat **UIT**.")
        
        # Parse time offset
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', args)
        if not match:
            return await ctx.send("❌ Ongeldige invoer. Gebruik `1h`, `30m`, `on` of `off`.")
        
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            minutes = int(val * 60)
        else:
            minutes = int(val)
        
        if minutes < 1:
            return await ctx.send("❌ De tijd vooraf moet minstens 1 minuut zijn.")
        
        await self.config.smart_reminder_offset_minutes.set(minutes)
        
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            display = f"{hours}h{mins}m" if mins else f"{hours}h"
        else:
            display = f"{minutes}m"
        
        await ctx.send(f"🔔 Slimme herinnering ingesteld op **{display}** vóór de vroegste aankomsttijd.")

        # Reschedule if a session is currently open
        if self.is_open:
            await self._reschedule_smart_reminder()

    @gamenight.command(name="remind")
    @commands.admin_or_permissions(administrator=True)
    async def gn_remind(self, ctx):
        """Stuur handmatig een stemherinnering aan alle aanwezigen die nog niet gestemd hebben."""
        if not self.is_open:
            return await ctx.send("⛔ De stemming is momenteel gesloten.")
            
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        missing_uids = await self._missing_voters(joining_players)
        
        if not missing_uids:
            return await ctx.send("✅ Niemand hoeft nog te stemmen: alle aanwezigen hebben gestemd, gepast of een deadline-straf gekregen.")
            
        pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
        embed = discord.Embed(
            title="⏳ Vergeet niet te stemmen!",
            description=(
                f"Hey {pings},\n\n"
                f"Je staat als aanwezig voor vanavond, maar hebt nog niet gestemd!\n"
                f"Stuur mij een **DM** met je keuzes, zodat we kunnen bepalen wat we spelen.\n\n"
                f"Voorbeeld: `!vote Fortnite, Palworld` 🤫"
            ),
            color=discord.Color.yellow(),
        )
        reminder_msg = await ctx.send(embed=embed)
        await self._track(reminder_msg)
        await self._track(ctx.message)
        await self._send_temporary_ping(ctx.channel, missing_uids)

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        """Bekijk hoeveel stemmen er zijn en op wie we nog wachten."""
        if not self.is_open:
            return await ctx.send("De stemming is momenteel gesloten.")

        count = len(self.votes)
        msg_text = f"🗳️ Er zijn momenteel **{count}** stemmen.\n"

        # Check who is still missing
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        if joining_players:
            missing_uids = await self._missing_voters(joining_players)
            if missing_uids:
                missing_names = []
                for uid in missing_uids:
                    user = self.bot.get_user(int(uid))
                    name = user.display_name if user else f"<@{uid}>"
                    missing_names.append(name)
                msg_text += f"\n⏳ **We wachten nog op:** {', '.join(missing_names)}"
            else:
                msg_text += "\n✅ **Alle aanwezigen hebben gestemd, gepast of een deadline-straf gekregen.**"

        await ctx.send(msg_text)

    @gamenight.command(name="history")
    async def gn_history(self, ctx):
        """Bekijk welke games de meeste stemrondes hebben gewonnen."""
        stats = await self.config.game_wins()
        sessions = await self.config.total_sessions()

        if not stats:
            return await ctx.send("Er is nog geen geschiedenis beschikbaar.")

        sorted_stats = sorted(stats.items(), key=lambda item: item[1], reverse=True)

        embed = discord.Embed(title="📜 Geschiedenis van gameavonden", color=discord.Color.purple())
        desc = f"*Totaal aantal rondes: {sessions}*\n\n"

        for i, (game, wins) in enumerate(sorted_stats, 1):
            if i == 1:
                icon = "👑"
            elif i == 2:
                icon = "🥈"
            elif i == 3:
                icon = "🥉"
            else:
                icon = "🔹"
            desc += f"{icon} **{game}**: {wins}x gewonnen\n"
            if i >= 10:
                break

        embed.description = desc
        await ctx.send(embed=embed)

    def _calculate_result(self, votes, players, weighted_mode, penalized_users=()):
        """Build a result without changing votes or history; explicitly absent users are excluded."""
        eligible_votes = {
            uid: vote for uid, vote in votes.items()
            if players.get(str(uid)) != "No"
        }
        scores = defaultdict(int)
        vote_counts = defaultdict(int)
        veto_counts = defaultdict(int)
        for uid, (pos_games, neg_game) in eligible_votes.items():
            for i, game in enumerate(pos_games):
                points = (2 if i == 0 and str(uid) in penalized_users else 3 - i) if weighted_mode else 1
                scores[game] += points
                vote_counts[game] += 1

            if neg_game and str(uid) not in penalized_users:
                scores[neg_game] -= 1
                veto_counts[neg_game] += 1

        # Sort priority:
        # 1. Total score (highest points first)
        # 2. Number of positive voters (e.g. 2x 1pt beats 1x 2pt because more people want it)
        # 3. Fewest vetoes/downvotes (-veto_counts)
        sorted_games = sorted(
            scores.items(),
            key=lambda item: (item[1], vote_counts[item[0]], -veto_counts[item[0]]),
            reverse=True
        )

        potential_winners = []
        if sorted_games:
            best_game, best_score = sorted_games[0]
            best_tuple = (best_score, vote_counts[best_game], -veto_counts[best_game])
            potential_winners = [
                g for g, s in sorted_games
                if (s, vote_counts[g], -veto_counts[g]) == best_tuple
            ]
        return {
            "ranking": [[game, score, vote_counts[game], veto_counts[game]]
                        for game, score in sorted_games],
            "potential_winners": potential_winners,
            "winner": None,
            "total": len(eligible_votes),
            "voted": sum(1 for p, n in eligible_votes.values() if p or n),
        }

    async def _show_results(self, channel: discord.abc.Messageable, *, finalize=False):
        """Finalize once on close; subsequent requests display the saved result."""
        # Commit the result and history together before sending Discord messages.
        # This also serializes concurrent results requests and survives a reload.
        async with self._config_transaction() as data:
            saved_result = data["session_result"]
            result = json.loads(saved_result) if saved_result else None
            if not result:
                result = self._calculate_result(self.votes, data["players"], data["weighted_mode"],
                                                data["active_veto_penalties"])
                if finalize:
                    candidates = result["potential_winners"]
                    if candidates:
                        result["winner"] = random.choice(candidates) if len(candidates) > 1 else candidates[0]
                        winner = result["winner"]
                        data["game_wins"][winner] = data["game_wins"].get(winner, 0) + 1
                        data["total_sessions"] += 1
                    data["session_result"] = json.dumps(result)

        if not result["ranking"]:
            text = ("🎲 Iedereen heeft gepast. Er is geen winnende game gekozen."
                    if result["total"] else "Geen stemmen ontvangen van aanwezige spelers.")
            await self._track(await channel.send(text))
            return

        title = "🏆 De uitslag" if result["winner"] else "🗳️ Tussenstand (nog niet definitief)"
        embed = discord.Embed(title=title, color=discord.Color.gold())
        desc = ""
        for i, (game, score, pos_votes, neg_votes) in enumerate(result["ranking"], 1):

            emoji = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"**#{i}**"

            vote_text = f"{pos_votes} positief"
            if neg_votes > 0:
                vote_text += f", {neg_votes} negatief 💀"

            desc += f"{emoji} **{game}**\n╚ **{score} punten** ({vote_text})\n\n"
            if i >= 10:
                break

        embed.description = desc
        voted_count = result["voted"]
        total = result["total"]
        passed_count = total - voted_count
        if passed_count > 0:
            embed.set_footer(text=f"Totaal: {total} spelers ({voted_count} gestemd, {passed_count} 🎲 geen voorkeur)")
        else:
            embed.set_footer(text=f"Totaal: {total} stemmers.")
        results_msg = await channel.send(embed=embed)
        await self._track(results_msg)

        final_winner = result["winner"]
        if final_winner is None:
            return
        if len(result["potential_winners"]) > 1:
            embed_tie = discord.Embed(
                title="🎰 LOTING BIJ GELIJKSPEL",
                description=f"Het rad stopt op...\n# **🎉 {final_winner} 🎉**",
                color=discord.Color.red(),
            )
            tie_result_msg = await channel.send(embed=embed_tie)
            await self._track(tie_result_msg)
        else:
            winner_msg = await channel.send(f"🎉 De winnaar is: **{final_winner}**!")
            await self._track(winner_msg)

    @gamenight.command(name="results")
    @commands.admin_or_permissions(administrator=True)
    async def gn_results(self, ctx):
        """Bekijk de tussenstand of de opgeslagen definitieve uitslag."""
        await self._show_results(ctx.channel)

    # ── Auto-Open Loop ──────────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def _auto_open_loop(self):
        """Background loop that checks every 30 seconds if it's time to auto-open the vote."""
        try:
            enabled = await self.config.auto_open_enabled()
            if not enabled:
                return

            # Don't auto-open if a session is already open
            if self.is_open:
                return

            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Already auto-opened today?
            if self._auto_opened_date == today_str:
                return

            # Check if today is an auto-open day (0=Monday ... 6=Sunday)
            auto_days = await self.config.auto_open_days()
            if now.weekday() not in auto_days:
                return

            # Check if current time >= the configured auto-open time
            auto_time_str = await self.config.auto_open_time()
            try:
                target_hour, target_minute = map(int, auto_time_str.split(":"))
            except (ValueError, AttributeError):
                return

            target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now < target_dt:
                return

            # All conditions met — auto-open!
            channel_id = await self.config.auto_open_channel_id()
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    return

            self._auto_opened_date = today_str
            await self.config.auto_opened_date.set(today_str)
            await self._do_open_vote(channel)
        except Exception as e:
            print(f"[GameNight] Auto-open loop error: {e}")

    @_auto_open_loop.before_loop
    async def _before_auto_open_loop(self):
        """Wait until the bot is ready before starting the auto-open loop."""
        await self.bot.wait_until_ready()

    # ── Auto-Open Commands ──────────────────────────────────────────────
    @gamenight.group(name="autoopen", invoke_without_command=True)
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen(self, ctx):
        """Toon de instellingen voor automatisch openen."""
        enabled = await self.config.auto_open_enabled()
        auto_time = await self.config.auto_open_time()
        channel_id = await self.config.auto_open_channel_id()
        auto_days = await self.config.auto_open_days()

        status = "✅ AAN" if enabled else "❌ UIT"

        day_names = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
        days_str = ", ".join(day_names[d] for d in sorted(auto_days)) if auto_days else "Geen"

        if channel_id:
            channel = self.bot.get_channel(channel_id)
            channel_str = channel.mention if channel else f"ID: {channel_id} (niet gevonden)"
        else:
            channel_str = "**Niet ingesteld** — gebruik `!gn autoopen channel #kanaal`"

        embed = discord.Embed(
            title="⏰ Instellingen voor automatisch openen",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Tijd", value=f"**{auto_time}**", inline=True)
        embed.add_field(name="Dagen", value=days_str, inline=False)
        embed.add_field(name="Kanaal", value=channel_str, inline=False)
        embed.set_footer(text="Gebruik !gn autoopen on/off/time/channel om de instellingen te wijzigen.")

        await ctx.send(embed=embed)

    @gn_autoopen.command(name="on")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_on(self, ctx):
        """Schakel automatisch openen in."""
        channel_id = await self.config.auto_open_channel_id()
        if not channel_id:
            return await ctx.send(
                "❌ Stel eerst een kanaal in met `!gn autoopen channel #kanaal` "
                "voordat je automatisch openen inschakelt."
            )
        await self.config.auto_open_enabled.set(True)
        auto_time = await self.config.auto_open_time()
        await ctx.send(f"✅ Automatisch openen staat **AAN**. De stemming opent automatisch om **{auto_time}**.")

    @gn_autoopen.command(name="off")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_off(self, ctx):
        """Schakel automatisch openen uit."""
        await self.config.auto_open_enabled.set(False)
        await ctx.send("❌ Automatisch openen staat **UIT**.")

    @gn_autoopen.command(name="time")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_time(self, ctx, time_str: str):
        """Stel het tijdstip voor automatisch openen in (UU:MM, bijvoorbeeld 18:00 of 19:30)."""
        match = re.match(r'^(\d{1,2}):(\d{2})$', time_str.strip())
        if not match:
            return await ctx.send("❌ Ongeldige invoer. Gebruik `UU:MM`, bijvoorbeeld `18:00` of `19:30`.")

        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return await ctx.send("❌ Ongeldige tijd. Uren moeten 0–23 zijn, minuten 0–59.")

        formatted = f"{hour:02d}:{minute:02d}"
        await self.config.auto_open_time.set(formatted)
        await ctx.send(f"⏰ Automatisch openen ingesteld op **{formatted}**.")

    @gn_autoopen.command(name="channel")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_channel(self, ctx, channel: discord.TextChannel):
        """Stel het kanaal in waarin de stemming automatisch wordt geopend."""
        await self.config.auto_open_channel_id.set(channel.id)
        await ctx.send(f"📢 Kanaal voor automatisch openen ingesteld op {channel.mention}.")

    # ── Debug Time Command ──────────────────────────────────────────────
    @gamenight.command(name="debugtime")
    @commands.admin_or_permissions(administrator=True)
    async def gn_debugtime(self, ctx):
        """Toon informatie over de tijdzone en planning voor probleemoplossing."""
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        utc_offset = now_local - now_utc.replace(tzinfo=None)
        offset_hours = utc_offset.total_seconds() / 3600

        # Format offset as +HH:MM
        sign = "+" if offset_hours >= 0 else "-"
        abs_hours = int(abs(offset_hours))
        abs_mins = int((abs(offset_hours) - abs_hours) * 60)
        offset_str = f"{sign}{abs_hours:02d}:{abs_mins:02d}"

        day_names = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
        today_name = day_names[now_local.weekday()]

        # Auto-open info
        enabled = await self.config.auto_open_enabled()
        auto_time = await self.config.auto_open_time()
        auto_days = await self.config.auto_open_days()
        auto_days_str = ", ".join(day_names[d] for d in sorted(auto_days)) if auto_days else "Geen"
        is_auto_day = now_local.weekday() in auto_days

        # Calculate next auto-open
        next_open_str = "Uitgeschakeld"
        if enabled and auto_days:
            try:
                target_h, target_m = map(int, auto_time.split(":"))
                # Find the next occurrence
                check = now_local.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
                # If today is an auto-day and the time hasn't passed yet, it's today
                if now_local.weekday() in auto_days and now_local < check:
                    next_open_str = f"{today_name} {auto_time} (vandaag)"
                else:
                    # Search the next 7 days
                    for i in range(1, 8):
                        future = now_local + timedelta(days=i)
                        if future.weekday() in auto_days:
                            future_name = day_names[future.weekday()]
                            future_date = future.strftime("%Y-%m-%d")
                            next_open_str = f"{future_name} {auto_time} ({future_date})"
                            break
            except (ValueError, AttributeError):
                next_open_str = "⚠️ Kan niet berekenen (ongeldige auto_open_time)"

        embed = discord.Embed(
            title="🕵️ Diagnose: tijd en tijdzone",
            color=discord.Color.greyple(),
        )
        embed.add_field(
            name="🕐 Tijden",
            value=(
                f"**UTC:** {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Lokaal:** {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Tijdsverschil:** UTC{offset_str}"
            ),
            inline=False,
        )
        embed.add_field(
            name="📅 Dag",
            value=(
                f"**Vandaag:** {today_name} (weekday={now_local.weekday()})\n"
                f"**Dag voor automatisch openen?** {'✅ Ja' if is_auto_day else '❌ Nee'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="⏰ Automatisch openen",
            value=(
                f"**Ingeschakeld:** {'✅' if enabled else '❌'}\n"
                f"**Tijd:** {auto_time}\n"
                f"**Dagen:** {auto_days_str}\n"
                f"**Vandaag al geopend?** {'Ja' if self._auto_opened_date == now_local.strftime('%Y-%m-%d') else 'Nee'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="📌 Volgende automatische opening",
            value=next_open_str,
            inline=False,
        )
        embed.add_field(
            name="🔧 Systeeminformatie",
            value=(
                f"**time.tzname:** {time.tzname}\n"
                f"**time.timezone:** {time.timezone} sec ({time.timezone / 3600:.1f}h)\n"
                f"**time.daylight:** {time.daylight}"
            ),
            inline=False,
        )
        embed.set_footer(text="Als het tijdsverschil niet klopt, draait de bot mogelijk in de verkeerde tijdzone.")

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(GameNight(bot))
