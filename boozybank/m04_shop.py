# M04 --- SHOP --------------------------------------------------------------
from __future__ import annotations
import discord
from redbot.core import commands, checks

COIN = "🪙"


class ShopMixin:
    # M04#1 HELPERS
    async def _shop_get(self, guild: discord.Guild):
        return await self.config.guild(guild).shop()

    async def _shop_set(self, guild: discord.Guild, data: dict):
        await self.config.guild(guild).shop.set(data)

    # M04#2 COMMANDS
    @commands.command()
    async def shop(self, ctx: commands.Context):
        """Toon alle shop items."""
        shop = await self._shop_get(ctx.guild)
        if not shop:
            return await ctx.send("🛍️ De shop is leeg.")
        lines = ["🛍️ **Boozy Shop**"]
        for key, item in shop.items():
            price = item.get("price", 0)
            label = item.get("label") or key
            role_id = item.get("role_id")
            role_txt = ""
            if role_id:
                r = ctx.guild.get_role(role_id)
                role_txt = f" → rol: @{r.name}" if r else " → rol: (verwijderd?)"
            lines.append(f"• **{label}** (`{key}`) — {COIN} {price}{role_txt}")
        await ctx.send("\n".join(lines))

    @commands.command()
    async def buy(self, ctx: commands.Context, key: str):
        """Koop een shop item per sleutel."""
        g = await self.config.guild(ctx.guild).all()
        if g.get("global_testmode", False):
            return await ctx.send("🧪 Testmodus: kopen is uitgeschakeld.")
        key = key.strip()
        shop = await self._shop_get(ctx.guild)
        if key not in shop:
            return await ctx.send("❌ Onbekend item.")
        item = shop[key]
        price = int(item.get("price", 0))
        role_id = item.get("role_id")
        label = item.get("label") or key

        bal = await self.config.user(ctx.author).booz()
        if bal < price:
            return await ctx.send(f"💸 Onvoldoende Boo'z. Nodig: {price}, jij hebt {bal}.")
        # aftrekken + toekennen
        await self.config.user(ctx.author).booz.set(int(bal) - price)
        if role_id:
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await ctx.author.add_roles(role, reason="Shop aankoop")
                except Exception:
                    pass
        await ctx.send(f"✅ Gekocht: **{label}** voor {COIN} {price}.")

    # M04#3 ADMIN
    @commands.command()
    @checks.admin()
    async def addshopitem(self, ctx: commands.Context, key: str, price: int, role: discord.Role | None = None, *, label: str | None = None):
        """Voeg item toe: key price [@role] [label...]"""
        key = key.strip()
        price = max(0, int(price))
        shop = await self._shop_get(ctx.guild)
        shop[key] = {"price": price, "role_id": role.id if role else None, "label": (label or key)}
        await self._shop_set(ctx.guild, shop)
        await ctx.send(f"🛍️ Item **{key}** toegevoegd: {COIN} {price}{' + rol ' + role.name if role else ''}.")

    @commands.command()
    @checks.admin()
    async def delshopitem(self, ctx: commands.Context, key: str):
        """Verwijder item per sleutel."""
        shop = await self._shop_get(ctx.guild)
        if key in shop:
            shop.pop(key)
            await self._shop_set(ctx.guild, shop)
            await ctx.send(f"🗑️ Item **{key}** verwijderd.")
        else:
            await ctx.send("❌ Onbekend item.")
