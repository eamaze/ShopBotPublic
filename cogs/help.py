import discord
from discord.ext import commands
from discord import app_commands
import os

from utils.logger import log
from utils.embed_builder import EmbedBuilder

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _user_can_run_command(self, interaction: discord.Interaction, command: app_commands.Command | app_commands.Group) -> bool:
        """
        Checks if the user has permission to run a given app_commands.Command or Group.
        This checks default_member_permissions (for commands) or default_permissions (for groups)
        and custom app_commands.checks.
        Includes admin bypass logic for visibility.
        """
        # Admin bypass for visibility
        admin_role_id_str = os.getenv("DISCORD_ADMIN_ROLE_ID")
        if admin_role_id_str and interaction.guild and interaction.user:
            try:
                admin_role_id = int(admin_role_id_str)
                member = interaction.guild.get_member(interaction.user.id)
                if member:
                    admin_role = interaction.guild.get_role(admin_role_id)
                    if admin_role and admin_role in member.roles:
                        return True # Admin can see all commands
            except ValueError:
                log.error(f"Invalid DISCORD_ADMIN_ROLE_ID in environment variables: {admin_role_id_str}. Must be an integer.")
        
        # Determine which permission attribute to check using getattr for robustness
        permissions_to_check = None
        if isinstance(command, app_commands.Command):
            permissions_to_check = getattr(command, 'default_member_permissions', None)
        elif isinstance(command, app_commands.Group):
            permissions_to_check = getattr(command, 'default_permissions', None)

        # Check default permissions
        if permissions_to_check is not None:
            # If default_member_permissions is set to False, it means only explicitly allowed roles can see it.
            # If it's a Permissions object, check if the user has those permissions.
            if isinstance(permissions_to_check, discord.Permissions):
                if not interaction.user.guild_permissions.is_superset(permissions_to_check):
                    return False
            elif permissions_to_check is False: # Command is hidden by default
                # If it's hidden by default, and not bypassed by admin, then it's not visible.
                # The global set_permissions in run_bot.py handles making it visible for admins.
                # This check here is for non-admins.
                return False
        
        # Evaluate custom checks only for individual commands (Groups don't have .checks directly)
        # This part is tricky because checks can raise exceptions. We need to simulate the check.
        if isinstance(command, app_commands.Command):
            # For help command visibility, we generally don't want to run the actual checks
            # as they might have side effects or send messages.
            # Instead, we rely on Discord's native permission system (which set_permissions modifies)
            # and default_member_permissions.
            # If a command has specific checks, and it's not an admin, we assume it might not be visible.
            # This is a simplification for help command display.
            if command.checks:
                # If there are custom checks, and the user is not an admin (already bypassed above),
                # we assume they might not have access for help display purposes.
                # A more robust solution would involve trying to run the checks without side effects,
                # which is complex and not directly supported by discord.py.
                return False

        return True

    @app_commands.command(name="help", description="Show help for commands or groups")
    @app_commands.describe(query="The name of a command or group to get help for (e.g., 'shop', 'shop create')")
    async def help_command(self, interaction: discord.Interaction, query: str = None):
        """
        Displays help for all commands or a specific command/group, filtered by user permissions.
        """
        await interaction.response.defer(ephemeral=True)

        # Get all registered commands from the bot's command tree
        # Use self.bot.tree.get_commands() which respects global commands and guild-specific commands
        all_commands_from_tree = self.bot.tree.get_commands(guild=discord.Object(id=interaction.guild_id))

        # Filter commands based on user permissions
        user_accessible_commands = []
        for cmd in all_commands_from_tree:
            # Check if the command is a top-level command or a subcommand of an accessible group
            if cmd.parent is None or (cmd.parent and await self._user_can_run_command(interaction, cmd.parent)):
                if await self._user_can_run_command(interaction, cmd):
                    user_accessible_commands.append(cmd)

        if query:
            query = query.lower()
            found_command = None
            
            # Try to find a command or group matching the query among accessible ones
            for cmd in user_accessible_commands:
                full_command_name = cmd.qualified_name.lower() # e.g., "shop create"
                if full_command_name == query:
                    found_command = cmd
                    break
            
            if found_command:
                embed = EmbedBuilder(title=f"Help for /{found_command.qualified_name}", color=discord.Color.blue())
                embed.description = found_command.description or "No description available."

                # Handle options/subcommands based on whether it's a Command or a Group
                if isinstance(found_command, app_commands.Group):
                    subcommands_list = []
                    for sub_cmd in found_command.commands: # Iterate through subcommands of the group
                        # Check if the subcommand itself is accessible
                        if await self._user_can_run_command(interaction, sub_cmd):
                            subcommands_list.append(f"`/{found_command.qualified_name} {sub_cmd.name}`: {sub_cmd.description or 'No description.'}")
                    if subcommands_list:
                        embed.add_field(name="Subcommands", value="\n".join(subcommands_list), inline=False)
                elif isinstance(found_command, app_commands.Command):
                    if found_command.options: # Regular command options
                        options_list = []
                        for option in found_command.options:
                            options_list.append(f"`{option.name}`: {option.description or 'No description.'} (Required: {option.required})")
                        if options_list:
                            embed.add_field(name="Options", value="\n".join(options_list), inline=False)
                
                await interaction.followup.send(embed=embed.build(), ephemeral=True)
                return
            else:
                await interaction.followup.send(f"Command or group '{query}' not found or you do not have permission to view it.", ephemeral=True)
                return

        # If no query, list all accessible top-level commands/groups
        embed = EmbedBuilder(title="Available Commands", description="Use `/help <command_name>` for more info on a specific command or group (e.g., `/help shop`).", color=discord.Color.green())
        
        # Group top-level commands and groups for display
        top_level_commands_and_groups = {}
        for cmd in user_accessible_commands:
            if cmd.parent is None: # This is a top-level command or group
                top_level_commands_and_groups[cmd.name] = cmd.description or "No description."
        
        commands_list = []
        for name, desc in sorted(top_level_commands_and_groups.items()):
            commands_list.append(f"`/{name}`: {desc}")
        
        if commands_list:
            embed.add_field(name="Commands & Groups", value="\n".join(commands_list), inline=False)
        else:
            embed.description = "No commands available or you do not have permission to view any."

        await interaction.followup.send(embed=embed.build(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
