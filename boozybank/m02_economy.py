# [02] ECONOMY — saldo bekijken, leaderboard, geven en admin-set

import discord
from redbot.core import commands, checks

class EconomyMixin:
    # ------- Helpers -------
    async def _get_balance(self, member: discord.abc.User) -> int:
        return int(await self.config.user(member).booz())

    async def _set_balance(self, member: discord.abc.User, amount: int) -> None:
        await self.config.user(member).booz.set(int(max(0, amount)))

    # ------- User commands -------
    @commands.command(aliases=["booz", "balance", "bal"])
    async def boozybal(self, ctx: commands.Context):
        """Toon je Boo'z saldo."""
        bal = await self._get_balance(ctx.author)
        await ctx.send(f"💰 {ctx.author.mention}, je hebt **{bal} Boo'z**.")

    @commands.command(aliases=["leaderboard", "top"])
    async def boozytop(self, ctx: commands.Context):
        """Top 10 Boo'z bezitters in deze server."""
        allu = await self.config.all_users()
        # Filter op leden die in deze guild zitten
        rows = []
        for uid, data in allu.items():
            m = ctx.guild.get_member(int(uid))
            if m:
                rows.append((m, int(data.get("booz", 0))))
        rows.sort(key=lambda x: x[1], reverse=True)
        top = rows[:10]

        if not top:
            return await ctx.send("🥇 **Boozy Top 10**\n_Nog geen data_")

        lines = [f"{i}. **{m.display_name}** — {bal} Boo'z" for i, (m, bal) in enumerate(top, 1)]
        await ctx.send("🥇 **Boozy Top 10**\n" + "\n".join(lines))

    @commands.command()
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Geef Boo'z aan iemand: !give @user 25"""
        if member.bot:
            return await ctx.send("❌ Je kunt geen Boo'z geven aan bots.")
        if amount <= 0:
            return await ctx.send("❌ Bedrag moet > 0 zijn.")

        your = await self._get_balance(ctx.author)
        if your < amount:
            return await ctx.send("❌ Niet genoeg Boo'z.")
        await self._set_balance(ctx.author, your - amount)

        other = await self._get_balance(member)
        await self._set_balance(member, other + amount)

        await ctx.send(f"💸 {ctx.author.mention} gaf **{amount} Boo'z** aan {member.mention}.")

    # ------- Admin commands -------
    @commands.command()
    @checks.admin()
    async def addmoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Admin: tel Boo'z bij een gebruiker op."""
        if amount <= 0:
            return await ctx.send("❌ Bedrag moet > 0 zijn.")
        bal = await self._get_balance(member)
        await self._set_balance(member, bal + amount)
        await ctx.send(f"✅ **{member.display_name}** heeft nu **{bal + amount} Boo'z** ( +{amount} ).")

    @commands.command()
    @checks.admin()
    async def removemoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Admin: haal Boo'z weg bij een gebruiker."""
        if amount <= 0:
            return await ctx.send("❌ Bedrag moet > 0 zijn.")
        bal = await self._get_balance(member)
        new = max(0, bal - amount)
        await self._set_balance(member, new)
        await ctx.send(f"✅ **{member.display_name}** heeft nu **{new} Boo'z** ( -{amount} ).")

    @commands.command()
    @checks.admin()
    async def setmoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Admin: zet Boo'z saldo direct op een waarde."""
        if amount < 0:
            return await ctx.send("❌ Bedrag kan niet negatief zijn.")
        await self._set_balance(member, amount)
        await ctx.send(f"🧮 **{member.display_name}** staat nu op **{amount} Boo'z**.")
