from redbot.core import commands, Config
from collections import defaultdict
import discord
import re
import difflib
import asyncio
import random

# --- CONFIGURATION: ALIAS LIST ---
GAME_ALIASES = {
    # SHOOTERS
    "Call of Duty": ["cod", "mw3", "mw2", "warzone", "bo6", "blackops", "callofduty", "shooter"],
    "Counter-Strike 2": ["cs2", "cs", "csgo", "counterstrike", "globaloffensive", "cstrike"],
    "Valorant": ["val", "valo", "valorant", "valerant"],
    "Overwatch 2": ["ow", "ow2", "overwatch", "overwatch2"],
    "Fortnite": ["fn", "fort", "build", "fortnite", "fortnight", "fornite", "fourtnite", "fortnitet"],
    "Apex Legends": ["apex", "apexlegends", "apax"],
    "Tom Clancy's Rainbow Six Siege": ["r6", "siege", "rainbow", "rss", "rainbowsix", "rainbow6"],
    "Escape from Tarkov": ["eft", "tarkov", "tarkof"],
    "Destiny 2": ["destiny", "d2", "destiny2"],
    "Halo Infinite": ["halo", "infinite", "masterchief"],
    "The Finals": ["finals", "thefinals"],
    "PUBG: Battlegrounds": ["pubg", "plunkbat", "battlegrounds"],

    # SURVIVAL & CRAFTING
    "Minecraft": ["mc", "mine", "craft", "minecraft", "mincraft", "maincraft", "blokjes"],
    "Terraria": ["terra", "terraria", "teraria"],
    "Rust": ["rust", "rustgame"],
    "Ark: Survival Ascended": ["ark", "asa", "ase", "dinos", "ark2"],
    "Valheim": ["valheim", "viking", "valheim"],
    "Raft": ["raft", "vlotje"],
    "Palworld": ["pal", "pals", "palworld", "pokemon", "palword"],
    "DayZ": ["dayz", "days", "day z"],
    "7 Days to Die": ["7days", "7d2d", "7dtd", "seven days"],
    "No Man's Sky": ["nms", "nomanssky", "noman"],
    "Project Zomboid": ["pz", "zomboid", "zombies"],

    # HORROR & CO-OP
    "Lethal Company": ["lethal", "lc", "company", "lethalcompany", "leathal", "lethalcomp"],
    "The Outlast Trials": ["trials", "tot", "outlast", "outlasttrials", "outlas", "out last", "trails", "triels"],
    "Phasmophobia": ["phas", "phasmo", "ghosts", "phasmophobia", "phasmofobia", "fasmophobia"],
    "Dead by Daylight": ["dbd", "deadby", "deadbydaylight", "dead by"],
    "Sons of the Forest": ["sotf", "sons", "forest", "forest2", "sonsoftheforest"],
    "Content Warning": ["content", "warning", "cw", "camera", "contentwarning"],
    "Left 4 Dead 2": ["l4d2", "l4d", "left4dead"],
    "Deep Rock Galactic": ["drg", "deeprock", "rockandstone", "dwarves", "deep rock"],
    "Helldivers 2": ["helldivers", "hd2", "democracy", "helldivers2"],
    "R.E.P.O.": ["repo", "r.e.p.o", "repo game"],
    "Sea of Thieves": ["sot", "sea", "thieves", "pirates", "seaofthieves"],
    "Garry's Mod": ["gmod", "garrys", "garry"],
    
    # SOCIAL & PARTY
    "Among Us": ["amogus", "au", "sus", "among", "impostor", "amongus"],
    "The Jackbox Party Pack": ["jackbox", "jb", "jack", "box"],
    "Fall Guys": ["fall", "guys", "fallguys", "beans", "fallguy"],
    "Pummel Party": ["pummel", "party", "pummelparty"],
    "Golf It!": ["golfit", "golf"],

    # MOBA & STRATEGY
    "League of Legends": ["lol", "league", "leagueoflegends", "leauge"],
    "Dota 2": ["dota", "dota2"],

    # SPORTS & RACING
    "Rocket League": ["rocket", "rl", "rocketleague", "cars", "soccer"],
    "Mario Kart": ["mario", "mariokart", "kart", "race"],

    # RPG & MMO
    "World of Warcraft": ["wow", "warcraft", "worldofwarcraft"],
    "Palia": ["palia", "pallia"], 
    "Baldur's Gate 3": ["bg3", "baldur", "baldurs", "gate3"],
    "Path of Exile": ["poe", "path", "pathofexile"],
    "Grand Theft Auto V": ["gta", "gta5", "gtav", "gtaonline", "gta 5"]
}

