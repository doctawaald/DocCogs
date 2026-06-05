from redbot.core import commands, Config
from collections import defaultdict
import discord
import re
import difflib
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

from .games import GAMES  # Separate game list

class RSVPView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        custom_id="gn_rsvp_select",
        placeholder="When will you be online?",
        options=[
            discord.SelectOption(label="Earlier (Before 20:30)", emoji="🕰️", value="Earlier"),
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
            val = select.values[0]
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

        # Message tracking for auto-cleanup
        self.tracked_messages: list[discord.Message] = []
        self._cleanup_task: asyncio.Task | None = None
        self._reminder_task: asyncio.Task | None = None
        self._smart_reminder_task: asyncio.Task | None = None
        self._smart_reminder_sent: bool = False

        # Database setup
        self.config = Config.get_conf(self, identifier=847372839210)
        default_global = {
            "game_wins": {},
            "total_sessions": 0,
            "weighted_mode": True,
            "veto_mode": False,
            "is_open": False,
            "votes": {},
            "vote_message": None,
            "tracked_messages": [],
            "cleanup_time": None,
            "cleanup_delay_hours": 12.0,
            "reminder_time": None,
            "reminder_delay_hours": 2.0,
            "smart_reminder_offset_minutes": 60,
            "smart_reminder_enabled": True,
            "players": {}
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
        # Defer immediately to satisfy Discord's 3-second response window.
        # Guard with is_done() in case another view instance already deferred this interaction.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        try:
            if not self.is_open:
                return await interaction.followup.send("Voting is currently closed.", ephemeral=True)
                
            async with self.config.players() as players:
                players[str(interaction.user.id)] = time_val
                if time_val == "No":
                    msg = "❌ You are marked as **not joining** today."
                else:
                    msg = f"✅ You are marked as playing at **{time_val}**!"
                    
            # Send ephemeral confirmation as a followup response
            await interaction.followup.send(msg, ephemeral=True)
            
            # Update the embed
            await self._update_rsvp_embed()
            
            # Reschedule the smart reminder based on the new earliest RSVP time
            await self._reschedule_smart_reminder()
            
            # Check completion
            await self.check_completion()
        except discord.errors.InteractionResponded:
            pass  # Already handled — safe to ignore
        except Exception as e:
            # Last resort: make sure the user gets feedback
            try:
                await interaction.followup.send(
                    "⚠️ Something went wrong processing your RSVP. Please try again.", ephemeral=True
                )
            except Exception:
                pass

    async def _update_rsvp_embed(self):
        channel, msg = await self._get_or_restore_vote_message()
        if not channel or not msg:
            return
            
        try:
            if not msg.embeds:
                return
                
            embed = msg.embeds[0]
            players = await self.config.players()
            
            # Rebuild the fields
            embed.clear_fields()
            embed.add_field(
                name="Are you gaming tonight?",
                value="Select your expected time in the dropdown below.\nSelect ❌ if you can't make it.",
                inline=False,
            )
            
            joining_players = {uid: t_val for uid, t_val in players.items() if t_val != "No"}
            absent_players = {uid: t_val for uid, t_val in players.items() if t_val == "No"}
            
            if joining_players:
                # Format player list
                player_lines = []
                for uid, t_val in joining_players.items():
                    has_voted = int(uid) in self.votes
                    status_emoji = "🎮" if has_voted else "❓"
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
                
            await msg.edit(embed=embed)
        except Exception as e:
            pass

    async def cog_load(self):
        """Restore state from config when the bot reboots."""
        self.is_open = await self.config.is_open()
        
        raw_votes = await self.config.votes()
        self.votes = {int(k): v for k, v in raw_votes.items()}
        
        # We don't eagerly load/fetch the message here during startup hook because the channel cache
        # might not be fully loaded. Instead, the lazy loader _get_or_restore_vote_message recovers it on-demand.
        self.vote_channel = None
        self.vote_message = None

        cleanup_time = await self.config.cleanup_time()
        if cleanup_time:
            now = time.time()
            delay = max(0, cleanup_time - now)
            self._cleanup_task = asyncio.create_task(self._schedule_cleanup(delay_seconds=delay))

        reminder_time = await self.config.reminder_time()
        if reminder_time:
            now = time.time()
            delay = max(0, reminder_time - now)
            self._reminder_task = asyncio.create_task(self._schedule_reminder(delay_seconds=delay))

        # Clean up any duplicate RSVPViews from previous reloads (before cog_unload was added)
        for view in list(self.bot.persistent_views):
            if view.__class__.__name__ == "RSVPView":
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
                if view.__class__.__name__ == "RSVPView":
                    try:
                        view.stop()
                    except Exception:
                        pass
                    try:
                        self.bot._connection._persistent_views.remove(view)
                    except Exception:
                        pass

        # Store view reference so we can stop it on unload to prevent duplicates
        self.rsvp_view = RSVPView(self)
        self.bot.add_view(self.rsvp_view)

    def cog_unload(self):
        """Clean up active persistent views and running tasks on cog unload."""
        if hasattr(self, 'rsvp_view'):
            self.rsvp_view.stop()
        if hasattr(self, '_cleanup_task') and self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if hasattr(self, '_reminder_task') and self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if hasattr(self, '_smart_reminder_task') and self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()

    async def _track(self, msg: discord.Message):
        """Register a message for the post-session cleanup."""
        if msg is not None:
            self.tracked_messages.append(msg)
            async with self.config.tracked_messages() as tracked:
                tracked.append([msg.channel.id, msg.id])

    async def _schedule_cleanup(self, delay_seconds: float):
        """Wait `delay_seconds` then bulk-delete all tracked messages, fetching channels if uncached."""
        await asyncio.sleep(delay_seconds)
        
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
                pass  # Already deleted or missing permissions — ignore
                
        self.tracked_messages.clear()
        await self.config.tracked_messages.set([])
        await self.config.cleanup_time.set(None)

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
            
        self._smart_reminder_sent = True
        
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
        await self._track(reminder_msg)

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
                    embed = discord.Embed(
                        title="🎉 All votes are in!",
                        description="Everyone who RSVP'd has voted.\nThe admin can now use `!gn close`.",
                        color=discord.Color.blue(),
                    )
                    all_voted_msg = await channel.send(embed=embed)
                    await self._track(all_voted_msg)
            else:
                # Someone new clicked ✅ — reset so the notification fires again when complete.
                self.all_voted_notified = False

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

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        self.is_open = True
        self.votes.clear()
        self.all_voted_notified = False
        self.too_many_notified = False  # Reset at the start of each new voting round
        self._smart_reminder_sent = False  # Reset for the new session
        
        await self.config.is_open.set(True)
        await self.config.votes.set({})
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

        rules = "🥇 3 pts | 🥈 2 pts | 🥉 1 pt" if weighted else "Every positive vote is 1 point."

        if veto:
            veto_text = "\n💀 **VETO ENABLED:** use `#` to downvote a game (-1 pt)."
            example = "`!vote Game1, Game2, Game3 # BadGame`"
        else:
            veto_text = ""
            example = "`!vote Game1, Game2, Game3`"

        embed = discord.Embed(
            title="🎮 Game Night Voting Open!",
            description=f"Send me a **DM** with your choices.\nExample: {example}\n\n{rules}{veto_text}",
            color=discord.Color.green(),
        )
        # The RSVP question
        embed.add_field(
            name="Are you gaming tonight?",
            value="Select your expected time in the dropdown below.\nSelect ❌ if you can't make it.",
            inline=False,
        )

        msg = await ctx.send(embed=embed, view=RSVPView(self))
        self.vote_message = msg
        self.vote_channel = ctx.channel
        await self.config.vote_message.set([ctx.channel.id, msg.id])

        await self._track(msg)  # Track the open-vote embed
        await self._track(ctx.message)  # Track the !gn open command itself

        # Schedule voting reminder (only if delay > 0, i.e. not disabled)
        delay_hours = await self.config.reminder_delay_hours()
        if delay_hours > 0:
            delay_seconds = delay_hours * 3600
            reminder_time = time.time() + delay_seconds
            await self.config.reminder_time.set(reminder_time)
            self._reminder_task = asyncio.create_task(self._schedule_reminder(delay_seconds=delay_seconds))

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        self.is_open = False
        await self.config.is_open.set(False)
        self.all_voted_notified = False
        self.too_many_notified = False
        
        # Remove view from message to prevent further RSVPs
        channel, msg = await self._get_or_restore_vote_message()
        if msg:
            try:
                await msg.edit(view=None)
            except discord.NotFound:
                pass
                
        await self._track(ctx.message)  # Track the !gn close command itself
        closing_msg = await ctx.send("🛑 **Voting is closed!** calculating results...")
        await self._track(closing_msg)
        await self.gn_results(ctx)

        # Schedule cleanup
        delay_hours = await self.config.cleanup_delay_hours()
        delay_seconds = delay_hours * 3600
        cleanup_time = time.time() + delay_seconds
        await self.config.cleanup_time.set(cleanup_time)

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self._cleanup_task = asyncio.create_task(self._schedule_cleanup(delay_seconds=delay_seconds))

        # Cancel voting reminders
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
        await self.config.reminder_time.set(None)

    @commands.command()
    async def vote(self, ctx, *, games_input: str):
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(
                f"{ctx.author.mention}, please send this in a DM! 🤫", delete_after=5
            )

        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")

        veto_enabled = await self.config.veto_mode()
        weighted_mode = await self.config.weighted_mode()

        pos_input = games_input
        neg_input = None

        if "#" in games_input:
            if not veto_enabled:
                return await ctx.send("⛔ Veto mode is disabled. You cannot use `#` today.")

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

    @gamenight.command(name="reset")
    @commands.admin_or_permissions(administrator=True)
    async def gn_reset(self, ctx):
        """Reset the current voting session completely."""
        self.is_open = False
        self.votes.clear()
        self.vote_message = None
        self.vote_channel = None
        self.all_voted_notified = False
        self.too_many_notified = False
        
        await self.config.is_open.set(False)
        await self.config.votes.set({})
        await self.config.vote_message.set(None)
        await self.config.tracked_messages.set([])
        await self.config.cleanup_time.set(None)
        await self.config.reminder_time.set(None)
        self._smart_reminder_sent = False
        
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        if self._smart_reminder_task and not self._smart_reminder_task.done():
            self._smart_reminder_task.cancel()
            
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

    @gamenight.command(name="results")
    @commands.admin_or_permissions(administrator=True)
    async def gn_results(self, ctx):
        if not self.votes:
            return await ctx.send("No votes received.")

        scores = defaultdict(int)
        vote_counts = defaultdict(int)
        veto_counts = defaultdict(int)

        weighted_mode = await self.config.weighted_mode()

        for pos_games, neg_game in self.votes.values():
            for i, game in enumerate(pos_games):
                points = (3 - i) if weighted_mode else 1
                scores[game] += points
                vote_counts[game] += 1

            if neg_game:
                scores[neg_game] -= 1
                veto_counts[neg_game] += 1

        sorted_games = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        highest_score = sorted_games[0][1]
        potential_winners = [g for g, s in sorted_games if s == highest_score]

        embed = discord.Embed(title="🏆 The Results", color=discord.Color.gold())
        desc = ""
        for i, (game, score) in enumerate(sorted_games, 1):
            pos_votes = vote_counts[game]
            neg_votes = veto_counts[game]

            emoji = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"**#{i}**"

            vote_text = f"{pos_votes} up"
            if neg_votes > 0:
                vote_text += f", {neg_votes} down 💀"

            desc += f"{emoji} **{game}**\n╚ **{score} pts** ({vote_text})\n\n"
            if i >= 10:
                break

        embed.description = desc
        embed.set_footer(text=f"Total: {len(self.votes)} voters.")
        results_msg = await ctx.send(embed=embed)
        await self._track(results_msg)

        # --- TIEBREAKER & SAVE LOGIC ---
        final_winner = potential_winners[0]

        if len(potential_winners) > 1:
            await asyncio.sleep(1)
            tie_str = ", ".join(potential_winners)
            tie_msg = await ctx.send(f"⚠️ **TIE!** Between: {tie_str}.\nSpinning the wheel...")
            await self._track(tie_msg)
            await asyncio.sleep(3)
            final_winner = random.choice(potential_winners)

            embed_tie = discord.Embed(
                title="🎰 SUDDEN DEATH",
                description=f"The wheel stops on...\n# **🎉 {final_winner} 🎉**",
                color=discord.Color.red(),
            )
            tie_result_msg = await ctx.send(embed=embed_tie)
            await self._track(tie_result_msg)
        else:
            winner_msg = await ctx.send(f"🎉 The winner is clear: **{final_winner}**!")
            await self._track(winner_msg)

        async with self.config.game_wins() as wins:
            current = wins.get(final_winner, 0)
            wins[final_winner] = current + 1

        count = await self.config.total_sessions()
        await self.config.total_sessions.set(count + 1)


async def setup(bot):
    await bot.add_cog(GameNight(bot))
