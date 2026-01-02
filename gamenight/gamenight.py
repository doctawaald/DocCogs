from redbot.core import commands
from collections import defaultdict
import discord
import re
import difflib # <--- De magische library voor typefouten

# --- CONFIGURATIE ---
GAME_ALIASES = {
    # SHOOTERS
    "Call of Duty": ["cod", "mw3", "mw2", "warzone", "bo6", "blackops"],
    "Counter-Strike 2": ["cs2", "cs", "csgo", "counterstrike"],
    "Valorant": ["val", "valo", "valorant"],
    "Overwatch 2": ["ow", "ow2", "overwatch"],
    "Fortnite": ["fn", "fort", "build", "fortnite", "fortnight"],
    "Apex Legends": ["apex", "apexlegends"],
    "Tom Clancy's Rainbow Six Siege": ["r6", "siege", "rainbow", "rss"],
    "Escape from Tarkov": ["eft", "tarkov"],
    "Destiny 2": ["destiny", "d2"],
    "Halo Infinite": ["halo", "infinite"],
    "The Finals": ["finals"],
    "PUBG: Battlegrounds": ["pubg", "plunkbat"],

    # SURVIVAL & CRAFTING
    "Minecraft": ["mc", "mine", "craft", "minecraft", "blokjes"],
    "Terraria": ["terra", "terraria"],
    "Rust": ["rust"],
    "Ark: Survival Ascended": ["ark", "asa", "ase", "dinos"],
    "Valheim": ["valheim", "viking"],
    "Raft": ["raft"],
    "Palworld": ["pal", "pals", "palworld", "pokemon"],
    "DayZ": ["dayz"],
    "7 Days to Die": ["7days", "7d2d", "7dtd"],
    "No Man's Sky": ["nms", "nomanssky"],
    "Project Zomboid": ["pz", "zomboid"],

    # HORROR & CO-OP
    "Lethal Company": ["lethal", "lc", "company", "lethalcompany"],
    "The Outlast Trials": ["trials", "tot", "outlast", "outlasttrials"],
    "Phasmophobia": ["phas", "phasmo", "ghosts", "phasmophobia"],
    "Dead by Daylight": ["dbd", "deadby", "deadbydaylight"],
    "Sons of the Forest": ["sotf", "sons", "forest", "forest2"],
    "Content Warning": ["content", "warning", "cw", "camera"],
    "Left 4 Dead 2": ["l4d2", "l4d"],
    "Deep Rock Galactic": ["drg", "deeprock", "rockandstone", "dwarves"],
    "Helldivers 2": ["helldivers", "hd2", "democracy"],
    "R.E.P.O.": ["repo", "r.e.p.o"],
    "Sea of Thieves": ["sot", "sea", "thieves", "pirates"],
    "Garry's Mod": ["gmod", "garrys"],
    
    # SOCIAL & PARTY
    "Among Us": ["amogus", "au", "sus", "among", "impostor"],
    "The Jackbox Party Pack": ["jackbox", "jb", "jack", "box"],
    "Fall Guys": ["fall", "guys", "fallguys", "beans"],
    "Pummel Party": ["pummel", "party"],
    "Golf It!": ["golfit", "golf"],

    # MOBA & STRATEGY
    "League of Legends": ["lol", "league", "leagueoflegends"],
    "Dota 2": ["dota"],

    # SPORTS & RACING
    "Rocket League": ["rocket", "rl", "rocketleague", "cars", "voetbalauto"],
    "Mario Kart": ["mario", "mariokart", "kart"],

    # RPG & MMO
    "World of Warcraft": ["wow", "warcraft"],
    "Palia": ["palia"], 
    "Baldur's Gate 3": ["bg3", "baldur", "baldurs"],
    "Path of Exile": ["poe", "path"],
    "Grand Theft Auto V": ["gta", "gta5", "gtav", "gtaonline"]
}