class GameNight(commands.Cog):
    """The Ultimate Game Night Plugin: Clean, Secret & Stats."""

    def __init__(self, bot):
        self.bot = bot
        self.votes = {}
        self.is_open = False
        self.weighted_mode = True 
        
        # Database setup
        self.config = Config.get_conf(self, identifier=847372839210)
        default_global = {
            "game_wins": {}, 
            "total_sessions": 0
        }
        self.config.register_global(**default_global)

    def normalize_game_name(self, user_input):
        """Marco-proof name recognition."""
        clean_input = user_input.strip().lower()
        if not clean_input:
            return None, False

        # 1. Exact check
        for official_name, aliases in GAME_ALIASES.items():
            if clean_input == official_name.lower():
                return official_name, False
            if clean_input in aliases:
                return official_name, False

        # 2. Fuzzy Match
        all_possibilities = {}
        for name, aliases in GAME_ALIASES.items():
            all_possibilities[name.lower()] = name
            for a in aliases:
                all_possibilities[a] = name
        
        matches = difflib.get_close_matches(clean_input, all_possibilities.keys(), n=1, cutoff=0.6)
        
        if matches:
            official_name = all_possibilities[matches[0]]
            return official_name, True 

        # 3. Fallback
        return user_input.strip().title(), False

    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        """Switch between 3-point and 1-point mode."""
        self.weighted_mode = not self.weighted_mode
        status = "**ON** (3-2-1)" if self.weighted_mode else "**OFF** (1-1-1)"
        await ctx.send(f"⚖️ Bonus point system is now {status}.")

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        """Reset votes and open the voting lines."""
        self.is_open = True
        self.votes.clear()
        rules = "🥇 3 pts | 🥈 2 pts | 🥉 1 pt" if self.weighted_mode else "Every vote is 1 point."
        embed = discord.Embed(
            title="🎮 Game Night Voting Open!",
            description=f"Send me a **DM** with `!vote Game 1, Game 2, Game 3`.\n\n{rules}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        """Close the voting lines AND show results immediately."""
        self.is_open = False
        await ctx.send("🛑 **Voting is closed!** calculating results...")
        
        # We triggeren nu direct de uitslag functie!
        # Zo hoef je niet apart !gn results te typen.
        await self.gn_results(ctx)

    @commands.command()
    async def vote(self, ctx, *, games_input: str):
        """Vote via DM: !vote Game1, Game2..."""
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(f"{ctx.author.mention}, please send this in a DM! 🤫", delete_after=5)

        if not self.is_open:
            return await ctx.send("⛔ Voting is currently closed.")

        raw_games = games_input.split(',')
        clean_games = []
        corrections = []

        for g in raw_games:
            if g.strip():
                final_name, was_corrected = self.normalize_game_name(g)
                if final_name:
                    clean_games.append(final_name)
                    if was_corrected:
                        corrections.append(f"'{g.strip()}' ➡️ **{final_name}**")

        if not clean_games:
            return await ctx.send("No valid games found. Please use commas.")

        clean_games = clean_games[:3]
        self.votes[ctx.author.id] = clean_games
        
        msg = "✅ **Votes Received!**\n"
        if corrections:
            msg += "\n🪄 *Autocorrect:* " + ", ".join(corrections) + "\n\n"

        msg += "**Your list:**\n"
        for i, game in enumerate(clean_games, 1):
            if self.weighted_mode:
                points = 4 - i
                msg += f"#{i} **{game}** ({points} pts)\n"
            else:
                msg += f"- **{game}**\n"
        
        await ctx.send(msg)

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        """Check how many people voted."""
        if not self.votes:
            return await ctx.send("No one has voted yet.")
        count = len(self.votes)
        await ctx.send(f"🗳️ Currently, **{count}** people have voted.")

    @gamenight.command(name="history")
    async def gn_history(self, ctx):
        """View the Hall of Fame."""
        stats = await self.config.game_wins()
        sessions = await self.config.total_sessions()

        if not stats:
            return await ctx.send("No history available yet.")

        sorted_stats = sorted(stats.items(), key=lambda item: item[1], reverse=True)

        embed = discord.Embed(title="📜 Game Night History", color=discord.Color.purple())
        desc = f"*Total sessions: {sessions}*\n\n"
        
        for i, (game, wins) in enumerate(sorted_stats, 1):
            if i == 1: icon = "👑"
            elif i == 2: icon = "🥈"
            elif i == 3: icon = "🥉"
            else: icon = "🔹"
            desc += f"{icon} **{game}**: won {wins}x\n"
            if i >= 10: break

        embed.description = desc
        await ctx.send(embed=embed)

    @gamenight.command(name="results")
    @commands.admin_or_permissions(administrator=True)
    async def gn_results(self, ctx):
        """Calculate winner + Tiebreaker + Save."""
        if not self.votes:
            return await ctx.send("No votes received.")

        scores = defaultdict(int)
        vote_counts = defaultdict(int)

        for user_games in self.votes.values():
            for i, game in enumerate(user_games):
                points = (3 - i) if self.weighted_mode else 1
                scores[game] += points
                vote_counts[game] += 1

        sorted_games = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        
        highest_score = sorted_games[0][1]
        potential_winners = [g for g, s in sorted_games if s == highest_score]

        embed = discord.Embed(title="🏆 The Results", color=discord.Color.gold())
        desc = ""
        for i, (game, score) in enumerate(sorted_games, 1):
            votes = vote_counts[game]
            emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**#{i}**"
            p_text = "pts" if self.weighted_mode else "votes"
            
            desc += f"{emoji} **{game}**\n╚ {score} {p_text} (by {votes} players)\n\n"
            if i >= 10: break

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
                color=discord.Color.red()
            )
            await ctx.send(embed=embed_tie)
        else:
            await ctx.send(f"🎉 The winner is clear: **{final_winner}**!")

        # Save to DB
        async with self.config.game_wins() as wins:
            current = wins.get(final_winner, 0)
            wins[final_winner] = current + 1
        
        count = await self.config.total_sessions()
        await self.config.total_sessions.set(count + 1)

async def setup(bot):
    await bot.add_cog(GameNight(bot))
