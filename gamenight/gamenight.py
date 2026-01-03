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
        """Close the voting lines AND
