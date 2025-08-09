import discord
from redbot.core import commands

class EconomyMixin:
    @commands.command()
    async def booz(self, ctx: commands.Context):
        """Bekijk je saldo (Boo'z)."""
        bal = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.mention}, je hebt **{bal} Boo'z**.")

    @commands.command()
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Geef Boo'z aan iemand."""
        if member.bot or amount <= 0:
            return await ctx.send("❌ Ongeldige input.")
        your = await self.config.user(ctx.author).booz()
        if your < amount:
            return await ctx.send("❌ Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(your - amount)
        other = await self.config.user(member).booz()
        await self.config.user(member).booz.set(other + amount)
        await ctx.send(f"💸 {ctx.author.mention} gaf **{amount} Boo'z** aan {member.mention}.")

    @commands.command()
    async def shop(self, ctx: commands.Context):
        """Bekijk de BoozyShop™."""
        shop = await self.config.guild(ctx.guild).shop()
        lines = [f"`{k}` — {v['price']} Boo'z" for k, v in shop.items()]
        await ctx.send("🏪 **BoozyShop™**\n" + ("\n".join(lines) if lines else "_Leeg_"))

    @commands.command()
    async def redeem(self, ctx: commands.Context, item: str):
        """Koop een item uit de shop: !redeem soundboard_access"""
        shop = await self.config.guild(ctx.guild).shop()
        key = item.lower().strip()
        if key not in shop:
            return await ctx.send("❌ Dat item bestaat niet.")
        price = int(shop[key]["price"])
        bal = await self.config.user(ctx.author).booz()
        if bal < price:
            return await ctx.send("❌ Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(bal - price)
        role_id = shop[key].get("role_id")
        if role_id:
            role = ctx.guild.get_role(int(role_id))
            if role:
                await ctx.author.add_roles(role, reason="BoozyShop aankoop")
                return await ctx.send(f"✅ Gekocht: **{key}** — rol **{role.name}** toegevoegd.")
        await ctx.send(f"✅ Gekocht: **{key}** voor {price} Boo'z.")

    @commands.command()
    async def boozyleader(self, ctx: commands.Context):
        """Top 10 Boo'z bezitters in deze server."""
        allu = await self.config.all_users()
        top = sorted(allu.items(), key=lambda kv: kv[1]["booz"], reverse=True)[:10]
        lines = []
        for i, (uid, data) in enumerate(top, 1):
            m = ctx.guild.get_member(int(uid))
            if m:
                lines.append(f"{i}. **{m.display_name}** — {data['booz']} Boo'z")
        await ctx.send("🥇 **Boozy Top 10**\n" + ("\n".join(lines) if lines else "_Nog geen data_"))
