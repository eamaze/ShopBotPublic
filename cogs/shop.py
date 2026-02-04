import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from typing import Optional, Dict, Any
import os
import csv
from io import BytesIO, StringIO
from datetime import datetime, timedelta, timezone
import asyncio
import json

from utils.database import Database
from utils.payments import PayPalPayment
from ui.views import ShopItemView, process_paid_order, set_bot_instance, LeaveReviewView, cancel_invoice
from utils.logger import log
from utils.embed_builder import EmbedBuilder

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.paypal_handler = PayPalPayment()
        self._status_update_lock = asyncio.Lock()
        self._status_update_scheduled = False
        
        self.check_pending_payments.start()
        self.check_inactive_carts.start()
        self.purge_closed_carts.start()
        self.sync_item_embeds.start()

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("ShopCog is ready.")
        self.db.set_setting('shop_status', 'open')
        await self.schedule_status_update()

    @commands.Cog.listener()
    async def on_disconnect(self):
        log.warning("Bot has disconnected. Setting shop status to closed.")
        self.db.set_setting('shop_status', 'closed')
        await self.schedule_status_update()

    shop_group = app_commands.Group(name="shop", description="Shop commands", default_permissions=discord.Permissions(administrator=True))

    async def _update_item_embed(self, item: Dict[str, Any]):
        try:
            channel = self.bot.get_channel(item['channel_id'])
            if not channel: return
            message = await channel.fetch_message(item['message_id'])
            embed = message.embeds[0]
            hide_stock = self.db.get_setting('hide_stock') == 'true'
            stock_value = "Hidden" if hide_stock else item['quantity']
            embed.set_field_at(1, name="In Stock", value=stock_value)
            if item['quantity'] <= 0:
                if "SOLD OUT" not in embed.title:
                    embed.title = f"SOLD OUT - {item['name']}"
                    embed.color = discord.Color.red()
            else:
                if "SOLD OUT" in embed.title:
                    embed.title = item['name']
                    embed.color = discord.Color.blue()
            await message.edit(embed=embed)
        except discord.NotFound:
            log.error(f"Message/channel not found for item {item['name']} (ID: {item['id']}).")
        except Exception as e:
            log.error(f"Error updating embed for item {item['name']} (ID: {item['id']}): {e}", exc_info=True)

    @shop_group.command(name="getitemid")
    async def get_item_id(self, interaction: discord.Interaction, name: str):
        item = self.db.execute_query("SELECT id FROM items WHERE name = %s", (name,), fetch='one')
        await interaction.response.send_message(f"The ID for '{name}' is: `{item['id']}`" if item else f"Could not find '{name}'.", ephemeral=True)

    @shop_group.command(name="completeorder")
    async def complete_order(self, interaction: discord.Interaction, location: str):
        cart_data = self.db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
        if not cart_data or cart_data['status'] != 'paid':
            await interaction.response.send_message("This command can only be used in a paid cart channel.", ephemeral=True)
            return
        await interaction.response.defer()
        cart_items = json.loads(cart_data['cart_data'])
        total_value = sum(item['quantity'] * item['price'] for item in cart_items.values())
        self.db.execute_query("INSERT INTO users (id, delivery_value_handled) VALUES (%s, %s) ON DUPLICATE KEY UPDATE delivery_value_handled = delivery_value_handled + %s", (interaction.user.id, total_value, total_value))
        await interaction.followup.send(embed=EmbedBuilder(title="Order Delivered!", description=f"Delivered to: **{location}**", color=discord.Color.blue()).build())
        await interaction.channel.send(embed=EmbedBuilder(title="Thank you!", description="Please leave a review.", color=discord.Color.gold()).build(), view=LeaveReviewView())

    @shop_group.command(name="complete_crypto_order", description="Manually completes a crypto order after verifying the transaction.")
    async def complete_crypto_order(self, interaction: discord.Interaction, cart_id: int):
        await interaction.response.defer(ephemeral=True)
        cart_data = self.db.execute_query("SELECT * FROM carts WHERE id = %s", (cart_id,), fetch='one')

        if not cart_data:
            await interaction.followup.send(f"No cart found with ID {cart_id}.", ephemeral=True)
            return
        
        if cart_data['status'] != 'pending_manual_verification':
            await interaction.followup.send(f"Cart {cart_id} is not pending manual verification. Its status is '{cart_data['status']}'.", ephemeral=True)
            return
            
        channel = self.bot.get_channel(cart_data['channel_id'])
        if not channel:
            await interaction.followup.send(f"Could not find the channel for cart {cart_id}.", ephemeral=True)
            return

        await process_paid_order(channel, cart_data)
        await interaction.followup.send(f"Successfully marked cart {cart_id} as paid.", ephemeral=True)
        log.info(f"Admin {interaction.user.id} manually completed crypto order for cart {cart_id}.")

    @shop_group.command()
    async def create(self, interaction: discord.Interaction, name: str, price: float, quantity: int, image_url: str, color: Optional[str] = None, description: Optional[str] = None):
        embed_color = discord.Color.blue() # Default color
        if color:
            color_map = {
                "cyan": "#00FFFF", "red": "#FF0000", "green": "#00FF00", "blue": "#0000FF",
                "yellow": "#FFFF00", "magenta": "#FF00FF", "white": "#FFFFFF", "black": "#000000",
                "gold": "#FFD700", "orange": "#FFA500", "purple": "#800080", "pink": "#FFC0CB"
            }
            color_str = color.lower()
            hex_code = color_map.get(color_str)
            
            if not hex_code:
                # If not a known name, assume it might be a hex code
                if color_str.startswith("#") and len(color_str) in [4, 7]: # Support for #RGB and #RRGGBB
                     hex_code = color_str
            
            if hex_code:
                try:
                    embed_color = discord.Color.from_str(hex_code)
                except ValueError:
                    log.warning(f"Invalid color format '{hex_code}' provided for item '{name}'. Defaulting to blue.")
                    # embed_color is already blue, so we just log and continue
            else:
                log.warning(f"Unknown color name '{color}' provided for item '{name}'. Defaulting to blue.")

        embed = EmbedBuilder(title=name, description=description, color=embed_color).add_field(name="Price", value=f"${price:.2f}").add_field(name="In Stock", value="Hidden" if self.db.get_setting('hide_stock') == 'true' else quantity).set_image(url=image_url).build()
        message = await interaction.channel.send(embed=embed, view=ShopItemView())
        self.db.execute_query("INSERT INTO items (name, price, description, image_url, quantity, message_id, channel_id) VALUES (%s, %s, %s, %s, %s, %s, %s)", (name, price, description, image_url, quantity, message.id, message.channel.id))
        await interaction.response.send_message(f"Created item {name}.", ephemeral=True)

    @shop_group.command()
    async def restock(self, interaction: discord.Interaction, item_id: int, quantity: int):
        self.db.execute_query("UPDATE items SET quantity = quantity + %s WHERE id = %s", (quantity, item_id))
        item = self.db.execute_query("SELECT * FROM items WHERE id = %s", (item_id,), fetch='one')
        if item:
            await self._update_item_embed(item)
            await interaction.response.send_message(f"Restocked {item['name']} with {quantity} items.", ephemeral=True)
        else:
            await interaction.response.send_message("Item not found.", ephemeral=True)

    @shop_group.command()
    async def spreadsheet(self, interaction: discord.Interaction):
        items = self.db.execute_query("SELECT * FROM items", fetch='all')
        if not items:
            await interaction.response.send_message("No items found.", ephemeral=True)
            return
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(items[0].keys())
        for item in items: writer.writerow(item.values())
        output.seek(0)
        await interaction.response.send_message("Item spreadsheet:", file=discord.File(BytesIO(output.getvalue().encode('utf-8')), 'items.csv'), ephemeral=True)

    @shop_group.command()
    async def remove(self, interaction: discord.Interaction, identifier: str):
        item = self.db.execute_query("SELECT * FROM items WHERE id = %s" if identifier.isdigit() else "SELECT * FROM items WHERE name = %s", (int(identifier) if identifier.isdigit() else identifier,), fetch='one')
        if item:
            try:
                channel = await self.bot.fetch_channel(item['channel_id'])
                message = await channel.fetch_message(item['message_id'])
                await message.delete()
            except discord.NotFound: pass
            self.db.execute_query("DELETE FROM items WHERE id = %s", (item['id'],))
            await interaction.response.send_message(f"Removed item {item['name']}.", ephemeral=True)
        else:
            await interaction.response.send_message("Item not found.", ephemeral=True)

    @shop_group.command()
    @app_commands.checks.cooldown(1, 300, key=lambda i: i.guild_id)
    async def set_status(self, interaction: discord.Interaction, status: str):
        status = status.lower()
        if status not in ['open', 'closed']:
            await interaction.response.send_message("Status must be 'open' or 'closed'.", ephemeral=True)
            return
        self.db.set_setting('shop_status', status)
        await self.schedule_status_update()
        await interaction.response.send_message(f"Shop status set to **{status.upper()}**.", ephemeral=True)

    @shop_group.command()
    async def toggle_hide_stock(self, interaction: discord.Interaction):
        new_setting = 'false' if self.db.get_setting('hide_stock') == 'true' else 'true'
        self.db.set_setting('hide_stock', new_setting)
        await self.sync_item_embeds()
        await interaction.response.send_message(f"Stock visibility set to **{'Hidden' if new_setting == 'true' else 'Visible'}**.", ephemeral=True)

    @shop_group.command()
    async def set_status_channel(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        self.db.set_setting('shop_status_channel_id', str(channel.id))
        await self.schedule_status_update()
        await interaction.response.send_message(f"Shop status channel set to {channel.mention}.", ephemeral=True)

    @shop_group.command(name="list_carts", description="List all active and pending carts.")
    async def list_carts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        carts = self.db.execute_query("SELECT id, user_id, status, payment_method, last_activity FROM carts WHERE status IN ('active', 'pending_payment', 'pending_manual_verification')", fetch='all')

        if not carts:
            await interaction.followup.send("No active or pending carts found.", ephemeral=True)
            return

        embed = EmbedBuilder(title="Active & Pending Carts", color=discord.Color.blue()).build()
        description_lines = []
        for cart in carts:
            user = self.bot.get_user(cart['user_id']) or await self.bot.fetch_user(cart['user_id'])
            username = user.display_name if user else f"Unknown User (ID: {cart['user_id']})"
            
            channel_mention = f"<#{cart['channel_id']}>" if cart.get('channel_id') else "N/A"
            
            description_lines.append(
                f"**Cart ID:** {cart['id']}\n"
                f"**User:** {username}\n"
                f"**Status:** {cart['status'].replace('_', ' ').title()}\n"
                f"**Payment Method:** {cart['payment_method'] or 'N/A'}\n"
                f"**Last Activity:** {cart['last_activity'].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"**Channel:** {channel_mention}\n"
            )
        
        current_description = ""
        for line in description_lines:
            if len(current_description) + len(line) > 4000:
                embed.description = current_description
                await interaction.followup.send(embed=embed, ephemeral=True)
                embed = EmbedBuilder(title="Active & Pending Carts (cont.)", color=discord.Color.blue()).build()
                current_description = line
            else:
                current_description += line + "\n"
        
        if current_description:
            embed.description = current_description
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        await interaction.followup.send(f"Found {len(carts)} active or pending carts.", ephemeral=True)


    @shop_group.command(name="wipe_all_carts", description="Wipe and destroy ALL carts and their channels.")
    async def wipe_all_carts(self, interaction: discord.Interaction):
        class ConfirmWipe(ui.View):
            def __init__(self):
                super().__init__(timeout=60)
                self.value = None

            @ui.button(label="Confirm Wipe", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button):
                self.value = True
                self.stop()
                await interaction.response.send_message("Wipe confirmed. Proceeding...", ephemeral=True)

            @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button):
                self.value = False
                self.stop()
                await interaction.response.send_message("Wipe canceled.", ephemeral=True)

        view = ConfirmWipe()
        await interaction.response.send_message(
            "**WARNING:** This will delete ALL cart channels and clear ALL cart data from the database. This action is irreversible. Are you sure?",
            view=view,
            ephemeral=True
        )
        await view.wait()

        if view.value is None:
            await interaction.followup.send("Wipe timed out. No action taken.", ephemeral=True)
            return
        elif view.value is False:
            return

        await interaction.followup.send("Initiating full cart wipe...", ephemeral=True)

        carts = self.db.execute_query("SELECT id, channel_id FROM carts", fetch='all')
        deleted_channels_count = 0
        deleted_db_entries_count = 0

        for cart in carts:
            if cart.get('channel_id'):
                try:
                    channel = self.bot.get_channel(cart['channel_id'])
                    if channel:
                        await channel.delete()
                        deleted_channels_count += 1
                except discord.NotFound:
                    log.warning(f"Cart channel {cart['channel_id']} not found for deletion (Cart ID: {cart['id']}).")
                except Exception as e:
                    log.error(f"Error deleting cart channel {cart['channel_id']} (Cart ID: {cart['id']}): {e}", exc_info=True)
            
            self.db.execute_query("DELETE FROM carts WHERE id = %s", (cart['id'],))
            deleted_db_entries_count += 1
        
        embed = EmbedBuilder(
            title="Cart Wipe Complete",
            description=(
                f"Successfully deleted {deleted_channels_count} Discord channels.\n"
                f"Successfully cleared {deleted_db_entries_count} database entries."
            ),
            color=discord.Color.green()
        ).build()
        await interaction.followup.send(embed=embed, ephemeral=True)


    @tasks.loop(seconds=15)
    async def check_pending_payments(self):
        """
        This task now only handles automated payment confirmations for PayPal.
        """
        pending_carts = self.db.execute_query(
            "SELECT * FROM carts WHERE status = 'pending_payment' AND payment_method = 'paypal' AND payment_id IS NOT NULL", 
            fetch='all'
        )
        if not pending_carts:
            return

        log.debug(f"Polling for {len(pending_carts)} pending PayPal payments.")

        for cart in pending_carts:
            channel = self.bot.get_channel(cart['channel_id'])
            if not channel: 
                log.warning(f"Could not find channel for pending cart {cart['id']}. Skipping.")
                continue

            try:
                order_details = self.paypal_handler.get_payment_details(cart['payment_id'])
                if not order_details:
                    continue

                if order_details.get('status') == 'APPROVED':
                    log.info(f"Polling: PayPal order {cart['payment_id']} is approved. Capturing payment...")
                    capture_response = self.paypal_handler.capture_payment(cart['payment_id'])
                    
                    if capture_response and capture_response.get('status') == 'COMPLETED':
                        log.info(f"Polling: PayPal payment for cart {cart['id']} captured and completed.")
                        await process_paid_order(channel, cart)
                    else:
                        log.error(f"Polling: Failed to capture PayPal payment for cart {cart['id']}. Status: {capture_response.get('status') if capture_response else 'None'}")
                        await cancel_invoice(cart, channel, reason="There was an issue finalizing your PayPal payment. Please contact support.")
            
            except Exception as e:
                log.error(f"Error processing pending payment for cart {cart['id']}: {e}", exc_info=True)


    @check_pending_payments.before_loop
    async def before_check_pending_payments(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=int(os.getenv("SHOP_REMINDER_INTERVAL_HOURS", 48)))
    async def check_inactive_carts(self):
        if self.db.get_setting('shop_status') == 'closed': return
        threshold = datetime.now(timezone.utc) - timedelta(hours=int(os.getenv("SHOP_INACTIVITY_THRESHOLD_HOURS", 48)))
        inactive_carts = self.db.execute_query("SELECT * FROM carts WHERE last_activity < %s AND status = 'active'", (threshold,), fetch='all')
        for cart in inactive_carts:
            user = await self.bot.fetch_user(cart['user_id'])
            if user:
                await self.bot.get_channel(cart['channel_id']).send(f"{user.mention}, you have items in your cart.")

    @check_inactive_carts.before_loop
    async def before_check_inactive_carts(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=168)
    async def purge_closed_carts(self):
        carts_to_purge = self.db.execute_query("SELECT * FROM carts WHERE status IN ('closed', 'completed')", fetch='all')
        for cart in carts_to_purge:
            try:
                channel = self.bot.get_channel(cart['channel_id'])
                if channel: await channel.delete()
            except discord.NotFound: pass
        self.db.execute_query("DELETE FROM carts WHERE status IN ('closed', 'completed')")

    @purge_closed_carts.before_loop
    async def before_purge_closed_carts(self):
        await self.bot.wait_until_ready()

    @tasks.loop(count=1)
    async def sync_item_embeds(self):
        items = self.db.execute_query("SELECT * FROM items", fetch='all')
        for item in items: await self._update_item_embed(item)

    @sync_item_embeds.before_loop
    async def before_sync_item_embeds(self):
        await self.bot.wait_until_ready()

    async def schedule_status_update(self):
        if self._status_update_scheduled: return
        self._status_update_scheduled = True
        await asyncio.sleep(2)
        await self.update_shop_status_channel()

    async def update_shop_status_channel(self):
        async with self._status_update_lock:
            self._status_update_scheduled = False
            channel_id = self.db.get_setting('shop_status_channel_id')
            if not channel_id or channel_id == '0': return
            try:
                channel = self.bot.get_channel(int(channel_id))
                if channel and channel.name != f"Shop Status: {self.db.get_setting('shop_status').upper()}":
                    await channel.edit(name=f"Shop Status: {self.db.get_setting('shop_status').upper()}")
            except (discord.Forbidden, discord.HTTPException): pass

async def setup(bot):
    set_bot_instance(bot)
    await bot.add_cog(ShopCog(bot))
