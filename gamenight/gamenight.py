from redbot.core import commands, Config
from collections import defaultdict
import discord
from discord.ext import tasks
import re
import difflib
import asyncio
import random
import time
import logging
from datetime import datetime, timedelta, timezone

from .games import GAMES  # Separate game list

log = logging.getLogger("red.gamenight")

class RSVPView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        custom_id="gn_rsvp_select",
        placeholder="When will you be online?",
        options=[
            discord.SelectOption(label="Earlier (Before 20:00)", emoji="🕰️", value="Earlier"),
            discord.SelectOption(label="20:00", emoji="🕗", value="20:00"),
            discord.SelectOption(label="20:30", emoji="🕣", value="20:30"),
            discord.SelectOption(label="21:00", emoji="🕘", value="21:00"),
            discord.SelectOption(label="21:30", emoji="🕤", value="21:30"),
            discord.SelectOption(label="22:00", emoji="🕙", value="22:00"),
            discord.SelectOption(label="22:30", emoji="🕥", value="22:30"),
            discord.SelectOption(label="23:00", emoji="🕚", value="23:00"),
            discord.SelectOption(label="Later (After 23:00)", emoji="🦉", value="Later"),
            discord.SelectOption(label="Not joining today", emoji="❌", value="No")
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
                        "⚠️ Game Night plugin is not loaded.", ephemeral=True
                    )
        except discord.errors.InteractionResponded:
            pass  # Already responded — safe to ignore
        except Exception as e:
            # Catch-all: make sure Discord always gets a response to avoid "interaction failed"
            log.exception("RSVP callback failed (interaction=%s)", interaction.id)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Something went wrong. Please try again.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "⚠️ Something went wrong. Please try again.", ephemeral=True
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
        label="Close Vote",
        style=discord.ButtonStyle.success,
        emoji="🛑"
    )
    async def close_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Only admins can close
            if not interaction.user.guild_permissions.administrator:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⛔ Only admins can close the vote.", ephemeral=True
                    )
                return

            active_cog = self.cog.bot.get_cog("GameNight")
            if active_cog is None:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Game Night plugin is not loaded.", ephemeral=True
                    )
                return

            if not active_cog.is_open:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⛔ Voting is already closed.", ephemeral=True
                    )
                return

            # Defer since close + results takes time
            if not interaction.response.is_done():
                await interaction.response.defer()

            # Disable the button on the message
            button.disabled = True
            button.label = "Vote Closed ✅"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            # Close the vote using shared logic
            await active_cog._do_close_vote(interaction.channel)

        except discord.errors.InteractionResponded:
            pass
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Something went wrong. Please try again.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "⚠️ Something went wrong. Please try again.", ephemeral=True
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
    """The Ultimate Game Night Plugin: Clean, Secret & Stats."""

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
            "session_result": None,
            "skip_history": {},
            "skip_limit": 2,
            "session_skip_users": [],
            "penalty_session": None,
            "penalty_warnings": {},
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
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                acknowledged = True
            except discord.InteractionResponded:
                acknowledged = True
            except (discord.HTTPException, asyncio.TimeoutError):
                log.exception("RSVP acknowledgement failed (interaction=%s, age=%.2fs)",
                              interaction.id,
                              (datetime.now(timezone.utc) - interaction.created_at).total_seconds())

        saved = False
        try:
            if not self.is_open:
                if acknowledged:
                    await interaction.edit_original_response(content="Voting is currently closed.")
                return
                
            async with self.config.players() as players:
                players[str(interaction.user.id)] = time_val
                if time_val == "No":
                    msg = "❌ You are marked as **not joining** today."
                else:
                    msg = f"✅ You are marked as playing at **{time_val}**!"
                    
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
                    ("⚠️ Your RSVP was saved, but the display could not be updated."
                     if saved else "⚠️ Your RSVP could not be saved. Please try again."), ephemeral=True
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
            rule = ("Skipping: unlimited." if limit is None else
                    f"Skipping: max {limit} sessions per calendar month.")
            if embed.description:
                embed.description = re.sub(r"Skipping: [^\n]*", rule, embed.description)
            
            # Rebuild the fields
            embed.clear_fields()
            embed.add_field(
                name="Are you gaming tonight?",
                value="Select your expected time in the dropdown below.\nSelect ❌ if you can't make it.",
                inline=False,
            )
            embed.add_field(
                name="⚠️ Vote deadline & veto penalty",
                value=("Vote by **10 minutes before the earliest start**. Watch for your warning and exact deadline.\n"
                       "Missing it means **no negative vote next game night you attend**. Positive votes stay available.\n"
                       "An accepted `!pass` counts. No automatic skip is charged."),
                inline=False,
            )
            
            joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
            absent_players = {uid: t_val for uid, t_val in players.items() if t_val == "No"}
            
            if joining_players:
                # Format player list
                player_lines = []
                for uid, t_val in joining_players.items():
                    has_voted = int(uid) in self.votes
                    if has_voted:
                        pos, neg = self.votes[int(uid)]
                        status_emoji = "🎲" if (not pos and not neg) else "🎮"
                    else:
                        status_emoji = "❓"
                    player_lines.append(f"• <@{uid}> - {t_val} {status_emoji}")
                    
                embed.add_field(
                    name=f"🎮 Players & ETA ({len(joining_players)})",
                    value="\n".join(player_lines),
                    inline=False
                )
                
            if absent_players:
                # Format absent player list
                absent_lines = []
                for uid in absent_players.keys():
                    absent_lines.append(f"• <@{uid}>")
                    
                embed.add_field(
                    name=f"❌ Not Joining ({len(absent_players)})",
                    value="\n".join(absent_lines),
                    inline=False
                )
                
            self.vote_message = await msg.edit(embed=embed)
        except Exception as e:
            log.exception("Could not update RSVP message")

    async def cog_load(self):
        """Restore state from config when the bot reboots."""
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
        await self.config.is_open.set(False)
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
        missing_uids = [uid for uid in joining_players.keys() if int(uid) not in self.votes]
        
        if missing_uids:
            pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
            embed = discord.Embed(
                title="⏳ Voting Reminder!",
                description=(
                    f"Hey {pings},\n\n"
                    f"You have RSVP'd for game night tonight but haven't submitted your votes yet!\n"
                    f"Please send me a **DM** with your choices so we can decide what to play.\n\n"
                    f"Example: `!vote Fortnite, Palworld` 🤫"
                ),
                color=discord.Color.yellow(),
            )
            reminder_msg = await channel.send(embed=embed)
            await self._track(reminder_msg)
            
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
        missing_uids = [uid for uid in joining_players.keys() if int(uid) not in self.votes]
        
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
                offset_text = f"{hours} hour(s)"
        else:
            offset_text = f"{offset_minutes} minutes"
        
        pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
        embed = discord.Embed(
            title="🔔 Game Night is starting soon!",
            description=(
                f"Hey {pings},\n\n"
                f"The first player is expected at **{earliest_str}** — that's in **{offset_text}**!\n"
                f"You've RSVP'd but haven't **picked your games** yet.\n\n"
                f"Send me a **DM** with your choices:\n"
                f"Example: `!vote Fortnite, Palworld` 🤫"
            ),
            color=discord.Color.orange(),
        )
        reminder_msg = await channel.send(embed=embed)
        self._smart_reminder_sent = True
        await self.config.smart_reminder_sent.set(True)
        await self._track(reminder_msg)

    def _veto_blocked_embed(self):
        return discord.Embed(
            title="🔒 No negative vote this game night",
            description=("You missed a voting deadline on a previous game night.\n\n"
                         "**You can still vote for games:** `!vote Fortnite, Minecraft`\n"
                         "Your `# Game` negative vote is unavailable this session. "
                         "Remove it and send your vote again.\n\n"
                         "Your veto returns after this session if you attend, unless you miss another deadline."),
            color=discord.Color.red(),
        )

    async def _finish_veto_penalties(self, channel):
        """Serve a penalty only during a later session in which the user attends."""
        restored = []
        async with self.config.all() as data:
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
                title="✅ Veto restored",
                description=("Your one-session penalty is complete. You may use a negative vote "
                             "again next game night, when veto mode is enabled."),
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
            async with self._close_lock:
                await self._check_vote_deadlines()
        except Exception:
            log.exception("Vote deadline check failed")

    @_penalty_loop.before_loop
    async def _before_penalty_loop(self):
        await self.bot.wait_until_ready()

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
            return
        # Keep clock-only RSVPs anchored to the day this session opened, including after reboot.
        opened = datetime.fromtimestamp(int(data["penalty_session"]) / 1_000_000_000)
        earliest = earliest.replace(year=opened.year, month=opened.month, day=opened.day)
        now = time.time()
        if now < earliest.timestamp() - 30 * 60:
            return
        for uid, eta in players.items():
            if eta == "No" or int(uid) in self.votes:
                continue
            if data["veto_penalties"].get(uid) == data["penalty_session"]:
                continue
            warning = data["penalty_warnings"].get(uid)
            target = earliest.timestamp() - 10 * 60
            # Never bring a previously announced deadline forward. Moving the start
            # later extends it and triggers an updated warning.
            if warning is None or target > warning:
                deadline = max(target, now + 10 * 60)
                embed = discord.Embed(
                    title="⚠️ Vote now — your next veto is at risk",
                    description=(f"You are marked as attending, but have **not voted**.\n\n"
                                 f"**Your deadline: <t:{int(deadline)}:t> (<t:{int(deadline)}:R>)**\n"
                                 f"Earliest start: <t:{int(earliest.timestamp())}:t>.\n\n"
                                 "Send a DM: `!vote Fortnite, Minecraft`. An accepted `!pass` also counts, "
                                 "within your monthly limit. If you cannot attend, select **Not joining today**.\n\n"
                                 "**Still no vote at the deadline?** You lose your negative vote (`# Game`) "
                                 "on the **next game night you attend**. Positive votes remain available. "
                                 "No automatic skip is charged."),
                    color=discord.Color.orange(),
                )
                sent = await channel.send(content=f"<@{uid}>", embed=embed,
                                          allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                async with self.config.penalty_warnings() as warnings:
                    warnings[uid] = deadline
                await self._track(sent)
            elif now >= warning:
                # Recheck after any network awaits; a vote or withdrawal wins the race.
                async with self.config.all() as current:
                    if (not self.is_open or current["players"].get(uid) == "No"
                            or int(uid) in self.votes):
                        continue
                    current["veto_penalties"][uid] = current["penalty_session"]
                embed = discord.Embed(
                    title="🔒 Deadline missed — next veto suspended",
                    description=("You were marked as attending and did not vote before your warned deadline.\n\n"
                                 "**Next game night you attend: no negative vote (`# Game`).**\n"
                                 "You can still play and vote positively. Your veto returns after that session "
                                 "unless you miss another deadline.\n\n"
                                 "You may still submit a vote tonight, but this does not cancel the penalty. "
                                 "**No skip was deducted.**"),
                    color=discord.Color.red(),
                )
                await self._track(await channel.send(content=f"<@{uid}>", embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)))

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

    async def check_completion(self):
        """Checks whether everyone who has an ETA has actually voted.
        Also sends a warning when more than TOO_MANY_PLAYERS_THRESHOLD players are present.
        """
        if not self.is_open:
            return

        channel, msg = await self._get_or_restore_vote_message()
        if not msg or not channel:
            return

        try:
            players = await self.config.players()
            joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
            player_count = len(joining_players)

            # ── "Too many players" warning ──────────────────────────────────
            if player_count > TOO_MANY_PLAYERS_THRESHOLD:
                if not self.too_many_notified:
                    self.too_many_notified = True
                    embed = discord.Embed(
                        title="⚠️ A lot of players tonight!",
                        description=(
                            f"There are now **{player_count} players** marked as present.\n"
                            f"Games that only support **{TOO_MANY_PLAYERS_THRESHOLD} players** "
                            f"are now **a bad idea**. 🚫\n\n"
                            "Keep player limits in mind when voting!"
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
                self.all_voted_notified = False
                return

            # Check who is still missing a vote
            missing = [uid for uid in joining_players.keys() if int(uid) not in self.votes]

            if not missing:
                # Everyone has voted — send the notification (only once)
                if not self.all_voted_notified:
                    self.all_voted_notified = True

                    # Clean up old all_voted notification if one was sent previously
                    if self._all_voted_msg:
                        try:
                            await self._all_voted_msg.delete()
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                        self._all_voted_msg = None

                    embed = discord.Embed(
                        title="🎉 All votes are in!",
                        description="Everyone who RSVP'd has voted.\nClick the button below to close voting and see the results!",
                        color=discord.Color.green(),
                    )
                    all_voted_msg = await channel.send(embed=embed, view=CloseVoteView(self))
                    self._all_voted_msg = all_voted_msg
                    await self._track(all_voted_msg)
            else:
                # Someone new clicked ✅ or has not voted yet — disable any existing close button
                if self.all_voted_notified:
                    self.all_voted_notified = False
                    if self._all_voted_msg:
                        try:
                            await self._all_voted_msg.edit(view=None)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                        self._all_voted_msg = None

        except discord.NotFound:
            pass  # Message was deleted
        except Exception as e:
            print(f"Error checking completion: {e}")



    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        current = await self.config.weighted_mode()
        await self.config.weighted_mode.set(not current)
        status = "**ON** (3-2-1)" if not current else "**OFF** (1-1-1)"
        await ctx.send(f"⚖️ Bonus point system is now {status}.")

    @gamenight.command(name="veto")
    @commands.admin_or_permissions(administrator=True)
    async def gn_veto(self, ctx):
        current = await self.config.veto_mode()
        await self.config.veto_mode.set(not current)
        status = "**ENABLED** 💀" if not current else "**DISABLED** ☮️"
        await ctx.send(f"🛡️ Veto Mode is now {status}.")

    async def _do_open_vote(self, channel: discord.TextChannel, trigger_message: discord.Message = None):
        """Shared logic to open a new voting session in the given channel.
        
        Parameters
        ----------
        channel : discord.TextChannel
            The channel to post the voting embed in.
        trigger_message : discord.Message, optional
            The command message that triggered the open (tracked for cleanup).
        """
        await self._finish_veto_penalties(channel)
        async with self.config.all() as data:
            data["penalty_session"] = str(time.time_ns())
            data["penalty_warnings"] = {}
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
        skip_rule = ("Skipping: unlimited." if skip_limit is None else
                     f"Skipping: max {skip_limit} sessions per calendar month.")

        rules = "🥇 3 pts | 🥈 2 pts | 🥉 1 pt" if weighted else "Every positive vote is 1 point."

        if veto:
            veto_text = "\n💀 **VETO ENABLED:** use `#` to downvote a game (-1 pt)."
            example = "`!vote Game1, Game2, Game3 # BadGame`"
        else:
            veto_text = ""
            example = "`!vote Game1, Game2, Game3`"

        embed = discord.Embed(
            title="🎮 Game Night Voting Open!",
            description=f"Send me a **DM** with your choices.\nExample: {example}\nNo preference? Send `!pass` or `!vote pass` 🎲\n{skip_rule}\n\n{rules}{veto_text}",
            color=discord.Color.green(),
        )
        # The RSVP question
        embed.add_field(
            name="Are you gaming tonight?",
            value="Select your expected time in the dropdown below.\nSelect ❌ if you can't make it.",
            inline=False,
        )
        embed.add_field(
            name="⚠️ Vote on time — protect your veto",
            value=("Joining? Vote before **10 minutes before the earliest start time**.\n"
                   "A warning is sent 30 minutes before the start. Late arrivals get at least 10 minutes after their warning.\n"
                   "No vote by your deadline? You lose your **negative vote next game night you attend**. "
                   "Positive votes remain available. An accepted `!pass` counts; no automatic skip is charged."),
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
        await self._do_open_vote(ctx.channel, trigger_message=ctx.message)

    async def _do_close_vote(self, channel: discord.TextChannel):
        """Shared logic for closing a vote session (used by !gn close and the Close Vote button)."""
        async with self._close_lock:
            if not self.is_open:
                return

            self.is_open = False
            await self.config.is_open.set(False)
            self.all_voted_notified = False
            self.too_many_notified = False

            # Remove view from the "all votes in" message if still present
            if self._all_voted_msg:
                try:
                    await self._all_voted_msg.edit(view=None)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                self._all_voted_msg = None
            
            # Remove view from vote message to prevent further RSVPs
            vote_channel, msg = await self._get_or_restore_vote_message()
            if msg:
                try:
                    await msg.edit(view=None)
                except discord.NotFound:
                    pass
                    
            closing_msg = await channel.send("🛑 **Voting is closed!** calculating results...")
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
        if not self.is_open:
            return await ctx.send("⛔ Voting is already closed.")
        await self._track(ctx.message)  # Track the !gn close command itself
        await self._do_close_vote(ctx.channel)

    @commands.command()
    async def vote(self, ctx, *, games_input: str):
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, please send this in a DM! 🤫", delete_after=5
            )

        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")

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

        pos_input = games_input
        neg_input = None

        if "#" in games_input:
            if not veto_enabled:
                return await ctx.send("⛔ Veto mode is disabled. You cannot use `#` today.")
            if str(ctx.author.id) in await self.config.active_veto_penalties():
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
            return await ctx.send("I found no valid games. Usage: `!vote Game1, Game2 # BadGame`")

        self.votes[ctx.author.id] = (clean_pos_games, clean_neg_game)
        await self.config.votes.set({str(k): v for k, v in self.votes.items()})

        msg = "✅ **Votes Received!**\n"
        if corrections:
            msg += "\n🪄 *Autocorrect:* " + ", ".join(corrections) + "\n\n"

        msg += "**Your list:**\n"
        for i, game in enumerate(clean_pos_games):
            if weighted_mode:
                points = 3 - i
                msg += f"#{i+1} **{game}** (+{points} pts)\n"
            else:
                msg += f"- **{game}** (+1 pt)\n"

        if clean_neg_game:
            msg += f"💀 **{clean_neg_game}** (-1 pt)\n"

        # ── Personal warning: flag games that don't fit the current group size ──
        player_count = await self._get_rsvp_count()
        if player_count is not None and player_count > 0:
            bad_games = []
            for game in clean_pos_games:
                max_p = GAMES.get(game, {}).get("max_players")
                if max_p is not None and player_count > max_p:
                    bad_games.append(f"**{game}** (max {max_p} players)")
            if bad_games:
                msg += (
                    f"\n⚠️ **Heads up!** With **{player_count} players** present tonight, "
                    f"these votes might not be a great idea:\n"
                    + "\n".join(f"🚫 {g}" for g in bad_games)
                )

        await ctx.send(msg)

        # ── Late vote: notify the channel if "all votes in" was already announced ──
        if self.all_voted_notified and self.vote_channel:
            self.all_voted_notified = False  # Reset so it fires again once everyone is done
            total_votes = len(self.votes)
            embed = discord.Embed(
                title="🔄 Vote count updated!",
                description=(
                    f"**{ctx.author.display_name}** just submitted a vote after the "
                    f"\"all votes in\" notification.\n"
                    f"Total votes received: **{total_votes}**\n\n"
                    "Hold off on `!gn close` — waiting for everyone to be done again."
                ),
                color=discord.Color.yellow(),
            )
            late_msg = await self.vote_channel.send(embed=embed)
            await self._track(late_msg)

        # Update the RSVP embed to reflect the player's updated voting status (🎮 emoji)
        await self._update_rsvp_embed()

        # Immediately check whether this was the last missing voter
        await self.check_completion()

    @commands.command(name="pass", aliases=["dontcare", "nopref"])
    async def pass_vote(self, ctx):
        """Register that you are playing but don't care what game is played."""
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, please send this in a DM! 🤫", delete_after=5
            )

        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")

        await self._register_pass(ctx)

    @gamenight.command(name="pass", aliases=["dontcare", "nopref"])
    async def gn_pass_cmd(self, ctx):
        """Register that you are playing but don't care what game is played."""
        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")

        await self._register_pass(ctx)

    @gamenight.command(name="skiplimit")
    @commands.is_owner()
    async def gn_skiplimit(self, ctx, value: str = None):
        """Owner only: show/set monthly skips. Use a number, 0 to block, or off for unlimited."""
        if value is not None:
            value = value.strip().lower()
            if value == "off":
                limit = None
            elif value.isascii() and value.isdigit() and len(value) <= 6:
                limit = int(value)
            else:
                return await ctx.send("❌ Use `!gn skiplimit <number>` (0–999999), or `!gn skiplimit off` for unlimited skips.")
            await self.config.skip_limit.set(limit)
        limit = await self.config.skip_limit()
        status = "unlimited" if limit is None else f"{limit} per player per calendar month"
        await ctx.send(f"🎲 Skip limit: **{status}**. Saved across reboots. Previous skips still count; an accepted skip in the current session remains valid.")
        if value is not None:
            await self._update_rsvp_embed()

    def _skip_rejection(self, history, today, limit=2):
        """Use the same local calendar as the game-night scheduler."""
        dates = [datetime.fromisoformat(value).date() for value in history]
        if limit is not None and sum(d.year == today.year and d.month == today.month for d in dates) >= limit:
            return f"⛔ Your monthly skip limit is {limit} and has been reached. Please vote for a game."
        return None

    async def _register_pass(self, ctx):
        """Helper to register a player as present without voting preferences."""
        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")
        uid = str(ctx.author.id)
        today = datetime.now().date()
        rejection = None
        # Check and consume quota together, including repeated/concurrent commands.
        async with self.config.all() as data:
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
            "🎲 **Your vote is set to 'No preference / Don't care'!**\n"
            "You are counted as attending, but haven't voted for specific games.\n"
            "We won't have to wait for your vote anymore. Have fun tonight! 🥳"
        )
        allowance = "unlimited" if limit is None else str(limit)
        msg += f"\n\nSkips used this month: **{used}/{allowance}**. Changing your vote does not refund a skip."
        if not has_rsvpd:
            msg += "\n\n⚠️ *Don't forget to select your expected arrival time in the gamenight channel dropdown!*"
        else:
            msg += "\n\n*(Change your mind? You can still submit votes anytime with `!vote Game1, Game2`)*"

        await ctx.send(msg)

        # Update the RSVP embed to reflect the player's updated voting status (🎲 emoji)
        await self._update_rsvp_embed()

        # Immediately check whether this completes all voting
        await self.check_completion()

    @gamenight.command(name="reset")
    @commands.admin_or_permissions(administrator=True)
    async def gn_reset(self, ctx):
        """Reset the current voting session completely."""
        self.is_open = False
        # Reset cancels a session; it must not count as serving a veto penalty.
        await self.config.active_veto_penalties.set([])
        await self.config.penalty_warnings.set({})
        await self.config.penalty_session.set(None)
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

        if self._all_voted_msg:
            try:
                await self._all_voted_msg.edit(view=None)
            except Exception:
                pass
            self._all_voted_msg = None
        
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        await self.config.auto_close_time.set(None)
            
        await ctx.send("🧹 **Gamenight has been fully reset.** (Game history remains intact).")

    @gamenight.command(name="cleanup")
    @commands.admin_or_permissions(administrator=True)
    async def gn_cleanup(self, ctx, time_str: str):
        """Set how long before voting messages are deleted (e.g. 1h, 30m)."""
        time_str = time_str.lower().strip()
        hours = 0.0
        
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', time_str)
        if not match:
            return await ctx.send("❌ Invalid format. Please use something like `1h` or `30m`.")
            
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            hours = val
        elif unit == 'm':
            hours = val / 60.0
            
        await self.config.cleanup_delay_hours.set(hours)
        await ctx.send(f"⏱️ Cleanup delay updated to **{time_str}**.")

    @gamenight.command(name="remindertime")
    @commands.admin_or_permissions(administrator=True)
    async def gn_remindertime(self, ctx, time_str: str):
        """Set how long after !gn open the fixed reminder fires (e.g. 2h, 30m, 0 to disable)."""
        time_str = time_str.lower().strip()
        
        # Allow '0' to disable the fixed reminder
        if time_str == "0":
            await self.config.reminder_delay_hours.set(0)
            await self.config.reminder_time.set(None)
            if self._reminder_task and not self._reminder_task.done():
                self._reminder_task.cancel()
            return await ctx.send("❌ Fixed reminder is now **disabled**.")
        
        hours = 0.0
        
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', time_str)
        if not match:
            return await ctx.send("❌ Invalid format. Use e.g. `2h`, `30m`, or `0` to disable.")
            
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            hours = val
        elif unit == 'm':
            hours = val / 60.0
            
        await self.config.reminder_delay_hours.set(hours)
        await ctx.send(f"⏱️ Fixed reminder set to **{time_str}** after `!gn open`.")
    @gamenight.command(name="smartreminder")
    @commands.admin_or_permissions(administrator=True)
    async def gn_smartreminder(self, ctx, *, args: str = None):
        """Configure the smart reminder that fires before the earliest RSVP time.
        
        Usage:
            !gn smartreminder 1h      — Set offset to 1 hour before earliest RSVP
            !gn smartreminder 30m     — Set offset to 30 minutes before earliest RSVP
            !gn smartreminder on      — Enable smart reminder
            !gn smartreminder off     — Disable smart reminder
            !gn smartreminder         — Show current settings
        """
        if args is None:
            # Show current settings
            enabled = await self.config.smart_reminder_enabled()
            offset = await self.config.smart_reminder_offset_minutes()
            status = "✅ ON" if enabled else "❌ OFF"
            
            if offset >= 60:
                hours = offset // 60
                mins = offset % 60
                offset_str = f"{hours}h{mins}m" if mins else f"{hours}h"
            else:
                offset_str = f"{offset}m"
            
            await ctx.send(
                f"🔔 **Smart Reminder**\n"
                f"Status: {status}\n"
                f"Offset: **{offset_str}** before the earliest RSVP time\n\n"
                f"Use `!gn smartreminder 1h` to set the offset,\n"
                f"`!gn smartreminder on/off` to enable/disable."
            )
            return
        
        args = args.strip().lower()
        
        if args == "on":
            await self.config.smart_reminder_enabled.set(True)
            await self._reschedule_smart_reminder()
            return await ctx.send("✅ Smart Reminder is now **ON**.")
        
        if args == "off":
            await self.config.smart_reminder_enabled.set(False)
            # Cancel running smart reminder
            if self._smart_reminder_task and not self._smart_reminder_task.done():
                self._smart_reminder_task.cancel()
            return await ctx.send("❌ Smart Reminder is now **OFF**.")
        
        # Parse time offset
        match = re.match(r'^(\d+(?:\.\d+)?)([hm])$', args)
        if not match:
            return await ctx.send("❌ Invalid format. Use e.g. `1h`, `30m`, `on` or `off`.")
        
        val, unit = match.groups()
        val = float(val)
        
        if unit == 'h':
            minutes = int(val * 60)
        else:
            minutes = int(val)
        
        if minutes < 1:
            return await ctx.send("❌ The offset must be at least 1 minute.")
        
        await self.config.smart_reminder_offset_minutes.set(minutes)
        
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            display = f"{hours}h{mins}m" if mins else f"{hours}h"
        else:
            display = f"{minutes}m"
        
        await ctx.send(f"🔔 Smart Reminder offset set to **{display}** before the earliest RSVP time.")

        # Reschedule if a session is currently open
        if self.is_open:
            await self._reschedule_smart_reminder()

    @gamenight.command(name="remind")
    @commands.admin_or_permissions(administrator=True)
    async def gn_remind(self, ctx):
        """Manually trigger a voting reminder to all RSVP'd players who haven't voted yet."""
        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")
            
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        missing_uids = [uid for uid in joining_players.keys() if int(uid) not in self.votes]
        
        if not missing_uids:
            return await ctx.send("✅ Everyone who RSVP'd has already voted!")
            
        pings = ", ".join(f"<@{uid}>" for uid in missing_uids)
        embed = discord.Embed(
            title="⏳ Voting Reminder!",
            description=(
                f"Hey {pings},\n\n"
                f"You have RSVP'd for game night tonight but haven't submitted your votes yet!\n"
                f"Please send me a **DM** with your choices so we can decide what to play.\n\n"
                f"Example: `!vote Fortnite, Palworld` 🤫"
            ),
            color=discord.Color.yellow(),
        )
        reminder_msg = await ctx.send(embed=embed)
        await self._track(reminder_msg)
        await self._track(ctx.message)

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        if not self.is_open:
            return await ctx.send("The voting is currently closed.")

        count = len(self.votes)
        msg_text = f"🗳️ We currently have **{count}** votes.\n"

        # Check who is still missing
        players = await self.config.players()
        joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
        if joining_players:
            missing_uids = [uid for uid in joining_players.keys() if int(uid) not in self.votes]
            if missing_uids:
                missing_names = []
                for uid in missing_uids:
                    user = self.bot.get_user(int(uid))
                    name = user.display_name if user else f"<@{uid}>"
                    missing_names.append(name)
                msg_text += f"\n⏳ **Still waiting for:** {', '.join(missing_names)}"
            else:
                msg_text += "\n✅ **All RSVP'd players have voted!**"

        await ctx.send(msg_text)

    @gamenight.command(name="history")
    async def gn_history(self, ctx):
        stats = await self.config.game_wins()
        sessions = await self.config.total_sessions()

        if not stats:
            return await ctx.send("No history available yet.")

        sorted_stats = sorted(stats.items(), key=lambda item: item[1], reverse=True)

        embed = discord.Embed(title="📜 Game Night History", color=discord.Color.purple())
        desc = f"*Total sessions: {sessions}*\n\n"

        for i, (game, wins) in enumerate(sorted_stats, 1):
            if i == 1:
                icon = "👑"
            elif i == 2:
                icon = "🥈"
            elif i == 3:
                icon = "🥉"
            else:
                icon = "🔹"
            desc += f"{icon} **{game}**: won {wins}x\n"
            if i >= 10:
                break

        embed.description = desc
        await ctx.send(embed=embed)

    def _calculate_result(self, votes, players, weighted_mode):
        """Build a result without changing votes or history; explicitly absent users are excluded."""
        eligible_votes = {
            uid: vote for uid, vote in votes.items()
            if players.get(str(uid)) != "No"
        }
        scores = defaultdict(int)
        vote_counts = defaultdict(int)
        veto_counts = defaultdict(int)
        for pos_games, neg_game in eligible_votes.values():
            for i, game in enumerate(pos_games):
                points = (3 - i) if weighted_mode else 1
                scores[game] += points
                vote_counts[game] += 1

            if neg_game:
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
        async with self.config.all() as data:
            result = data["session_result"]
            if result is None:
                result = self._calculate_result(self.votes, data["players"], data["weighted_mode"])
                if finalize:
                    candidates = result["potential_winners"]
                    if candidates:
                        result["winner"] = random.choice(candidates) if len(candidates) > 1 else candidates[0]
                        winner = result["winner"]
                        data["game_wins"][winner] = data["game_wins"].get(winner, 0) + 1
                        data["total_sessions"] += 1
                    data["session_result"] = result

        if not result["ranking"]:
            text = ("🎲 Everyone has no preference. No winning game was selected."
                    if result["total"] else "No votes received from attending players.")
            await self._track(await channel.send(text))
            return

        title = "🏆 The Results" if result["winner"] else "🗳️ Current standings (not final)"
        embed = discord.Embed(title=title, color=discord.Color.gold())
        desc = ""
        for i, (game, score, pos_votes, neg_votes) in enumerate(result["ranking"], 1):

            emoji = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"**#{i}**"

            vote_text = f"{pos_votes} up"
            if neg_votes > 0:
                vote_text += f", {neg_votes} down 💀"

            desc += f"{emoji} **{game}**\n╚ **{score} pts** ({vote_text})\n\n"
            if i >= 10:
                break

        embed.description = desc
        voted_count = result["voted"]
        total = result["total"]
        passed_count = total - voted_count
        if passed_count > 0:
            embed.set_footer(text=f"Total: {total} players ({voted_count} voted, {passed_count} 🎲 don't care)")
        else:
            embed.set_footer(text=f"Total: {total} voters.")
        results_msg = await channel.send(embed=embed)
        await self._track(results_msg)

        final_winner = result["winner"]
        if final_winner is None:
            return
        if len(result["potential_winners"]) > 1:
            embed_tie = discord.Embed(
                title="🎰 SUDDEN DEATH",
                description=f"The wheel stops on...\n# **🎉 {final_winner} 🎉**",
                color=discord.Color.red(),
            )
            tie_result_msg = await channel.send(embed=embed_tie)
            await self._track(tie_result_msg)
        else:
            winner_msg = await channel.send(f"🎉 The winner is clear: **{final_winner}**!")
            await self._track(winner_msg)

    @gamenight.command(name="results")
    @commands.admin_or_permissions(administrator=True)
    async def gn_results(self, ctx):
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
        """Show current auto-open settings."""
        enabled = await self.config.auto_open_enabled()
        auto_time = await self.config.auto_open_time()
        channel_id = await self.config.auto_open_channel_id()
        auto_days = await self.config.auto_open_days()

        status = "✅ ON" if enabled else "❌ OFF"

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        days_str = ", ".join(day_names[d] for d in sorted(auto_days)) if auto_days else "None"

        if channel_id:
            channel = self.bot.get_channel(channel_id)
            channel_str = channel.mention if channel else f"ID: {channel_id} (not found)"
        else:
            channel_str = "**Not configured** — use `!gn autoopen channel #channel`"

        embed = discord.Embed(
            title="⏰ Auto-Open Settings",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Time", value=f"**{auto_time}**", inline=True)
        embed.add_field(name="Days", value=days_str, inline=False)
        embed.add_field(name="Channel", value=channel_str, inline=False)
        embed.set_footer(text="Use !gn autoopen on/off/time/channel to adjust settings.")

        await ctx.send(embed=embed)

    @gn_autoopen.command(name="on")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_on(self, ctx):
        """Enable auto-open."""
        channel_id = await self.config.auto_open_channel_id()
        if not channel_id:
            return await ctx.send(
                "❌ Please set a channel first with `!gn autoopen channel #channel` "
                "before enabling auto-open."
            )
        await self.config.auto_open_enabled.set(True)
        auto_time = await self.config.auto_open_time()
        await ctx.send(f"✅ Auto-open is now **ON**. The voting session will open automatically at **{auto_time}**.")

    @gn_autoopen.command(name="off")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_off(self, ctx):
        """Disable auto-open."""
        await self.config.auto_open_enabled.set(False)
        await ctx.send("❌ Auto-open is now **OFF**.")

    @gn_autoopen.command(name="time")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_time(self, ctx, time_str: str):
        """Set the auto-open time (HH:MM format, e.g. 18:00 or 19:30)."""
        match = re.match(r'^(\d{1,2}):(\d{2})$', time_str.strip())
        if not match:
            return await ctx.send("❌ Invalid format. Please use `HH:MM`, e.g. `18:00` or `19:30`.")

        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return await ctx.send("❌ Invalid time. Hours must be 0-23, minutes 0-59.")

        formatted = f"{hour:02d}:{minute:02d}"
        await self.config.auto_open_time.set(formatted)
        await ctx.send(f"⏰ Auto-open time set to **{formatted}**.")

    @gn_autoopen.command(name="channel")
    @commands.admin_or_permissions(administrator=True)
    async def gn_autoopen_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where auto-open posts the voting embed."""
        await self.config.auto_open_channel_id.set(channel.id)
        await ctx.send(f"📢 Auto-open channel set to {channel.mention}.")

    # ── Debug Time Command ──────────────────────────────────────────────
    @gamenight.command(name="debugtime")
    @commands.admin_or_permissions(administrator=True)
    async def gn_debugtime(self, ctx):
        """Show timezone and scheduling debug information."""
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        utc_offset = now_local - now_utc.replace(tzinfo=None)
        offset_hours = utc_offset.total_seconds() / 3600

        # Format offset as +HH:MM
        sign = "+" if offset_hours >= 0 else "-"
        abs_hours = int(abs(offset_hours))
        abs_mins = int((abs(offset_hours) - abs_hours) * 60)
        offset_str = f"{sign}{abs_hours:02d}:{abs_mins:02d}"

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        today_name = day_names[now_local.weekday()]

        # Auto-open info
        enabled = await self.config.auto_open_enabled()
        auto_time = await self.config.auto_open_time()
        auto_days = await self.config.auto_open_days()
        auto_days_str = ", ".join(day_names[d] for d in sorted(auto_days)) if auto_days else "None"
        is_auto_day = now_local.weekday() in auto_days

        # Calculate next auto-open
        next_open_str = "Disabled"
        if enabled and auto_days:
            try:
                target_h, target_m = map(int, auto_time.split(":"))
                # Find the next occurrence
                check = now_local.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
                # If today is an auto-day and the time hasn't passed yet, it's today
                if now_local.weekday() in auto_days and now_local < check:
                    next_open_str = f"{today_name} {auto_time} (today)"
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
                next_open_str = "⚠️ Could not calculate (invalid auto_open_time)"

        embed = discord.Embed(
            title="🕵️ Debug: Time & Timezone",
            color=discord.Color.greyple(),
        )
        embed.add_field(
            name="🕐 Times",
            value=(
                f"**UTC:** {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Local:** {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Offset:** UTC{offset_str}"
            ),
            inline=False,
        )
        embed.add_field(
            name="📅 Day",
            value=(
                f"**Today:** {today_name} (weekday={now_local.weekday()})\n"
                f"**Is auto-open day?** {'✅ Yes' if is_auto_day else '❌ No'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="⏰ Auto-Open Config",
            value=(
                f"**Enabled:** {'✅' if enabled else '❌'}\n"
                f"**Time:** {auto_time}\n"
                f"**Days:** {auto_days_str}\n"
                f"**Already opened today?** {'Yes' if self._auto_opened_date == now_local.strftime('%Y-%m-%d') else 'No'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="📌 Next Auto-Open",
            value=next_open_str,
            inline=False,
        )
        embed.add_field(
            name="🔧 System Info",
            value=(
                f"**time.tzname:** {time.tzname}\n"
                f"**time.timezone:** {time.timezone} sec ({time.timezone / 3600:.1f}h)\n"
                f"**time.daylight:** {time.daylight}"
            ),
            inline=False,
        )
        embed.set_footer(text="If the offset is incorrect, the bot might be running in the wrong timezone.")

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(GameNight(bot))
