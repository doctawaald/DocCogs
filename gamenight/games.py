# games.py — Gamenight game list
# Each game has:
#   "aliases"     : list of spelling variants / abbreviations
#   "max_players" : max party size (None = unlimited / unknown)

GAMES = {
    # ── SHOOTERS ──────────────────────────────────────────────────────────────
    "Fortnite": {
        "aliases": ["fn", "fort", "build", "fortnite", "fortnight", "fornite", "fourtnite", "fortnitet"],
        "max_players": 4,
    },
    "Escape from Tarkov": {
        "aliases": ["eft", "tarkov", "tarkof"],
        "max_players": 5,
    },
    "The Finals": {
        "aliases": ["finals", "thefinals"],
        "max_players": 4,
    },

    # ── SURVIVAL & CRAFTING ───────────────────────────────────────────────────
    "Minecraft": {
        "aliases": ["mc", "mine", "craft", "minecraft", "mincraft", "maincraft", "blokjes"],
        "max_players": None,
    },
    "Valheim": {
        "aliases": ["valheim", "viking"],
        "max_players": 10,
    },
    "Palworld": {
        "aliases": ["pal", "pals", "palworld", "pokemon", "palword"],
        "max_players": 4,
    },
    "Hytale": {
        "aliases": ["hytale", "hy", "tale"],
        "max_players": None,
    },
    "Voyagers of Nera": {
        "aliases": ["von", "nera", "voyagers", "voyager", "voyagersofnera"],
        "max_players": None,
    },
    "Windrose": {
        "aliases": ["wr", "windrose", "wind", "rose", "pirates"],
        "max_players": 8,
    },

    # ── HORROR & CO-OP ────────────────────────────────────────────────────────
    "Lethal Company": {
        "aliases": ["lethal", "lc", "company", "lethalcompany", "leathal", "lethalcomp"],
        "max_players": 4,
    },
    "The Outlast Trials": {
        "aliases": ["trials", "tot", "outlast", "outlasttrials", "outlas", "out last", "trails", "triels"],
        "max_players": 4,
    },
    "Phasmophobia": {
        "aliases": ["phas", "phasmo", "ghosts", "phasmophobia", "phasmofobia", "fasmophobia"],
        "max_players": 4,
    },
    "Sons of the Forest": {
        "aliases": ["sotf", "sons", "forest", "forest2", "sonsoftheforest"],
        "max_players": 8,
    },
    "R.E.P.O.": {
        "aliases": ["repo", "r.e.p.o", "repo game"],
        "max_players": 6,
    },
    "Sea of Thieves": {
        "aliases": ["sot", "sea", "thieves", "seaofthieves"],
        "max_players": 4,
    },
    "Lockdown Protocol": {
        "aliases": ["lockdown", "protocol", "lp", "lockdownprotocol"],
        "max_players": 6,
    },

    # ── SOCIAL & PARTY ────────────────────────────────────────────────────────
    "Among Us": {
        "aliases": ["amogus", "au", "sus", "among", "impostor", "amongus"],
        "max_players": 15,
    },
    "Fall Guys": {
        "aliases": ["fall", "guys", "fallguys", "beans", "fallguy"],
        "max_players": None,
    },
    "Pummel Party": {
        "aliases": ["pummel", "pumparty", "pummelparty"],
        "max_players": 8,
    },
    "Golf It!": {
        "aliases": ["golfit", "golf"],
        "max_players": 8,
    },
    "Golf With Your Friends": {
        "aliases": ["gwyf", "golfwithfriends", "golf friends", "golfwith"],
        "max_players": 12,
    },
    "Gang Beasts": {
        "aliases": ["gang", "beasts", "gangbeasts", "gelly"],
        "max_players": 8,
    },
    "Dale & Dawson Stationery Supplies": {
        "aliases": ["dale", "dawson", "ddss", "stationery", "manager", "daleanddawson"],
        "max_players": 4,
    },
    "Mario Party (4-7)": {
        "aliases": ["marioparty", "mario", "board"],
        "max_players": 4,
    },

    # ── SPORTS & RACING ───────────────────────────────────────────────────────
    "Rocket League": {
        "aliases": ["rocket", "rl", "rocketleague", "cars", "soccer"],
        "max_players": None,
    },
    "Mario Kart": {
        "aliases": ["karting", "mariokart", "kart", "race"],
        "max_players": None,
    },

    # ── RPG & MMO ────────────────────────────────────────────────────────────
    "Palia": {
        "aliases": ["palia", "pallia"],
        "max_players": None,
    },
    "Grand Theft Auto V": {
        "aliases": ["gta", "gta5", "gtav", "gtaonline", "gta 5"],
        "max_players": None,
    },

    # ── SIMULATORS & OTHER ───────────────────────────────────────────────────
    "Schedule 1": {
        "aliases": ["s1", "sched1", "schedule1", "schedule one", "sched 1", "schedule", "drugs", "weed", "cocaine"],
        "max_players": 4,
    },
}
