import os
import sys
import asyncio

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.logger import log
from utils.config import setup_os
from utils.database import Database
import mysql.connector

# Immediately load environment variables from config.json
if not setup_os():
    log.critical("Could not load configuration. The application cannot start.")
    exit()

import discord
from discord.ext import commands
from utils.config import setup_paypal
from ui import views as ui_views
from utils.webhook_server import start_webhook_server

def initialize_database():
    """
    Establishes the database connection.
    Returns the database instance on success, None on failure.
    """
    try:
        db_instance = Database()  # This will initialize the singleton instance
        return db_instance
    except mysql.connector.Error:
        # The Database class already logs the critical error.
        return None

class AdminBypassCommandTree(discord.app_commands.CommandTree):
    """
    A custom CommandTree that allows users with DISCORD_ADMIN_ROLE_ID to bypass all command checks.
    """
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(bot, *args, **kwargs)
        self.admin_role_id = None
        admin_role_id_str = os.getenv("DISCORD_ADMIN_ROLE_ID")
        if admin_role_id_str:
            try:
                self.admin_role_id = int(admin_role_id_str)
                log.info(f"Admin bypass enabled for role ID: {self.admin_role_id}")
            except ValueError:
                log.error(f"Invalid DISCORD_ADMIN_ROLE_ID in environment variables: {admin_role_id_str}. Must be an integer.")

    async def _check_can_run(self, interaction: discord.Interaction, command: discord.app_commands.Command) -> bool:
        # Check for admin bypass first
        if self.admin_role_id and interaction.guild and interaction.user:
            member = interaction.guild.get_member(interaction.user.id)
            if member:
                admin_role = interaction.guild.get_role(self.admin_role_id)
                if admin_role and admin_role in member.roles:
                    log.info(f"Admin bypass: User {interaction.user.name} ({interaction.user.id}) executed command {command.name}.")
                    return True # Admin bypasses all checks

        # If not an admin, or admin_role_id is not set, proceed with normal checks
        return await super()._check_can_run(interaction, command)

class MyBot(commands.Bot):
    def __init__(self, db_instance):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents, help_command=None, tree_cls=AdminBypassCommandTree)
        self.tree.on_error = self.on_app_command_error
        self.db = db_instance

    async def setup_hook(self):
        # Pass bot instance to views that need it
        ui_views.set_bot_instance(self)

        # Start the webhook server in the background
        asyncio.create_task(start_webhook_server(self, self.db))

        # List of persistent views that need to be added globally
        persistent_views = [
            ui_views.ShopItemView,
            ui_views.CartView,
            ui_views.DeleteCartView,
            ui_views.DeleteTicketView,
            ui_views.GiveawayView,
            ui_views.TicketCreationView,
            ui_views.TicketChannelView,
            ui_views.LeaveReviewView,
        ]
        for ViewClass in persistent_views:
            self.add_view(ViewClass())

        # Dynamically load all cogs from the 'cogs' directory
        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('__'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    log.info(f"Loaded cog: cogs.{filename[:-3]}")
                except Exception as e:
                    log.error(f"Failed to load cog cogs.{filename[:-3]}: {e}", exc_info=True)

        guild_id = int(os.getenv("DISCORD_GUILD_ID"))
        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        synced_commands = await self.tree.sync(guild=guild)
        log.info(f"Synced {len(synced_commands)} application commands.")

        # --- New logic for admin command visibility (selective) ---
        admin_role_id_str = os.getenv("DISCORD_ADMIN_ROLE_ID")
        if admin_role_id_str:
            try:
                admin_role_id = int(admin_role_id_str)
                
                permissions_to_set = []
                # Iterate through all synced commands to find those marked as admin-only
                for command in synced_commands:
                    # Check if the command or group has default_permissions=False
                    # This indicates it's meant to be hidden by default and explicitly granted
                    is_admin_command = False
                    if isinstance(command, discord.app_commands.Group):
                        if command.default_permissions is False:
                            is_admin_command = True
                    elif isinstance(command, discord.app_commands.Command):
                        if command.default_member_permissions is False:
                            is_admin_command = True
                    
                    if is_admin_command:
                        permissions_to_set.append(
                            discord.app_commands.GuildCommandPermission(
                                command.id,
                                permissions=[
                                    discord.app_commands.Permission(admin_role_id, True, type=discord.app_commands.AppCommandPermissionType.role)
                                ]
                            )
                        )
                
                if permissions_to_set:
                    await self.tree.set_permissions(guild=guild, permissions=permissions_to_set)
                    log.info(f"Set command permissions for {len(permissions_to_set)} admin-only commands for role {admin_role_id} in guild {guild_id}.")
                else:
                    log.info(f"No admin-only commands found to set specific permissions for role {admin_role_id} in guild {guild_id}.")

            except ValueError:
                log.error(f"Invalid DISCORD_ADMIN_ROLE_ID in environment variables: {admin_role_id_str}. Must be an integer.")
            except Exception as e:
                log.error(f"Failed to set command permissions for admin role: {e}", exc_info=True)
        # --- End new logic ---

    async def on_ready(self):
        log.info(f'Logged in as {self.user.name}')
        activity = discord.Activity(type=discord.ActivityType.playing, name="Goat of all shop bots")
        await self.change_presence(activity=activity)
        log.info("Bot status set to 'watching 2b2t'")

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.errors.CheckFailure):
            # This handles permission errors from checks like _is_admin_role_func
            # The check function itself is responsible for sending the feedback.
            log.warning(f"Check failed for user {interaction.user.id} on command {interaction.command.name if interaction.command else 'unknown'}.")
            # If the check failed, and it wasn't bypassed by admin, send a generic message.
            if not interaction.response.is_done():
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        elif isinstance(error, discord.app_commands.errors.MissingRole):
            await interaction.response.send_message("You do not have the required role to use this command.", ephemeral=True)
        else:
            log.error(f"An unhandled app command error occurred: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

def main():
    """
    Main function to set up and run the bot.
    """
    db_instance = initialize_database()
    if not db_instance:
        log.critical("Database connection failed. The bot will not start.")
        return

    setup_paypal()

    bot = MyBot(db_instance)

    token = os.getenv("DISCORD_AUTH_TOKEN")
    if not token:
        log.critical("DISCORD_AUTH_TOKEN not found in environment variables.")
        return

    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        log.critical("Failed to log in. Please check your Discord authentication token.")

if __name__ == '__main__':
    main()