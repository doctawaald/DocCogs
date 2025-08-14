# M02 --- ECONOMY -----------------------------------------------------------
from __future__ import annotations
from typing import List, Tuple
import discord
from redbot.core import commands, checks

COIN = "🪙"


class EconomyMixin:
    # M02#1 HELPERS
    async def _get_balance(self, member: discord.Member) -> int:
        return int(await self.config.user(member).booz())

    async def _set_balance(self, member: discord.Member, value: int) -> None:
        await self.config.user(member).booz.set(max(0, int(value)))

    async def _add_balance(self, member: discord.Member, delta: int) -> int:
        cur = await self._get_balance(member)
        newv = max(0, cur + int(delta))
        await self._set_balance(member, newv)
        return newv

    # M02#2 BALANCE
    @commands.command(aliases=["bal", "balance", "boozybal"])
    async def booz(self, ctx: commands.Context, member: discord.Member | None = None):
        """Toon je Boo'z saldo (of dat van iemand anders)."""
        target = member or ctx.author
        if target.bot:
            return await ctx.send("🤖 Bots hebben geen Boo'z.")
        bal = await self._get_balance(target)
        who = "jouw" if target == ctx.author else f"{target.display_name}"
        await ctx.send(f"{COIN} **Boo'z** — {who}: **{bal}**")

    # M02#3 LEADERBOARD
    @commands.command(aliases=["leaderboard", "boozytop"])
    async def top(self, ctx: commands.Context, limit: int = 10):
        """Toon de top Boo'z in deze server (default 10)."""
        limit = max(1, min(25, int(limit)))
        rows: List[Tuple[int, discord.Member]] = []
        for m in ctx.guild.members:
            if m.bot:
                continue
            bal = await self._get_balance(m)
            if bal > 0:
                rows.append((bal, m))
        if not rows:
            return await ctx.send("📉 Nog geen Boo'z data.")
        rows.sort(key=lambda x: x[0], reverse=True)
        lines = [f"🏆 **Leaderboard (top {limit})**"]
        for i, (bal, m) in enumerate(rows[:limit], start=1):
            lines.append(f"{i}. {m.display_name} — {COIN} {bal}")
        await ctx.send("\n".join(lines))

    # M02#4 ADMIN GRANTS/TAKES
    @commands.command()
    @checks.admin()
    async def boozygive(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Geef Boo'z aan een gebruiker."""
        if member.bot:
            return await ctx.send("🤖 Bots kunnen geen Boo'z krijgen.")
        amount = int(amount)
        if amount <= 0:
            return await ctx.send("Geef een positief aantal.")
        newv = await self._add_balance(member, amount)
        await ctx.send(f"✅ Gaf **{member.display_name}** {COIN} {amount}. Nieuw saldo: {newv}")

    @commands.command()
    @checks.admin()
    async def boozytake(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Neem Boo'z af van een gebruiker."""
        if member.bot:
            return await ctx.send("🤖 Bots hebben geen Boo'z.")
        amount = int(amount)
        if amount <= 0:
            return await ctx.send("Geef een positief aantal.")
        cur = await self._get_balance(member)
        newv = max(0, cur - amount)
        await self._set_balance(member, newv)
        await ctx.send(f"✅ Nam {COIN} {amount} af van **{member.display_name}**. Nieuw saldo: {newv}")
