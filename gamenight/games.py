# games.py — Gamelijst voor GameNight
#
# "aliases"     : alternatieve namen, afkortingen en veelgemaakte spelfouten
# "max_players" : maximale gezamenlijke groep in de hieronder bedoelde spelmodus
#
# Uitgangspunt: normale spelmodi, zonder mods.
# Bij competitieve games telt de party/teamgrootte, niet de volledige match.
# Bij co-op- en partygames telt de gezamenlijke sessie/lobby.
#
# None betekent: afhankelijk van server/versie, geen vaste limiet,
# of geen betrouwbaar vastgesteld maximum. Het betekent niet altijd onbeperkt.

GAMES = {
    # ── SHOOTERS ────────────────────────────────────────────────────────────
    "Fortnite": {
        "aliases": [
            "fn", "fort", "build", "fortnite", "fortnight",
            "fornite", "fourtnite", "fortnitet"
        ],
        "max_players": 4,  # Battle Royale / Zero Build Squads.
    },
    "Escape from Tarkov": {
        "aliases": ["eft", "tarkov", "tarkof"],
        "max_players": 5,  # PMC-groep; andere modi kunnen afwijken.
    },
    "The Finals": {
        "aliases": ["finals", "thefinals"],
        "max_players": 5,  # Power Shift; Cashout/Ranked Cashout: 3.
    },

    # ── SURVIVAL & CRAFTING ─────────────────────────────────────────────────
    "Minecraft": {
        "aliases": [
            "mc", "mine", "craft", "minecraft",
            "mincraft", "maincraft", "blokjes"
        ],
        "max_players": None,  # Afhankelijk van editie en serverinstellingen.
    },
    "Valheim": {
        "aliases": ["valheim", "viking"],
        "max_players": 10,
    },
    "Palworld": {
        "aliases": ["pal", "pals", "palworld", "pokemon", "palword"],
        "max_players": 4,  # Gewone co-op; dedicated server: maximaal 32.
    },
    "Hytale": {
        "aliases": ["hytale", "hy", "tale"],
        "max_players": None,  # Afhankelijk van serverinstellingen/capaciteit.
    },
    "Voyagers of Nera": {
        "aliases": ["von", "nera", "voyagers", "voyager", "voyagersofnera"],
        "max_players": 10,
    },
    "Windrose": {
        "aliases": ["wr", "windrose", "wind", "rose", "pirates"],
        "max_players": 8,  # Ondersteund maximum; maximaal 4 aanbevolen.
    },

    # ── HORROR & CO-OP ──────────────────────────────────────────────────────
    "Lethal Company": {
        "aliases": [
            "lethal", "lc", "company",
            "lethalcompany", "leathal", "lethalcomp"
        ],
        "max_players": 4,  # Zonder mods.
    },
    "The Outlast Trials": {
        "aliases": [
            "trials", "tot", "outlast", "outlasttrials",
            "outlas", "out last", "trails", "triels"
        ],
        "max_players": 4,  # Reguliere co-opgroep.
    },
    "Phasmophobia": {
        "aliases": [
            "phas", "phasmo", "ghosts", "phasmophobia",
            "phasmofobia", "fasmophobia"
        ],
        "max_players": 4,
    },
    "Sons of the Forest": {
        "aliases": ["sotf", "sons", "forest", "forest2", "sonsoftheforest"],
        "max_players": 8,
    },
    "R.E.P.O.": {
        "aliases": ["repo", "r.e.p.o", "repo game"],
        "max_players": 6,  # Zonder mods.
    },
    "Mimesis": {
        "aliases": [
            "mimesis", "mime", "mimisis",
            "memesis", "meme", "mimi"
        ],
        "max_players": 4,
    },
    "Sea of Thieves": {
        "aliases": ["sot", "sea", "thieves", "seaofthieves"],
        "max_players": 4,  # Eén Galleon; Brigantine: 3, Sloop: 2.
    },
    "Lockdown Protocol": {
        "aliases": ["lockdown", "protocol", "lp", "lockdownprotocol"],
        "max_players": 16,
    },

    # ── SOCIAL & PARTY ──────────────────────────────────────────────────────
    "Among Us": {
        "aliases": [
            "amogus", "au", "sus",
            "among", "impostor", "amongus"
        ],
        "max_players": 15,
    },
    "Fall Guys": {
        "aliases": ["fall", "guys", "fallguys", "beans", "fallguy"],
        "max_players": 4,  # Normale party; Custom Shows kunnen groter zijn.
    },
    "Pummel Party": {
        "aliases": ["pummel", "pumparty", "pummelparty"],
        "max_players": 8,
    },
    "Golf It!": {
        "aliases": ["golfit", "golf"],
        "max_players": None,  # Geen vaste online spelerslimiet; hostafhankelijk.
    },
    "Golf With Your Friends": {
        "aliases": ["gwyf", "golfwithfriends", "golf friends", "golfwith"],
        "max_players": 12,
    },
    "Gang Beasts": {
        "aliases": ["gang", "beasts", "gangbeasts", "gelly"],
        "max_players": 8,  # Reguliere versus-lobby.
    },
    "Dale & Dawson Stationery Supplies": {
        "aliases": [
            "dale", "dawson", "ddss",
            "stationery", "manager", "daleanddawson"
        ],
        "max_players": 21,  # Mapafhankelijk; sommige kantoren maximaal 18.
    },
    "Meccha Chameleon": {
        "aliases": [
            "meccha chameleon", "mecchachameleon",
            "mecha chameleon", "mechachameleon",
            "chameleon", "meccha", "mecha", "cham",
            "verfspel", "verstoppertje", "kameleon",
            "verf", "verstop", "verstoppen",
            "meccha kameleon", "mecha kameleon"
        ],
        "max_players": None,  # Hostafhankelijk; 2–10 spelers aanbevolen.
    },
    "Mario Party (4-7)": {
        "aliases": ["marioparty", "mario", "board"],
        "max_players": 4,  # Gewone bordmodus; MP7 heeft ook een 8-spelermodus.
    },

    # ── SPORTS & RACING ─────────────────────────────────────────────────────
    "Rocket League": {
        "aliases": ["rocket", "rl", "rocketleague", "cars", "soccer"],
        "max_players": 4,  # Casual Quads; Standard: 3, Doubles: 2.
    },
    "Mario Kart": {
        "aliases": ["karting", "mariokart", "kart", "race"],
        "max_players": None,  # Specificeer eerst welke versie jullie spelen.
    },

    # ── RPG & MMO ───────────────────────────────────────────────────────────
    "Palia": {
        "aliases": ["palia", "pallia"],
        "max_players": 4,  # Party; de gedeelde server kan meer spelers bevatten.
    },
    "Grand Theft Auto V": {
        "aliases": ["gta", "gta5", "gtav", "gtaonline", "gta 5"],
        "max_players": 30,  # GTA Online-freemode; heists/missies vaak lager.
    },

    # ── SIMULATORS & OVERIGE ────────────────────────────────────────────────
    "Schedule 1": {
        "aliases": [
            "s1", "sched1", "schedule1", "schedule one",
            "sched 1", "schedule", "drugs", "weed", "cocaine"
        ],
        "max_players": 4,  # Normale co-op, zonder mods.
    },
}
