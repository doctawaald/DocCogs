# ============================
# m04_shop.py
# ============================
from __future__ import annotations
import discord
from redbot.core import commands, checks
from .m01_utils import COIN

class ShopMixin:
    async def _shop_get(self, guild: discord.Guild) -> dict:
        return await self.config.guild(guild).shop() if hasattr(self.config.guild(guild), 'shop') else {}

    async def _shop_set(self, guild: discord.Guild, data: dict):
        # ensure key exists
        if not hasattr(self.config.guild(guild), 'shop'):
            await self.config.guild(guild).set_raw("shop", value={})
        await self.config.guild(guild).shop.set(data)

    @commands.command()
    async def shop(self, ctx: commands.Context):
        shop = await self._shop_get(ctx.guild)
        if not shop:
            return await ctx.send("🛍️ De shop is leeg.")
        lines = ["🛍️ **Boozy Shop**"]
        for key, item in shop.items():
            price = int(item.get("price", 0))
            label = item.get("label") or key
            rid = item.get("role_id")
            rtxt = ""
            if rid:
                r = ctx.guild.get_role(rid)
                rtxt = f" → rol: @{r.name}" if r else " → rol: (verwijderd?)"
            lines.append(f"• **{label}** (`{key}`) — {COIN} {price}{rtxt}")
        await ctx.send("\n".join(lines))

    @commands.command()
    async def buy(self, ctx: commands.Context, key: str):
        g = await self.config.guild(ctx.guild).all()
        if g.get("global_testmode", False):
            return await ctx.send("🧪 Testmodus: kopen uitgeschakeld.")
        shop = await self._shop_get(ctx.guild)
        if key not in shop:
            return await ctx.send("❌ Onbekend item.")
        item = shop[key]
        price = int(item.get("price", 0))
        bal = await self.config.user(ctx.author).booz()
        if bal < price:
            return await ctx.send(f"💸 Onvoldoende Boo'z. Nodig: {price}, jij hebt {bal}.")
        await self.config.user(ctx.author).booz.set(int(bal) - price)
        rid = item.get("role_id")
        if rid:
            role = ctx.guild.get_role(rid)
            if role:
                try:
                    await ctx.author.add_roles(role, reason="Boozy shop aankoop")
                except Exception:
                    pass
        await ctx.send(f"✅ Gekocht: **{item.get('label') or key}** voor {COIN} {price}.")

    @commands.command()
    @checks.admin()
    async def addshopitem(self, ctx: commands.Context, key: str, price: int, role: discord.Role | None = None, *, label: str | None = None):
        shop = await self._shop_get(ctx.guild)
        shop[key] = {"price": max(0,int(price)), "role_id": role.id if role else None, "label": label or key}
        await self._shop_set(ctx.guild, shop)
        await ctx.send(f"🛍️ Item **{key}** toegevoegd: {COIN} {int(price)}{' + rol ' + role.name if role else ''}.")

    @commands.command()
    @checks.admin()
    async def delshopitem(self, ctx: commands.Context, key: str):
        shop = await self._shop_get(ctx.guild)
        if key in shop:
            shop.pop(key)
            await self._shop_set(ctx.guild, shop)
            await ctx.send(f"🗑️ Item **{key}** verwijderd.")
        else:
            await ctx.send("❌ Onbekend item.")
