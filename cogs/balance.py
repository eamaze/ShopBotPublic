import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from utils.database import Database
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class CreditCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    # Main command group
    balance_group = app_commands.Group(name="balance", description="Commands for managing store credit")
    
    # Admin-only subgroup
    admin_balance_group = app_commands.Group(name="admin", parent=balance_group, description="Admin commands for managing credit", default_permissions=discord.Permissions(administrator=True))

    @balance_group.command(name="check", description="Checks your or another user's store credit balance.")
    async def balance_check(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """
        Checks the store credit balance. 
        Regular users can only check their own balance.
        Admins can check any user's balance.
        """
        target_user = user or interaction.user

        # Permission check: if a user is specified, the invoker must be an admin
        if user and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to check other users' balances.", ephemeral=True)
            log.warning(f"User {interaction.user.id} attempted to check {user.id}'s balance without admin permissions.")
            return

        user_data = self.db.execute_query("SELECT balance FROM users WHERE id = %s", (target_user.id,), fetch='one')
        balance = user_data['balance'] if user_data else 0
        
        embed = EmbedBuilder(
            title=f"{target_user.display_name}'s Balance",
            description=f"Store credit balance: **${balance:.2f}**",
            color=discord.Color.green()
        ).build()
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info(f"Balance check for user {target_user.id} (requested by {interaction.user.id}): ${balance:.2f}.")

    @admin_balance_group.command(name="add", description="Adds credit to a user's balance.")
    async def balance_add(self, interaction: discord.Interaction, user: discord.Member, amount: float):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
            
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return
            
        self.db.execute_query("INSERT INTO users (id, balance) VALUES (%s, %s) ON DUPLICATE KEY UPDATE balance = balance + %s", (user.id, amount, amount))
        await interaction.response.send_message(f"Added ${amount:.2f} to {user.mention}'s balance.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} added ${amount:.2f} credit to user {user.id}.")

    @admin_balance_group.command(name="set", description="Sets a user's credit balance to a specific amount.")
    async def balance_set(self, interaction: discord.Interaction, user: discord.Member, amount: float):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
            
        if amount < 0:
            await interaction.response.send_message("Amount cannot be negative.", ephemeral=T)
            return

        self.db.execute_query("INSERT INTO users (id, balance) VALUES (%s, %s) ON DUPLICATE KEY UPDATE balance = %s", (user.id, amount, amount))
        await interaction.response.send_message(f"Set {user.mention}'s balance to ${amount:.2f}.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} set user {user.id}'s balance to ${amount:.2f}.")

async def setup(bot):
    await bot.add_cog(CreditCog(bot))
