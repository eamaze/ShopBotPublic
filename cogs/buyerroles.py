import discord
from discord.ext import commands
from discord import app_commands
import os

from utils.database import Database
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class BuyerRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    buyer_roles_group = app_commands.Group(name="buyerroles", description="Buyer role tier commands", default_permissions=discord.Permissions(administrator=True))

    @buyer_roles_group.command(name="add")
    async def add_role(self, interaction: discord.Interaction, role: discord.Role, amount: float):
        """
        Adds a new role tier.
        """
        self.db.execute_query("INSERT INTO role_tiers (role_id, amount_required) VALUES (%s, %s) ON DUPLICATE KEY UPDATE amount_required = %s", (role.id, amount, amount))
        await interaction.response.send_message(f"Added role tier: {role.mention} requires ${amount:.2f} spent.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} added role tier {role.name} (ID: {role.id}) with amount ${amount:.2f}.")

    @buyer_roles_group.command(name="remove")
    async def remove_role(self, interaction: discord.Interaction, role: discord.Role):
        """
        Removes a role tier.
        """
        self.db.execute_query("DELETE FROM role_tiers WHERE role_id = %s", (role.id,))
        await interaction.response.send_message(f"Removed role tier: {role.mention}.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} removed role tier {role.name} (ID: {role.id}).")

    @buyer_roles_group.command(name="list")
    async def list_roles(self, interaction: discord.Interaction):
        """
        Lists all role tiers.
        """
        role_tiers = self.db.execute_query("SELECT * FROM role_tiers ORDER BY amount_required ASC", fetch='all')

        embed_builder = EmbedBuilder(title="Role Tiers", color=discord.Color.blue())
        if role_tiers:
            for tier in role_tiers:
                role = interaction.guild.get_role(tier['role_id'])
                if role:
                    embed_builder.add_field(name=role.name, value=f"Requires ${tier['amount_required']:.2f} spent.", inline=False)
                else:
                    log.warning(f"Role with ID {tier['role_id']} not found for role tier listing.")
        else:
            embed_builder.set_description("No role tiers configured.")
            
        await interaction.response.send_message(embed=embed_builder.build(), ephemeral=True)
        log.info(f"Admin {interaction.user.id} listed role tiers.")

async def setup(bot):
    await bot.add_cog(BuyerRolesCog(bot))
