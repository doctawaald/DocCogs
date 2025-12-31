from redbot.core import commands
from collections import defaultdict
import discord
import re

# --- CONFIGURATIE ---
# Een uitgebreide lijst met populaire games en hun aliassen.
GAME_ALIASES = {
    # --- SHOOTERS ---
    "Call of Duty": ["cod", "mw3", "mw2", "warzone", "bo6", "blackops"],
    "Counter-Strike 2": ["cs2", "cs", "csgo", "counterstrike", "globaloffensive"],
    "Valorant": ["val", "valo", "valorant"],
    "Overwatch 2": ["ow", "ow2", "overwatch"],
    "Fortnite": ["fn", "fort", "build", "fortnite"],
    "Apex Legends": ["apex", "apexlegends"],
    "Tom Clancy's Rainbow Six Siege": ["r6", "siege", "rainbow", "rss", "rainbowsix"],
    "Team Fortress 2": ["tf2", "teamfortress"],
    "Escape from Tarkov": ["eft", "tarkov"],
    "Destiny 2": ["destiny", "d2"],
    "Halo Infinite": ["halo", "infinite"],
    "The Finals": ["finals"],
    "PUBG: Battlegrounds": ["pubg", "plunkbat"],

    # --- SURVIVAL & CRAFTING ---
    "Minecraft": ["mc", "mine", "craft", "minecraft"],
    "Terraria": ["terra", "terraria"],
    "Rust": ["rust"],
    "Ark: Survival Ascended": ["ark", "asa", "ase"],
    "Valheim": ["valheim", "viking"],
    "Raft": ["raft"],
    "Palworld": ["pal", "pals", "palworld", "pokemonmetguns"],
    "DayZ": ["dayz"],
    "7 Days to Die": ["7days", "7d2d", "7dtd"],
    "No Man's Sky": ["nms", "nomanssky"],
    "Project Zomboid": ["pz", "zomboid"],

    # --- HORROR & CO-OP ---
    "Lethal Company": ["lethal", "lc", "company", "lethalcompany"],
    "Phasmophobia": ["phas", "phasmo", "ghosts"],
    "Dead by Daylight": ["dbd", "deadby", "deadbydaylight"],
    "Sons of the Forest": ["sotf", "sons", "forest"],
    "Content Warning": ["content", "warning", "cw", "camera"],
    "Left 4 Dead 2": ["l4d2", "l4d"],
    "Deep Rock Galactic": ["drg", "deeprock", "rockandstone", "dwarves"],
    "Helldivers 2": ["helldivers", "hd2", "democracy", "super earth"],
    "R.E.P.O.": ["repo", "r.e.p.o"],
    "Sea of Thieves": ["sot", "sea", "thieves", "pirates"],
    "Garry's Mod": ["gmod", "garrys"],
    
    # --- SOCIAL & PARTY ---
    "Among Us": ["amogus", "au", "sus", "among", "impostor"],
    "The Jackbox Party Pack": ["jackbox", "jb", "jack", "box"],
    "Fall Guys": ["fall", "guys", "fallguys", "beans"],
    "Pummel Party": ["pummel", "party"],
    "Golf It!": ["golfit", "golf"],

    # --- MOBA & STRATEGY ---
    "League of Legends": ["lol", "league", "leagueoflegends"],
    "Dota 2": ["dota"],

    # --- SPORTS & RACING ---
    "Rocket League": ["rocket", "rl", "rocketleague", "cars"],
    "Mario Kart": ["mario", "mariokart", "kart"],

    # --- RPG & MMO ---
    "World of Warcraft": ["wow", "warcraft"],
    "Baldur's Gate 3": ["bg3", "baldur", "baldurs"],
    "Path of Exile": ["poe", "path"],
    "Grand Theft Auto V": ["gta", "gta5", "gtav", "gtaonline"]
}

