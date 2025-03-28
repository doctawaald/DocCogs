import discord
import datetime
import zoneinfo

from redbot.core import commands
from discord.ext import tasks

# Brussels timezone
BRUSSELS_TZ = zoneinfo.ZoneInfo("Europe/Brussels")

class PaymentReminder(commands.Cog):
    """
    Plugin to send a monthly payment reminder at a configurable time (Brussels time),
    and additional reminders every 1 minute if the payment isn't confirmed using the 'ipaid' command.
    Additionally, an admin (notification user) will receive notifications for all payment-related events.
    """

    def __init__(self, bot):
        self.bot = bot
        # List of user IDs to receive the reminder
        self.reminder_users = []
        # Default monthly reminder day
        self.reminder_day = 1
        # Default reminder time is set to 21:00
        self.reminder_hour = 21
        self.reminder_minute = 0
        # Record the timestamp when the last reminder was sent per user (as datetime objects)
        self.last_reminder = {}
        # Set of user IDs who haven't confirmed payment yet
        self.unpaid = set()
        # Admin (notification) user ID to receive extra messages
        self.notify_user = None
        # To ensure the monthly reminder logic runs only once per day
        self.last_run_date = None
        # Start the background task (runs every minute)
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = datetime.datetime.now(BRUSSELS_TZ)
        today = now.date()
        # Check if current time matches the configured reminder time (hour and minute) and ensure monthly reminder runs only once per day
        if now.hour == self.reminder_hour and now.minute == self.reminder_minute:
            if self.last_run_date == today:
                return  # Already executed today.
            self.last_run_date = today

            # Monthly reminder: if today is the configured day
            if today.day == self.reminder_day:
                for user_id in self.reminder_users:
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send("Reminder: Please complete your payment for this month!")
                        except Exception as e:
                            print(f"Could not send monthly reminder to {user_id}: {e}")
                    # Record the current timestamp and mark user as unpaid
                    self.last_reminder[user_id] = now
                    self.unpaid.add(user_id)
                    # Notify admin if set
                    if self.notify_user:
                        admin_user = self.bot.get_user(self.notify_user)
                        if admin_user:
                            try:
                                await admin_user.send(f"Monthly reminder sent to user with ID: {user_id}.")
                            except Exception as e:
                                print(f"Could not notify admin about monthly reminder for {user_id}: {e}")
        else:
            # Additional reminder: every 1 minute for users who haven't confirmed payment
            for user_id in list(self.unpaid):
                last_time = self.last_reminder.get(user_id)
                if last_time is None:
                    continue
                if (now - last_time).total_seconds() >= 60:  # 1 minute
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send("Additional Reminder: Please complete your payment if you haven't done so already.")
                        except Exception as e:
                            print(f"Could not send additional reminder to {user_id}: {e}")
                    self.last_reminder[user_id] = now
                    if self.notify_user:
                        admin_user = self.bot.get_user(self.notify_user)
                        if admin_user:
                            try:
                                await admin_user.send(f"Additional reminder sent to user with ID: {user_id}.")
                            except Exception as e:
                                print(f"Could not notify admin about additional reminder for {user_id}: {e}")

    @commands.command()
    async def addreminder(self, ctx, user: discord.User):
        """Add a user to the reminder list."""
        if user.id not in self.reminder_users:
            self.reminder_users.append(user.id)
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
        await ctx.send(f"Reminder time is now set to {hour:02d}:{minute:02d} Brussels time.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setnotifyuser(self, ctx, user: discord.User):
        """
        Set the Discord user that will receive notifications about payment reminders and confirmations.
        """
        self.notify_user = user.id
        await ctx.send(f"Notification user has been set to {user.mention}.")

    @commands.command()
    async def ipaid(self, ctx):
        """
        Confirm that you have made your payment, stopping further reminders.
        """
        user_id = ctx.author.id
        if user_id in self.unpaid:
            self.unpaid.remove(user_id)
            await ctx.send("Thank you for confirming your payment!")
            # Notify admin about payment confirmation
            if self.notify_user:
                admin_user = self.bot.get_user(self.notify_user)
                if admin_user:
                    try:
                        await admin_user.send(f"Payment confirmation received from {ctx.author} (ID: {user_id}).")
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
