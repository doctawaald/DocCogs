import discord
import datetime
import zoneinfo

from redbot.core import commands, Config
from discord.ext import tasks

# Brussels timezone
BRUSSELS_TZ = zoneinfo.ZoneInfo("Europe/Brussels")

class PaymentReminder(commands.Cog):
    """
    Plugin to send a monthly payment reminder at a configurable time (Brussels time),
    and additional reminders every 2 days if the payment isn't confirmed using the 'ipaid' command.
    Additionally, an admin (notification user) will receive notifications for all payment-related events.
    
    Data is stored persistently using Redbot's Config API.
    """
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789012345678, force_registration=True)
        default_global = {
            "reminder_users": [],
            "unpaid": [],
            "last_reminder": {},  # stored as {user_id (str): timestamp (isoformat)}
            "reminder_day": 1,
            "reminder_hour": 21,
            "reminder_minute": 0,
            "notify_user": None,
        }
        self.config.register_global(**default_global)
        
        # In-memory variabelen (laden uit de config)
        self.reminder_users = []
        self.unpaid = set()
        self.last_reminder = {}  # mapping: user_id (int) -> datetime
        self.reminder_day = 1
        self.reminder_hour = 21
        self.reminder_minute = 0
        self.notify_user = None
        # Voor de maandelijkse reminder; niet persistent
        self.last_run_date = None
        
        # Laad de data uit de config (asynchroon)
        self.bot.loop.create_task(self.load_config())
        self.reminder_loop.start()

    async def load_config(self):
        data = await self.config.all_global()
        self.reminder_users = data.get("reminder_users", [])
        self.unpaid = set(data.get("unpaid", []))
        last_reminder_data = data.get("last_reminder", {})
        self.last_reminder = {}
        for user_id_str, timestamp in last_reminder_data.items():
            try:
                dt = datetime.datetime.fromisoformat(timestamp)
                self.last_reminder[int(user_id_str)] = dt
            except Exception:
                pass
        self.reminder_day = data.get("reminder_day", 1)
        self.reminder_hour = data.get("reminder_hour", 21)
        self.reminder_minute = data.get("reminder_minute", 0)
        self.notify_user = data.get("notify_user", None)

    async def save_reminder_users(self):
        await self.config.reminder_users.set(self.reminder_users)

    async def save_unpaid(self):
        await self.config.unpaid.set(list(self.unpaid))

    async def save_last_reminder(self):
        data = {str(user_id): dt.isoformat() for user_id, dt in self.last_reminder.items()}
        await self.config.last_reminder.set(data)

    async def save_reminder_day(self):
        await self.config.reminder_day.set(self.reminder_day)

    async def save_reminder_time(self):
        await self.config.reminder_hour.set(self.reminder_hour)
        await self.config.reminder_minute.set(self.reminder_minute)

    async def save_notify_user(self):
        await self.config.notify_user.set(self.notify_user)

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = datetime.datetime.now(BRUSSELS_TZ)
        today = now.date()
        # Controleer of het de ingestelde remindertijd is (uur en minuut) en voer de maandelijkse reminder slechts 1 keer per dag uit.
        if now.hour == self.reminder_hour and now.minute == self.reminder_minute:
            if self.last_run_date == today:
                return  # Al uitgevoerd vandaag.
            self.last_run_date = today

            # Maandelijkse reminder: als vandaag de ingestelde dag is
            if today.day == self.reminder_day:
                for user_id in self.reminder_users:
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send("Reminder: Please complete your payment for this month! (use !ipaid after your payment)")
                        except Exception as e:
                            print(f"Could not send monthly reminder to {user_id}: {e}")
                    # Update de timestamp en markeer als unpaid
                    self.last_reminder[user_id] = now
                    self.unpaid.add(user_id)
                    if self.notify_user:
                        admin_user = self.bot.get_user(self.notify_user)
                        if admin_user:
                            try:
                                await admin_user.send(f"Monthly reminder sent to {user} (ID: {user.id}).")
                            except Exception as e:
                                print(f"Could not notify admin about monthly reminder for {user_id}: {e}")
                await self.save_last_reminder()
                await self.save_unpaid()
        else:
            # Extra reminder: elke 2 dagen (172800 seconden) voor gebruikers die nog niet hebben bevestigd
            for user_id in list(self.unpaid):
                last_time = self.last_reminder.get(user_id)
                if last_time is None:
                    continue
                if (now - last_time).total_seconds() >= 172800:  # 2 dagen
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send("Additional Reminder: Please complete your payment if you haven't done so already. (use !ipaid after your payment)")
                        except Exception as e:
                            print(f"Could not send additional reminder to {user_id}: {e}")
                    self.last_reminder[user_id] = now
                    if self.notify_user:
                        admin_user = self.bot.get_user(self.notify_user)
                        if admin_user:
                            try:
                                await admin_user.send(f"Additional reminder sent to {user} (ID: {user.id}).")
                            except Exception as e:
                                print(f"Could not notify admin about additional reminder for {user_id}: {e}")
                    await self.save_last_reminder()

    @commands.command()
    async def addreminder(self, ctx, user: discord.User):
        """Add a user to the reminder list."""
        if user.id not in self.reminder_users:
            self.reminder_users.append(user.id)
            await self.save_reminder_users()
            await ctx.send(f"{user.mention} has been added to the reminder list.")
        else:
            await ctx.send(f"{user.mention} is already on the reminder list.")

    @commands.command()
    async def removereminder(self, ctx, user: discord.User):
        """Remove a user from the reminder list."""
        if user.id in self.reminder_users:
            self.reminder_users.remove(user.id)
            self.unpaid.discard(user.id)
            if user.id in self.last_reminder:
                del self.last_reminder[user.id]
            await self.save_reminder_users()
            await self.save_unpaid()
            await self.save_last_reminder()
            await ctx.send(f"{user.mention} has been removed from the reminder list.")
        else:
            await ctx.send(f"{user.mention} is not on the reminder list.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreminderdate(self, ctx, day: int):
        """
        Set the day of the month on which the monthly reminder is sent.
        Provide a number between 1 and 31.
        """
        if day < 1 or day > 31:
            await ctx.send("Please provide a valid day (between 1 and 31).")
            return
        self.reminder_day = day
        await self.save_reminder_day()
        await ctx.send(f"The reminder day is now set to day {day} of the month.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setremindertime(self, ctx, hour: int, minute: int):
        """
        Set the time (hour and minute, Brussels time) when reminders are sent.
        Example: `setremindertime 19 58` sets the reminder time to 19:58 Brussels time.
        """
        if hour < 0 or hour > 23:
            await ctx.send("Please provide a valid hour (between 0 and 23).")
            return
        if minute < 0 or minute > 59:
            await ctx.send("Please provide a valid minute (between 0 and 59).")
            return
        self.reminder_hour = hour
        self.reminder_minute = minute
        await self.save_reminder_time()
        await ctx.send(f"Reminder time is now set to {hour:02d}:{minute:02d} Brussels time.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setnotifyuser(self, ctx, user: discord.User):
        """
        Set the Discord user that will receive notifications about payment reminders and confirmations.
        """
        self.notify_user = user.id
        await self.save_notify_user()
        await ctx.send(f"Notification user has been set to {user.mention}.")

    @commands.command()
    async def ipaid(self, ctx):
        """
        Confirm that you have made your payment, stopping further reminders.
        """
        user_id = ctx.author.id
        if user_id in self.unpaid:
            self.unpaid.remove(user_id)
            await self.save_unpaid()
            await ctx.send("Thank you for confirming your payment!")
            if self.notify_user:
                admin_user = self.bot.get_user(self.notify_user)
                if admin_user:
                    try:
                        await admin_user.send(f"Payment confirmation received from {ctx.author} (ID: {ctx.author.id}).")
                    except Exception as e:
                        print(f"Could not notify admin about payment confirmation from {user_id}: {e}")
        else:
            await ctx.send("You have already confirmed your payment or are not on the reminder list.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetipaid(self, ctx, user: discord.User = None):
        """
        Reset the payment confirmation for a user, re-adding them to the unpaid list.
        If no user is provided, resets for the invoker.
        This command is intended for testing purposes.
        """
        if user is None:
            user = ctx.author
        if user.id not in self.reminder_users:
            await ctx.send("That user is not on the reminder list.")
            return
        self.unpaid.add(user.id)
        self.last_reminder[user.id] = datetime.datetime.now(BRUSSELS_TZ)
        await self.save_unpaid()
        await self.save_last_reminder()
        await ctx.send(f"{user.mention}'s payment status has been reset. They will receive reminders again.")
        if self.notify_user:
            admin_user = self.bot.get_user(self.notify_user)
            if admin_user:
                try:
                    await admin_user.send(f"Payment status reset for {user} (ID: {user.id}).")
                except Exception as e:
                    print(f"Could not notify admin about reset for {user.id}: {e}")

async def setup(bot):
    await bot.add_cog(PaymentReminder(bot))