class GameNight(commands.Cog):
    """Geavanceerde Game Night Voting plugin met naam-herkenning."""

    def __init__(self, bot):
        self.bot = bot
        self.votes = {}
        self.is_open = False
        self.weighted_mode = True 

    def normalize_game_name(self, user_input):
        """
        Probeert de rommelige input van een user om te zetten naar een nette game naam.
        """
        # 1. Alles naar kleine letters en witruimte rondom weg
        clean_input = user_input.strip().lower()
        
        # 2. Check de Alias lijst (exacte match op afkorting)
        for official_name, aliases in GAME_ALIASES.items():
            # Check of de input matcht met de officiële naam (kleine letters)
            if clean_input == official_name.lower():
                return official_name
            # Check of de input in de lijst met afkortingen staat
            if clean_input in aliases:
                return official_name

        # 3. Slimme schoonmaak: verwijder alles wat geen letter of cijfer is
        # Dit zorgt dat "R.E.P.O" -> "repo" wordt, en "CS:GO" -> "csgo"
        # We doen dit alleen voor de check, we returnen de 'mooie' versie niet direct.
        stripped_input = re.sub(r'[^a-z0-9]', '', clean_input)
        
        for official_name, aliases in GAME_ALIASES.items():
            # We strippen ook de aliases even kaal voor de vergelijking
            stripped_aliases = [re.sub(r'[^a-z0-9]', '', a) for a in aliases]
            if stripped_input in stripped_aliases:
                return official_name

        # 4. Als we niks vinden, maken we er gewoon een nette Title Case van.
        # "mijn rare game" -> "Mijn Rare Game"
        return user_input.strip().title()

    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        """Hoofdcommando voor Game Night."""
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        """Wisselt tussen Bonuspunten (3-2-1) en Simpel tellen (1-1-1)."""
        self.weighted_mode = not self.weighted_mode
        status = "**AAN** (3-2-1)" if self.weighted_mode else "**UIT** (1-1-1)"
        await ctx.send(f"⚖️ Bonuspunten systeem staat nu {status}.")

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        """Opent de stembus."""
        self.is_open = True
        self.votes.clear()
        
        rules = "🥇 3 pnt | 🥈 2 pnt | 🥉 1 pnt" if self.weighted_mode else "Elke stem is 1 punt."

        embed = discord.Embed(
            title="🎮 Game Night Stembus Geopend!",
            description=f"Stuur mij een **DM** met `!stem Game 1, Game 2, Game 3`.\n\n{rules}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        """Sluit de stembus."""
        self.is_open = False
        await ctx.send("🛑 De stembus is gesloten!")

    @commands.command()
    async def stem(self, ctx, *, games_input: str):
        """Stem via DM: !stem Game1, Game2, Game3"""
        
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(f"{ctx.author.mention}, stuur dit in een DM! 🤫", delete_after=5)

        if not self.is_open:
            return await ctx.send("⛔ De stembus is gesloten.")

        # Inputs splitsen
        raw_games = games_input.split(',')
        
        # --- HIER GEBEURT DE MAGIE ---
        clean_games = []
        for g in raw_games:
            if g.strip(): # Als het niet leeg is
                # We sturen het door onze slimme functie
                corrected_name = self.normalize_game_name(g)
                clean_games.append(corrected_name)
        # -----------------------------

        if not clean_games:
            return await ctx.send("Gebruik: `!stem Game A, Game B`")

        clean_games = clean_games[:3]
        self.votes[ctx.author.id] = clean_games
        
        msg = "Ik heb je stemmen genoteerd:\n"
        for i, game in enumerate(clean_games, 1):
            if self.weighted_mode:
                points = 4 - i
                msg += f"**#{i}** {game} ({points} pnt)\n"
            else:
                msg += f"- {game}\n"
        
        await ctx.send(msg)

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        """Kijk wie er al gestemd heeft."""
        if not self.votes:
            return await ctx.send("Nog niemand heeft gestemd.")
        
        count = len(self.votes)
        await ctx.send(f"🗳️ Er hebben al **{count}** mensen gestemd.")

    @gamenight.command(name="uitslag")
    @commands.admin_or_permissions(administrator=True)
    async def gn_uitslag(self, ctx):
        """Toont de winnaar."""
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
