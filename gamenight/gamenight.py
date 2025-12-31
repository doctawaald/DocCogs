from redbot.core import commands
from collections import defaultdict
import discord

class GameNight(commands.Cog):
    """Geavanceerde Game Night Voting plugin met instelbare puntentelling."""

    def __init__(self, bot):
        self.bot = bot
        # Structuur: {user_id: ['Game1', 'Game2', 'Game3']}
        self.votes = {}
        self.is_open = False
        # Als True: 3-2-1 punten. Als False: 1-1-1 punten.
        self.weighted_mode = True 

    @commands.group(name="gn", invoke_without_command=True)
    async def gamenight(self, ctx):
        """Hoofdcommando voor Game Night."""
        await ctx.send_help(ctx.command)

    @gamenight.command(name="mode")
    @commands.admin_or_permissions(administrator=True)
    async def gn_mode(self, ctx):
        """Wisselt tussen Bonuspunten (3-2-1) en Simpel tellen (1-1-1)."""
        self.weighted_mode = not self.weighted_mode
        
        if self.weighted_mode:
            status = "**AAN** (Top 3 krijgt 3, 2, 1 punten)"
        else:
            status = "**UIT** (Elke game krijgt 1 punt, volgorde maakt niet uit)"
            
        await ctx.send(f"⚖️ Bonuspunten systeem staat nu {status}.")

    @gamenight.command(name="open")
    @commands.admin_or_permissions(administrator=True)
    async def gn_open(self, ctx):
        """Opent de stembus en toont de huidige regels."""
        self.is_open = True
        self.votes.clear()
        
        # Tekst aanpassen op basis van de modus
        if self.weighted_mode:
            rules_text = ("🥇 Keuze 1 krijgt **3 punten**\n"
                          "🥈 Keuze 2 krijgt **2 punten**\n"
                          "🥉 Keuze 3 krijgt **1 punt**")
        else:
            rules_text = "Elke game die je noemt krijgt **1 punt**.\nDe volgorde maakt niet uit."

        embed = discord.Embed(
            title="🎮 Game Night Stembus Geopend!",
            description=f"Stuur mij een **Privébericht (DM)** met `!stem Game 1, Game 2, Game 3`.\n\n{rules_text}",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Modus: {'Bonuspunten' if self.weighted_mode else 'Simpel'}")
        await ctx.send(embed=embed)

    @gamenight.command(name="close")
    @commands.admin_or_permissions(administrator=True)
    async def gn_close(self, ctx):
        """Sluit de stembus."""
        self.is_open = False
        await ctx.send("🛑 De stembus is gesloten! Tijd voor de uitslag...")

    @commands.command()
    async def stem(self, ctx, *, games_input: str):
        """Stem via DM: !stem Game1, Game2, Game3"""
        
        if ctx.guild is not None:
            await ctx.message.delete(delay=1)
            return await ctx.send(f"{ctx.author.mention}, stuur dit in een DM naar mij! 🤫", delete_after=5)

        if not self.is_open:
            return await ctx.send("⛔ De stembus is momenteel gesloten.")

        raw_games = games_input.split(',')
        clean_games = [g.strip().title() for g in raw_games if g.strip()]

        if not clean_games:
            return await ctx.send("Gebruik: `!stem Game A, Game B`")

        clean_games = clean_games[:3]
        self.votes[ctx.author.id] = clean_games
        
        # Feedback naar de gebruiker aanpassen
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

        voters = []
        for user_id in self.votes.keys():
            user = self.bot.get_user(user_id)
            voters.append(user.name if user else "Onbekende speler")

        embed = discord.Embed(title="🗳️ Huidige Status", color=discord.Color.blue())
        embed.add_field(name=f"Aantal stemmers: {len(voters)}", value=", ".join(voters), inline=False)
        await ctx.send(embed=embed)

    @gamenight.command(name="uitslag")
    @commands.admin_or_permissions(administrator=True)
    async def gn_uitslag(self, ctx):
        """Berekent de score en toont de winnaar."""
        if not self.votes:
            return await ctx.send("Er is niet gestemd.")

        scores = defaultdict(int)
        vote_counts = defaultdict(int)

        for user_games in self.votes.values():
            for i, game in enumerate(user_games):
                # HIER zit de logica wissel
                if self.weighted_mode:
                    points = 3 - i # 3, 2, of 1 punt
                else:
                    points = 1     # Altijd 1 punt
                
                scores[game] += points
                vote_counts[game] += 1

        sorted_games = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        embed = discord.Embed(
            title="🏆 De Uitslag is bekend!", 
            description=f"Modus: **{'Bonuspunten (3-2-1)' if self.weighted_mode else 'Meeste stemmen gelden'}**",
            color=discord.Color.gold()
        )
        
        desc = ""
        for i, (game, score) in enumerate(sorted_games, 1):
            votes = vote_counts[game]
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**#{i}**"
            
            # Tekst aanpassen: bij gewogen modus tonen we punten, bij simpele modus aantal stemmen
            if self.weighted_mode:
                score_text = f"{score} punten"
            else:
                score_text = f"{score} stemmen"

            desc += f"{emoji} **{game}**\n╚ *{score_text}* (gekozen door {votes} spelers)\n\n"
            
            if i >= 10: 
                desc += f"*...en nog {len(sorted_games) - 10} andere games.*"
                break

        embed.description = desc
        embed.set_footer(text=f"Totaal {len(self.votes)} mensen hebben gestemd.")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GameNight(bot))
