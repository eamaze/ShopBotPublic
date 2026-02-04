import discord
from discord.ext import commands
from discord import app_commands
import os

from utils.database import Database
from ui.views import EmbedEditorView
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class EmbedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    embed_group = app_commands.Group(name="embed", description="Embed creation and editing commands", default_permissions=discord.Permissions(administrator=True))

    @embed_group.command(name="create")
    async def create_embed(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """
        Launches the interactive embed builder to create and send an embed.
        """
        embed = EmbedBuilder(
            title="New Embed",
            description="This is a new embed. Use the buttons below to edit it."
        ).build()
        
        view = EmbedEditorView(target=channel, embed=embed)
        await interaction.response.send_message("Embed Builder:", embed=embed, view=view, ephemeral=True)
        log.info(f"Admin {interaction.user.id} initiated embed creation for channel {channel.id}.")

    @embed_group.command(name="edit")
    async def edit_embed(self, interaction: discord.Interaction, message_id: str):
        """
        Edits an existing embed created by the bot using the interactive builder.
        """
        try:
            # Assume the message is in the same channel the command is run in
            message = await interaction.channel.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await interaction.response.send_message("Message not found or invalid ID.", ephemeral=True)
            return

        if message.author.id != self.bot.user.id or not message.embeds:
            await interaction.response.send_message("This message is not an editable embed created by the bot.", ephemeral=True)
            return

        original_embed = message.embeds[0]
        
        view = EmbedEditorView(target=message, embed=original_embed)
        await interaction.response.send_message("Editing embed:", embed=original_embed, view=view, ephemeral=True)
        log.info(f"Admin {interaction.user.id} initiated embed edit for message {message.id}.")

async def setup(bot):
    await bot.add_cog(EmbedCog(bot))
