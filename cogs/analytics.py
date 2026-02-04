import discord
from discord.ext import commands
from discord import app_commands
import os
from datetime import datetime, timedelta, timezone

from utils.database import Database
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class AnalyticsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    analytics_group = app_commands.Group(name="analytics", description="Analytics commands", default_permissions=discord.Permissions(administrator=True))

    def _get_date_range_start(self, date_range: str) -> datetime:
        now = datetime.now(timezone.utc)
        if date_range == "1_week":
            return now - timedelta(weeks=1)
        elif date_range == "1_month":
            return now - timedelta(days=30) # Approximate month
        elif date_range == "1_year":
            return now - timedelta(days=365) # Approximate year
        elif date_range == "all_time":
            return datetime.min.replace(tzinfo=timezone.utc) # Start of time
        return datetime.min.replace(tzinfo=timezone.utc) # Default to all time

    def log_event(self, event_type: str, item_id: int = None, user_id: int = None):
        self.db.execute_query(
            "INSERT INTO analytics (event_type, item_id, user_id, timestamp) VALUES (%s, %s, %s, %s)",
            (event_type, item_id, user_id, datetime.now(timezone.utc))
        )

    @analytics_group.command(name="item")
    async def item_analytics(self, interaction: discord.Interaction, item_id: int):
        item = self.db.execute_query("SELECT name FROM items WHERE id = %s", (item_id,), fetch='one')
        if not item:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return

        purchases = self.db.execute_query(
            "SELECT COUNT(*) as count FROM analytics WHERE event_type = 'purchase' AND item_id = %s",
            (item_id,),
            fetch='one'
        )
        total_purchases = purchases['count'] if purchases else 0

        embed = EmbedBuilder(
            title=f"Analytics for {item['name']}",
            description=f"Total Purchases: {total_purchases}"
        ).build()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @analytics_group.command(name="popular")
    @app_commands.describe(date_range="Filter by date range")
    @app_commands.choices(date_range=[
        app_commands.Choice(name="Last 7 Days", value="1_week"),
        app_commands.Choice(name="Last 30 Days", value="1_month"),
        app_commands.Choice(name="Last Year", value="1_year"),
        app_commands.Choice(name="All Time (YTD)", value="all_time")
    ])
    async def popular_items(self, interaction: discord.Interaction, date_range: app_commands.Choice[str] = "all_time"):
        start_date = self._get_date_range_start(date_range.value)
        
        popular_items = self.db.execute_query(
            """
            SELECT i.name, COUNT(a.item_id) as purchase_count
            FROM analytics a
            JOIN items i ON a.item_id = i.id
            WHERE a.event_type = 'purchase' AND a.timestamp >= %s
            GROUP BY a.item_id
            ORDER BY purchase_count DESC
            LIMIT 10
            """,
            (start_date,),
            fetch='all'
        )

        embed = EmbedBuilder(title=f"Most Popular Items ({date_range.name})")
        if popular_items:
            for item in popular_items:
                embed.add_field(name=item['name'], value=f"Purchases: {item['purchase_count']}", inline=False)
        else:
            embed.description = "No purchase data available for this period."

        await interaction.response.send_message(embed=embed.build(), ephemeral=True)

    @analytics_group.command(name="summary")
    @app_commands.describe(date_range="Filter by date range")
    @app_commands.choices(date_range=[
        app_commands.Choice(name="Last 7 Days", value="1_week"),
        app_commands.Choice(name="Last 30 Days", value="1_month"),
        app_commands.Choice(name="Last Year", value="1_year"),
        app_commands.Choice(name="All Time (YTD)", value="all_time")
    ])
    async def summary(self, interaction: discord.Interaction, date_range: app_commands.Choice[str] = "all_time"):
        start_date = self._get_date_range_start(date_range.value)

        total_purchases = self.db.execute_query(
            "SELECT COUNT(*) as count FROM analytics WHERE event_type = 'purchase' AND timestamp >= %s",
            (start_date,),
            fetch='one'
        )['count']

        total_revenue = self.db.execute_query(
            """
            SELECT SUM(i.price) as total
            FROM analytics a
            JOIN items i ON a.item_id = i.id
            WHERE a.event_type = 'purchase' AND a.timestamp >= %s
            """,
            (start_date,),
            fetch='one'
        )['total'] or 0

        embed = EmbedBuilder(
            title=f"Shop Analytics Summary ({date_range.name})"
        ).add_field(name="Total Purchases", value=total_purchases)\
         .add_field(name="Total Revenue", value=f"${total_revenue:.2f}")

        await interaction.response.send_message(embed=embed.build(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(AnalyticsCog(bot))
