import discord
from discord.ext import commands
from discord import app_commands
import os

from utils.database import Database
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class DeliveryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    delivery_group = app_commands.Group(name="delivery", description="Delivery commands", default_permissions=discord.Permissions(administrator=True))

    @delivery_group.command(name="user_stats")
    async def user_stats(self, interaction: discord.Interaction, user: discord.Member):
        """
        Checks the total amount of money a user has delivered in goods.
        """
        user_data = self.db.execute_query("SELECT delivery_value_handled FROM users WHERE id = %s", (user.id,), fetch='one')
        delivery_value_handled = user_data['delivery_value_handled'] if user_data and user_data['delivery_value_handled'] is not None else 0.0

        embed = EmbedBuilder(
            title=f"Delivery Stats for {user.display_name}",
            description=f"Total value of goods delivered: **${delivery_value_handled:.2f}**"
        ).build()
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info(f"Delivery person {interaction.user.id} checked user {user.id}'s delivery stats.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """
        Handles when a member joins the guild.
        """
        log.info(f"Member {member.id} ({member.name}) joined the guild. Checking for roles.")
        await self.check_and_apply_roles(member.guild, member.id)

    async def check_and_apply_roles(self, guild: discord.Guild, user_id: int):
        user_data = self.db.execute_query("SELECT lifetime_spent FROM users WHERE id = %s", (user_id,), fetch='one')
        lifetime_spent = user_data['lifetime_spent'] if user_data else 0

        role_tiers = self.db.execute_query("SELECT * FROM role_tiers ORDER BY amount_required ASC", fetch='all')

        member = await guild.fetch_member(user_id)
        for tier in role_tiers:
            if lifetime_spent >= tier['amount_required']:
                role = guild.get_role(tier['role_id'])
                if role and role not in member.roles:
                    await member.add_roles(role)
                    log.info(f"Applied role {role.name} to user {user_id} based on lifetime spent.")

async def setup(bot):
    await bot.add_cog(DeliveryCog(bot))
