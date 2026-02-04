import discord
from discord.ext import commands, tasks
import os
import random
from datetime import datetime, timedelta, timezone

from utils.database import Database
from ui.views import GiveawayView
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.giveaway_manager.start()

    async def end_giveaway(self, giveaway: dict):
        log.info(f"Ending giveaway {giveaway['id']}.")
        giveaway_channel_id = int(os.getenv("GIVEAWAY_CHANNEL_ID"))
        channel = self.bot.get_channel(giveaway_channel_id)
        
        if not channel:
            log.error(f"Giveaway channel with ID {giveaway_channel_id} not found for ending giveaway {giveaway['id']}.")
            self.db.execute_query("UPDATE giveaways SET status = 'ended' WHERE id = %s", (giveaway['id'],))
            return

        entrants = [row['user_id'] for row in self.db.execute_query("SELECT user_id FROM giveaway_entrants WHERE giveaway_id = %s", (giveaway['id'],), fetch='all')]
        
        winner_id = random.choice(entrants) if entrants else None
        
        if winner_id:
            prize = float(os.getenv("GIVEAWAY_CREDIT_PRIZE"))
            self.db.execute_query("INSERT INTO users (id, balance) VALUES (%s, %s) ON DUPLICATE KEY UPDATE balance = balance + %s", (winner_id, prize, prize))
            winner = await self.bot.fetch_user(winner_id)
            
            winner_embed = EmbedBuilder(
                title="Giveaway Winner!",
                description=f"Congratulations {winner.mention}! You won **${prize:.2f}** in store credit!",
                color=discord.Color.green()
            ).build()
            await channel.send(embed=winner_embed)
            log.info(f"Giveaway {giveaway['id']} winner: {winner.id} won ${prize:.2f}.")
            
            try:
                msg = await channel.fetch_message(giveaway['message_id'])
                embed = EmbedBuilder(
                    title="Giveaway Ended",
                    description=f"Winner: {winner.mention}",
                    color=discord.Color.red()
                ).build()
                await msg.edit(embed=embed, view=None)
                log.info(f"Updated giveaway message {giveaway['message_id']} for winner announcement.")
            except discord.NotFound:
                log.warning(f"Giveaway message {giveaway['message_id']} not found for updating winner.")
        else:
            no_entrants_embed = EmbedBuilder(
                title="Giveaway Ended",
                description="The giveaway has ended, but there were no entrants.",
                color=discord.Color.red()
            ).build()
            await channel.send(embed=no_entrants_embed)
            log.info(f"Giveaway {giveaway['id']} ended with no entrants.")

        self.db.execute_query("DELETE FROM giveaway_entrants WHERE giveaway_id = %s", (giveaway['id'],))
        self.db.execute_query("UPDATE giveaways SET status = 'ended' WHERE id = %s", (giveaway['id'],))

    async def start_new_giveaway(self):
        log.info("Starting a new giveaway.")
        giveaway_channel_id = int(os.getenv("GIVEAWAY_CHANNEL_ID"))
        giveaway_role_id = int(os.getenv("GIVEAWAY_ROLE_ID"))
        prize = float(os.getenv("GIVEAWAY_CREDIT_PRIZE"))
        
        channel = self.bot.get_channel(giveaway_channel_id)
        if not channel:
            log.critical(f"Giveaway channel with ID {giveaway_channel_id} not found. Cannot start new giveaway.")
            return
        
        role = channel.guild.get_role(giveaway_role_id)
        role_mention = role.mention if role else "Everyone"
        
        end_time = datetime.now(timezone.utc) + timedelta(hours=24)
        embed = EmbedBuilder(
            title="Daily Credit Giveaway!",
            description=f"Click the button to enter for a chance to win **${prize:.2f}** in store credit!\nEnds <t:{int(end_time.timestamp())}:R>",
            color=discord.Color.gold()
        ).build()
        
        msg = await channel.send(content=role_mention, embed=embed, view=GiveawayView())
        self.db.execute_query("INSERT INTO giveaways (message_id, end_time, status) VALUES (%s, %s, 'active')", (msg.id, end_time))
        log.info(f"New giveaway started (ID: {self.db.execute_query('SELECT id FROM giveaways ORDER BY id DESC LIMIT 1', fetch='one')['id']}) in channel {channel.id}.")

    @tasks.loop(minutes=1)
    async def giveaway_manager(self):
        log.debug("Running giveaway manager task.")
        
        # Check for active giveaways that have ended
        active_giveaway = self.db.execute_query("SELECT * FROM giveaways WHERE status = 'active' ORDER BY id DESC LIMIT 1", fetch='one')
        
        if active_giveaway:
            now = datetime.now(timezone.utc)
            if now > active_giveaway['end_time'].replace(tzinfo=timezone.utc):
                await self.end_giveaway(active_giveaway)
                await self.start_new_giveaway() # Start a new one immediately after ending the old one
            else:
                # Optional: Update existing giveaway embed if needed (e.g., time remaining)
                # This part is kept minimal to avoid unnecessary API calls
                pass
        else:
            # No active giveaway found, so start a new one
            await self.start_new_giveaway()

    @giveaway_manager.before_loop
    async def before_giveaway_manager(self):
        log.info("Waiting for bot to be ready before starting giveaway manager.")
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))
