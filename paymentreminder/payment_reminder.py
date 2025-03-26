import discord
from discord.ext import commands, tasks
import datetime

class PaymentReminder(commands.Cog):
    """Plugin to send a monthly payment reminder with a configurable date."""

    def __init__(self, bot):
        self.bot = bot
        # List of user IDs to receive the reminder
        self.reminder_users = []
        # Default day is the 1st of the month
        self.reminder_day = 1
        # Start the background task
        self.reminder_loop.start()

    def cog_unload(self):
        # Stop the background task when the cog is unloaded
        self.reminder_loop.cancel()

    @tasks.loop(hours=24)
    async def reminder_loop(self):
        """Check daily if it is the configured day and send reminders."""
        now = datetime.datetime.utcnow()  # Adjust to local time if needed
        if now.day == self.reminder_day:
            for user_id in self.reminder_users:
                user = self.bot.get_user(user_id)
                if user:
                    try:
                        await user.send("Reminder: Don't forget to complete your payment this month!")
                    except Exception as e:
                        print(f"Could not send reminder to {user_id}: {e}")

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
            await ctx.send(f"{user.mention} has been removed from the reminder list.")
        else:
            await ctx.send(f"{user.mention} is not on the reminder list.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreminderdate(self, ctx, day: int):
        """
        Set the day of the month on which the reminder is sent.
        Provide a number between 1 and 31.
        """
        if day < 1 or day > 31:
            await ctx.send("Please provide a valid day (between 1 and 31).")
            return
        self.reminder_day = day
        await ctx.send(f"The reminder day is now set to day {day} of the month.")

def setup(bot):
    bot.add_cog(PaymentReminder(bot))