class GameNight(commands.Cog):
    """Marco-proof voting system."""

    def __init__(self, bot):
        self.bot = bot
        self.votes = {}
        self.is_open = False
        self.weighted_mode = True 

    def normalize_game_name(self, user_input):
        """
        Probeert input te matchen. Geeft terug: (GecorrigeerdeNaam, WasHetEenGok)
        """
        clean_input = user_input.strip().lower()
        if not clean_input:
            return None, False

        # 1. Exacte check (Clean input vs Aliases)
        for official_name, aliases in GAME_ALIASES.items():
            if clean_input == official_name.lower():
                return official_name, False
            if clean_input in aliases:
                return official_name, False

        # 2. Marco-Proof Fuzzy Match (De 'Gok' fase)
        # We maken een lijst van ALLE woorden die we kennen (officiële namen + aliassen)
        all_possibilities = {}
        for name, aliases in GAME_ALIASES.items():
            all_possibilities[name.lower()] = name
            for a in aliases:
                all_possibilities[a] = name
        
        # difflib zoekt de beste match. 'cutoff=0.6' betekent 60% gelijkenis nodig.
        matches = difflib.get_close_matches(clean_input, all_possibilities.keys(), n=1, cutoff=0.6)
        
        if matches:
            best_match_key = matches[0]
            official_name = all_possibilities[best_match_key]
            return official_name, True # True betekent: We hebben het gecorrigeerd

        # 3. Geen match gevonden? Dan is het een nieuwe/onbekende game.
        # We maken hem gewoon netjes (Hoofdletters).
        return user_input.strip().title(), False

    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        self.weighted_mode = not self.weighted_mode
        status = "**AAN** (3-2-1)" if self.weighted_mode else "**UIT** (1-1-1)"
        await ctx.send(f"⚖️ Bonuspunten systeem staat nu {status}.")

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        self.is_open = True
        self.votes.clear()
        rules = "🥇 3 pnt | 🥈 2 pnt | 🥉 1 pnt" if self.weighted_mode else "Elke stem is 1 punt."
        embed = discord.Embed(
            title="🎮 Game Night Stembus Geopend!",
            description=f"Stuur een **DM** met `!stem Game 1, Game 2, Game 3`.\n\n{rules}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        self.is_open = False
        await ctx.send("🛑 De stembus is gesloten!")

    @commands.command()
    async def stem(self, ctx, *, games_input: str):
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(f"{ctx.author.mention}, stuur dit in een DM! 🤫", delete_after=5)

        if not self.is_open:
            return await ctx.send("⛔ De stembus is gesloten.")

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
            return await ctx.send("Ik snapte geen enkele game. Gebruik komma's: `!stem Game A, Game B`")

        clean_games = clean_games[:3]
        self.votes[ctx.author.id] = clean_games
        
        # Feedback Bericht
        msg = "✅ **Stemmen Ontvangen!**\n"
        
        # Laat Marco weten dat we hem geholpen hebben
        if corrections:
            msg += "\n🪄 *Autocorrect:* " + ", ".join(corrections) + "\n\n"

        msg += "**Jouw lijstje:**\n"
        for i, game in enumerate(clean_games, 1):
            if self.weighted_mode:
                points = 4 - i
                msg += f"#{i} **{game}** ({points} pnt)\n"
            else:
                msg += f"- **{game}**\n"
        
        await ctx.send(msg)

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        if not self.votes:
            return await ctx.send("Nog niemand heeft gestemd.")
        count = len(self.votes)
        await ctx.send(f"🗳️ Er hebben al **{count}** mensen gestemd.")

    @gamenight.command(name="uitslag")
    @commands.admin_or_permissions(administrator=True)
    async def gn_uitslag(self, ctx):
        if not self.votes:
            return await ctx.send("Er is niet gestemd.")

        scores = defaultdict(int)
        vote_counts = defaultdict(int)

        for user_games in self.votes.values():
            for i, game in enumerate(user_games):
                points = (3 - i) if self.weighted_mode else 1
                scores[game] += points
                vote_counts[game] += 1

        sorted_games = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        embed = discord.Embed(title="🏆 De Uitslag", color=discord.Color.gold())
        desc = ""
        for i, (game, score) in enumerate(sorted_games, 1):
            votes = vote_counts[game]
            emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**#{i}**"
            p_text = "punten" if self.weighted_mode else "stemmen"
            desc += f"{emoji} **{game}**\n╚ *{score} {p_text}* ({votes} stemmers)\n\n"
            if i >= 10: break

        embed.description = desc
        embed.set_footer(text=f"Totaal {len(self.votes)} stemmers.")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GameNight(bot))
