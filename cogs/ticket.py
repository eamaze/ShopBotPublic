import discord
from discord.ext import commands, tasks
from discord import app_commands
import os

from utils.database import Database
from ui.views import TicketCreationView
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.purge_closed_tickets.start()

    ticket_group = app_commands.Group(name="ticket", description="Ticket commands", default_permissions=discord.Permissions(administrator=True))

    @ticket_group.command(name="setup")
    async def setup_ticket(self, interaction: discord.Interaction):
        """
        Posts the ticket creation message.
        """
        channel_id = int(os.getenv("TICKETS_CHANNEL_ID"))
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message(f"Error: Ticket channel with ID {channel_id} not found.", ephemeral=True)
            log.error(f"Ticket channel with ID {channel_id} not found in guild {interaction.guild.id}.")
            return

        embed = EmbedBuilder(
            title="Support Tickets",
            description="Click the button below to open a support ticket.",
            color=discord.Color.blue()
        ).build()
        await channel.send(embed=embed, view=TicketCreationView())
        await interaction.response.send_message("Ticket system set up.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} set up ticket system in channel {channel.id}.")

    @tasks.loop(hours=168)
    async def purge_closed_tickets(self):
        log.info("Purging closed tickets.")
        closed_tickets = self.db.execute_query("SELECT * FROM tickets WHERE status = 'closed'", fetch='all')
        
        for ticket in closed_tickets:
            channel = self.bot.get_channel(ticket['channel_id'])
            if channel:
                await channel.delete()
                log.info(f"Deleted channel {ticket['channel_id']} for purged ticket {ticket['id']}.")
            else:
                log.warning(f"Channel {ticket['channel_id']} not found for closed ticket {ticket['id']} during purge.")
        
        self.db.execute_query("DELETE FROM tickets WHERE status = 'closed'")
        log.info(f"Purged {len(closed_tickets)} closed tickets from database.")

    @purge_closed_tickets.before_loop
    async def before_purge_closed_tickets(self):
        log.info("Starting closed ticket purge loop.")
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TicketCog(bot))
