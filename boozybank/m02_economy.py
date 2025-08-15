# ============================
# m02_economy.py
# ============================
from __future__ import annotations
from typing import List, Tuple
import discord
from redbot.core import commands, checks
from .m01_utils import COIN

class EconomyMixin:
    # M02#1 helpers
    async def eco_get(self, member: discord.Member) -> int:
        return int(await self.config.user(member).booz())

    async def eco_set(self, member: discord.Member, value: int) -> int:
        v = max(0, int(value))
        await self.config.user(member).booz.set(v)
        return v

    async def eco_add(self, member: discord.Member, delta: int) -> int:
        cur = await self.eco_get(member)
        return await self.eco_set(member, cur + int(delta))

    # M02#2 public API (voor interne modules)
    async def add_booz(self, guild: discord.Guild, member: discord.Member, amount: int, *, reason: str = "") -> int:
        if member.bot:
            return await self.eco_get(member)
        g = await self.config.guild(guild).all()
        if g.get("global_testmode", False):
            try:
                await member.send(f"🧪 Testmodus: geen Boo'z voor: {reason or 'actie'}")
            except Exception:
                pass
            return await self.eco_get(member)
        return await self.eco_add(member, amount)

    # M02#3 commands
    @commands.command(aliases=["bal","balance","boozybal"])
    async def booz(self, ctx: commands.Context, member: discord.Member | None = None):
        tgt = member or ctx.author
        if tgt.bot:
            return await ctx.send("🤖 Bots hebben geen Boo'z.")
        bal = await self.eco_get(tgt)
        who = "jouw" if tgt == ctx.author else tgt.display_name
        await ctx.send(f"{COIN} **Boo'z** — {who}: **{bal}**")

    @commands.command(aliases=["leaderboard","boozytop"])
    async def top(self, ctx: commands.Context, limit: int = 10):
        limit = max(1, min(25, int(limit)))
        rows: List[Tuple[int, discord.Member]] = []
        for m in ctx.guild.members:
            if m.bot:
                continue
            bal = await self.eco_get(m)
            rows.append((bal, m))
        rows.sort(key=lambda x: x[0], reverse=True)
        lines = [f"🏆 **Leaderboard (top {limit})**"]
        for i, (bal, m) in enumerate(rows[:limit], 1):
            lines.append(f"{i}. {m.display_name} — {COIN} {bal}")
        await ctx.send("\n".join(lines) if len(lines) > 1 else "📉 Nog geen data.")

    @commands.command()
    @checks.admin()
    async def boozygive(self, ctx: commands.Context, member: discord.Member, amount: int):
        if member.bot:
            return await ctx.send("🤖 Bots hebben geen Boo'z.")
        newv = await self.eco_add(member, max(0, int(amount)))
        await ctx.send(f"✅ Gaf **{member.display_name}** {COIN} {int(amount)} → saldo {newv}")

    @commands.command()
    @checks.admin()
    async def boozytake(self, ctx: commands.Context, member: discord.Member, amount: int):
        if member.bot:
            return await ctx.send("🤖 Bots hebben geen Boo'z.")
        cur = await self.eco_get(member)
        newv = await self.eco_set(member, max(0, cur - int(amount)))
        await ctx.send(f"✅ Nam {COIN} {int(amount)} af van **{member.display_name}** → saldo {newv}")
