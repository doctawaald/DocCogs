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
    "Borderlands": ["borderlands", "bl", "bl2", "bl3", "border", "tiny tina", "wonderlands"],

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
    "Hytale": ["hytale", "hy", "tale"],
    "Voyagers of Nera": ["von", "nera", "voyagers", "voyager", "voyagersofnera"],

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
    "Lockdown Protocol": ["lockdown", "protocol", "lp", "lockdownprotocol"],
    
    # SOCIAL & PARTY
    "Among Us": ["amogus", "au", "sus", "among", "impostor", "amongus"],
    "The Jackbox Party Pack": ["jackbox", "jb", "jack", "box"],
    "Fall Guys": ["fall", "guys", "fallguys", "beans", "fallguy"],
    "Pummel Party": ["pummel", "party", "pummelparty"],
    "Golf It!": ["golfit", "golf"],
    "Golf With Your Friends": ["gwyf", "golfwithfriends", "golf friends", "golfwith"],
    "Gang Beasts": ["gang", "beasts", "gangbeasts", "gelly"],
    "Dale & Dawson Stationery Supplies": ["dale", "dawson", "ddss", "stationery", "manager", "daleanddawson"],

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
    "Grand Theft Auto V": ["gta", "gta5", "gtav", "gtaonline", "gta 5"],
    
    # SIMULATORS & OTHER
    "Schedule 1": ["s1", "sched1", "schedule1", "schedule one", "sched 1", "schedule", "drugs", "weed", "cocaine"]
}

class GameNight(commands.Cog):
    """The Ultimate Game Night Plugin: Clean, Secret & Stats."""

    def __init__(self, bot):
        self.bot = bot
        self.votes = {}
        self.is_open = False
        
        # Voor de RSVP Check
        self.vote_message = None
        self.vote_channel = None
        self.all_voted_notified = False
        
        # Database setup
        self.config = Config.get_conf(self, identifier=847372839210)
        default_global = {
            "game_wins": {}, 
            "total_sessions": 0,
            "weighted_mode": True,   
            "veto_mode": False       
        }
        self.config.register_global(**default_global)

    def normalize_game_name(self, user_input):
        clean_input = user_input.strip().lower()
        if not clean_input:
            return None, False

        for official_name, aliases in GAME_ALIASES.items():
            if clean_input == official_name.lower() or clean_input in aliases:
                return official_name, False

        all_possibilities = {name.lower(): name for name, aliases in GAME_ALIASES.items()}
        for name, aliases in GAME_ALIASES.items():
            for a in aliases:
                all_possibilities[a] = name
        
        matches = difflib.get_close_matches(clean_input, all_possibilities.keys(), n=1, cutoff=0.6)
        
        if matches:
            return all_possibilities[matches[0]], True 

        return user_input.strip().title(), False

    async def check_completion(self):
        """Checkt of iedereen die op ✅ heeft geklikt ook echt gestemd heeft."""
        if not self.is_open or not self.vote_message or not self.vote_channel or self.all_voted_notified:
            return

        try:
            # Haal het actuele bericht op (om de nieuwste reacties te zien)
            msg = await self.vote_channel.fetch_message(self.vote_message.id)
            yes_reaction = discord.utils.get(msg.reactions, emoji="✅")
            
            if not yes_reaction:
                return

            # Lijst van spelers die ✅ hebben geklikt (negeer de bot)
            yes_users = [user async for user in yes_reaction.users() if not user.bot]

            if not yes_users:
                return 

            # Controleer of al deze users in de self.votes dictionary staan
            missing = [user for user in yes_users if user.id not in self.votes]

            if not missing: # Iedereen heeft gestemd!
                self.all_voted_notified = True
                embed = discord.Embed(
                    title="🎉 All votes are in!",
                    description="Everyone who RSVP'd has voted.\nThe admin can now use `!gn close`.",
                    color=discord.Color.blue()
                )
                await self.vote_channel.send(embed=embed)

        except discord.NotFound:
            pass # Bericht is verwijderd
        except Exception as e:
            print(f"Error checking completion: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Zorgt ervoor dat de bot het direct checkt als iemand achteraf op ✅ klikt."""
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
        self.all_voted_notified = False # Reset de trigger
        
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
            color=discord.Color.green()
        )
        # De RSVP Vraag
        embed.add_field(
            name="Are you gaming tonight?", 
            value="Click ✅ if you are playing.\nClick ❌ if you can't make it.", 
            inline=False
        )
        
        msg = await ctx.send(embed=embed)
        self.vote_message = msg
        self.vote_channel = ctx.channel
        
        # Voeg direct de reacties toe
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        self.is_open = False
        self.all_voted_notified = False
        await ctx.send("🛑 **Voting is closed!** calculating results...")
        await self.gn_results(ctx)

    @commands.command()
    async def vote(self, ctx, *, games_input: str):
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(f"{ctx.author.mention}, please send this in a DM! 🤫", delete_after=5)

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

        # 1. Positieve Votes
        raw_pos_games = pos_input.split(',')
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

        # 2. Negatieve Vote (Fix: Split op komma, pak alleen eerste)
        clean_neg_game = None
        if neg_input and neg_input.strip():
            raw_neg_games = neg_input.split(',')
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
        
        await ctx.send(msg)
        
        # Check direct of dit de laatste missende stemmer was!
        await self.check_completion()

    @gamenight.command(name="status")
    async def gn_status(self, ctx):
        if not self.is_open:
            return await ctx.send("De stembus is momenteel gesloten.")
            
        count = len(self.votes)
        msg_text = f"🗳️ We currently have **{count}** votes.\n"

        # Check wie er missen
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
                pass # Als het originele bericht is verwijderd, skipt hij dit
        
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
            
            emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**#{i}**"
            
            vote_text = f"{pos_votes} up"
            if neg_votes > 0:
                vote_text += f", {neg_votes} down 💀"
            
            desc += f"{emoji} **{game}**\n╚ **{score} pts** ({vote_text})\n\n"
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

        async with self.config.game_wins() as wins:
            current = wins.get(final_winner, 0)
            wins[final_winner] = current + 1
        
        count = await self.config.total_sessions()
        await self.config.total_sessions.set(count + 1)

async def setup(bot):
    await bot.add_cog(GameNight(bot))
