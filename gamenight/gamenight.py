from redbot.core import commands, Config
from collections import defaultdict
import discord
import re
import difflib
import asyncio
import random

from .games import GAMES  # Separate game list

# Build alias lookup once at import time
GAME_ALIASES = {name: data["aliases"] for name, data in GAMES.items()}

# Player count threshold for the "too many players" warning
TOO_MANY_PLAYERS_THRESHOLD = 4


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

        # Database setup
        self.config = Config.get_conf(self, identifier=847372839210)
        default_global = {
            "game_wins": {},
            "total_sessions": 0,
            "weighted_mode": True,
            "veto_mode": False,
        }
        self.config.register_global(**default_global)

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
        """Returns the current number of non-bot users who clicked ✅, or None if unavailable."""
        if not self.vote_message or not self.vote_channel:
            return None
        try:
            msg = await self.vote_channel.fetch_message(self.vote_message.id)
            yes_reaction = discord.utils.get(msg.reactions, emoji="✅")
            if not yes_reaction:
                return 0
            yes_users = [u async for u in yes_reaction.users() if not u.bot]
            return len(yes_users)
        except Exception:
            return None

    async def check_completion(self):
        """Checks whether everyone who clicked ✅ has actually voted.
        Also sends a warning when more than TOO_MANY_PLAYERS_THRESHOLD players are present.
        """
        if not self.is_open or not self.vote_message or not self.vote_channel:
            return

        try:
            # Fetch the current message to get the latest reactions
            msg = await self.vote_channel.fetch_message(self.vote_message.id)
            yes_reaction = discord.utils.get(msg.reactions, emoji="✅")

            if not yes_reaction:
                return

            # List of players who clicked ✅ (ignore the bot)
            yes_users = [user async for user in yes_reaction.users() if not user.bot]
            player_count = len(yes_users)

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
                    await self.vote_channel.send(embed=embed)
            else:
                # Player count dropped back down — reset so the warning can fire again if needed
                self.too_many_notified = False

            # ── Minimum threshold for the "all votes in" check ──────────────
            # Only evaluate once at least 3 people have RSVP'd.
            if player_count < 3:
                self.all_voted_notified = False
                return

            # Check who is still missing a vote
            missing = [user for user in yes_users if user.id not in self.votes]

            if not missing:
                # Everyone has voted — send the notification (only once)
                if not self.all_voted_notified:
                    self.all_voted_notified = True
                    embed = discord.Embed(
                        title="🎉 All votes are in!",
                        description="Everyone who RSVP'd has voted.\nThe admin can now use `!gn close`.",
                        color=discord.Color.blue(),
                    )
                    await self.vote_channel.send(embed=embed)
            else:
                # Someone new clicked ✅ — reset so the notification fires again when complete.
                self.all_voted_notified = False

        except discord.NotFound:
            pass  # Message was deleted
        except Exception as e:
            print(f"Error checking completion: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Triggers a completion check immediately when someone clicks ✅."""
        if self.is_open and self.vote_message and payload.message_id == self.vote_message.id:
            if str(payload.emoji) == "✅" and payload.user_id != self.bot.user.id:
                await self.check_completion()

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Re-checks when someone removes their ✅ (e.g. player count drops back down)."""
        if self.is_open and self.vote_message and payload.message_id == self.vote_message.id:
            if str(payload.emoji) == "✅" and payload.user_id != self.bot.user.id:
                await self.check_completion()

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
            value="Click ✅ if you are playing.\nClick ❌ if you can't make it.",
            inline=False,
        )

        msg = await ctx.send(embed=embed)
        self.vote_message = msg
        self.vote_channel = ctx.channel

        # Add reactions immediately
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        self.is_open = False
        self.all_voted_notified = False
        self.too_many_notified = False
        await ctx.send("🛑 **Voting is closed!** calculating results...")
        await self.gn_results(ctx)

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
            await self.vote_channel.send(embed=embed)

        # Immediately check whether this was the last missing voter
        await self.check_completion()

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        if not self.is_open:
            return await ctx.send("The voting is currently closed.")

        count = len(self.votes)
        msg_text = f"🗳️ We currently have **{count}** votes.\n"

        # Check who is still missing
        if self.vote_message and self.vote_channel:
            try:
                msg = await self.vote_channel.fetch_message(self.vote_message.id)
                yes_reaction = discord.utils.get(msg.reactions, emoji="✅")

                if yes_reaction:
                    yes_users = [u async for u in yes_reaction.users() if not u.bot]
                    missing = [u for u in yes_users if u.id not in self.votes]

                    if missing:
                        missing_names = ", ".join([u.display_name for u in missing])
                        msg_text += f"\n⏳ **Still waiting for:** {missing_names}"
                    elif yes_users:
                        msg_text += "\n✅ **All RSVP'd players have voted!**"
            except Exception:
                pass  # Skip if the original message was deleted

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
        await ctx.send(embed=embed)

        # --- TIEBREAKER & SAVE LOGIC ---
        final_winner = potential_winners[0]

        if len(potential_winners) > 1:
            await asyncio.sleep(1)
            tie_str = ", ".join(potential_winners)
            await ctx.send(f"⚠️ **TIE!** Between: {tie_str}.\nSpinning the wheel...")
            await asyncio.sleep(3)
            final_winner = random.choice(potential_winners)

            embed_tie = discord.Embed(
                title="🎰 SUDDEN DEATH",
                description=f"The wheel stops on...\n# **🎉 {final_winner} 🎉**",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed_tie)
        else:
            await ctx.send(f"🎉 The winner is clear: **{final_winner}**!")

        async with self.config.game_wins() as wins:
            current = wins.get(final_winner, 0)
            wins[final_winner] = current + 1

        count = await self.config.total_sessions()
        await self.config.total_sessions.set(count + 1)


async def setup(bot):
    await bot.add_cog(GameNight(bot))
