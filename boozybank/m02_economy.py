# [02] ECONOMY — saldo, leaderboard, give, shop en redeem (rol-koppeling voor extern soundboard)

import discord
from redbot.core import commands, checks

class EconomyMixin:
    # ------- Helpers -------
    async def _get_balance(self, member: discord.abc.User) -> int:
        return int(await self.config.user(member).booz())

    async def _set_balance(self, member: discord.abc.User, amount: int) -> None:
        await self.config.user(member).booz.set(int(max(0, amount)))

    async def _get_shop(self, guild: discord.Guild) -> dict:
        return await self.config.guild(guild).shop()

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

    # ------- Shop & redeem -------
    @commands.command()
    async def shop(self, ctx: commands.Context):
        """Bekijk de BoozyShop™ items en (optionele) rol-koppeling."""
        shop = await self._get_shop(ctx.guild)
        if not shop:
            return await ctx.send("🏪 **BoozyShop™**\n_Leeg_")
        lines = []
        for k, v in shop.items():
            price = int(v.get("price", 0))
            role_id = v.get("role_id")
            role_txt = f" → rol: <@&{role_id}>" if role_id else ""
            lines.append(f"`{k}` — {price} Boo'z{role_txt}")
        await ctx.send("🏪 **BoozyShop™**\n" + "\n".join(lines))

    @commands.command()
    async def redeem(self, ctx: commands.Context, item: str):
        """
        Koop een item uit de shop: !redeem soundboard_access
        - Rekent Boo'z af.
        - Koppelt rol automatisch als het item een rol heeft (voor externe soundboard-bots).
        - Blokkeert dubbelaankoop als je de rol al hebt.
        """
        key = item.lower().strip()
        shop = await self._get_shop(ctx.guild)
        if key not in shop:
            return await ctx.send("❌ Dat item bestaat niet.")

        price = int(shop[key].get("price", 0))
        role_id = shop[key].get("role_id")
        role = ctx.guild.get_role(int(role_id)) if role_id else None

        # Dubbelkoop-guard: als er een rol is gekoppeld en je hebt die al, weiger aankoop
        if role and role in ctx.author.roles:
            return await ctx.send(f"ℹ️ Je hebt **{role.name}** al; aankoop niet nodig.")

        bal = await self._get_balance(ctx.author)
        if bal < price:
            return await ctx.send(f"❌ Je hebt {price} Boo'z nodig.")

        # Rekenen
        await self._set_balance(ctx.author, bal - price)

        # Rol toekennen (optioneel)
        if role:
            try:
                await ctx.author.add_roles(role, reason=f"BoozyShop aankoop: {key}")
                return await ctx.send(f"✅ Gekocht: **{key}** — rol **{role.name}** toegevoegd.")
            except Exception:
                # Rol mislukt → refund
                cur = await self._get_balance(ctx.author)
                await self._set_balance(ctx.author, cur + price)
                return await ctx.send("⚠️ Kon de rol niet toekennen (rechten?). Aankoop geannuleerd en Boo'z teruggestort.")

        # Geen rol gekoppeld → gewoon afronden
        await ctx.send(f"✅ Gekocht: **{key}** voor {price} Boo'z.")

    # ------- Soundboard check (handig voor externe bot) -------
    @commands.command()
    async def canusesoundboard(self, ctx: commands.Context, member: discord.Member | None = None):
        """Check of jij (of @user) de vereiste soundboard-rol hebt."""
        member = member or ctx.author
        shop = await self._get_shop(ctx.guild)
        item = shop.get("soundboard_access")
        if not item or not item.get("role_id"):
            return await ctx.send("ℹ️ Er is geen rol gekoppeld aan `soundboard_access` in de shop.")
        role = ctx.guild.get_role(int(item["role_id"]))
        if not role:
            return await ctx.send("⚠️ De gekoppelde rol bestaat niet meer.")
        if role in member.roles:
            return await ctx.send(f"✅ **{member.display_name}** heeft **{role.name}** en kan het soundboard gebruiken (als de externe bot daarop checkt).")
        return await ctx.send(f"❌ **{member.display_name}** mist de rol **{role.name}**.")

    # ------- Admin: refund / herstel -------
    @commands.command()
    @checks.admin()
    async def refundpurchase(self, ctx: commands.Context, member: discord.Member, item: str):
        """
        Admin: maak aankoop ongedaan en stort Boo'z terug.
        - Verwijdert de rol als er een rol aan het item is gekoppeld.
        """
        key = item.lower().strip()
        shop = await self._get_shop(ctx.guild)
        if key not in shop:
            return await ctx.send("❌ Dat item bestaat niet.")
        price = int(shop[key].get("price", 0))
        role_id = shop[key].get("role_id")
        role = ctx.guild.get_role(int(role_id)) if role_id else None

        # Rol wegnemen als die er is
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"BoozyShop refund: {key}")
            except Exception:
                return await ctx.send("⚠️ Kon de rol niet verwijderen (rechten?). Refund afgebroken.")

        # Geld terugstorten
        bal = await self._get_balance(member)
        await self._set_balance(member, bal + price)
        await ctx.send(f"↩️ Refund: **{member.display_name}** kreeg **{price} Boo'z** terug voor **{key}**.")
