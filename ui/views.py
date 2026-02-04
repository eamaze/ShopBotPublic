import discord
from discord import ui
from utils.database import Database
from utils.payments import PayPalPayment, CryptoPayment
from utils.logger import log
from utils.embed_builder import EmbedBuilder
import json
from datetime import datetime, timezone
import os
from typing import Optional

# Global variable to hold the bot instance
_bot_instance = None

def set_bot_instance(bot_obj):
    global _bot_instance
    _bot_instance = bot_obj

db = Database()
paypal_handler = PayPalPayment()
crypto_handler = CryptoPayment()

async def cancel_invoice(cart_data: dict, channel: discord.TextChannel, reason: str = "Your cart was modified."):
    """
    Cancels an existing invoice by deleting the message and clearing database fields.
    Sends an embed notification to the user with a specific reason.
    """
    if cart_data.get('invoice_message_id'):
        try:
            invoice_message = await channel.fetch_message(cart_data['invoice_message_id'])
            await invoice_message.delete()
            log.info(f"Deleted old invoice message {cart_data['invoice_message_id']} for cart {cart_data['id']}.")
        except discord.NotFound:
            log.warning(f"Could not find invoice message {cart_data['invoice_message_id']} to delete for cart {cart_data['id']}.")
        
        db.execute_query(
            "UPDATE carts SET invoice_message_id = NULL, payment_id = NULL, payment_method = NULL, status = 'active' WHERE id = %s",
            (cart_data['id'],)
        )
        
        embed = EmbedBuilder(
            title="Invoice Canceled",
            description=f"Your previous invoice has been canceled because: **{reason}** Please proceed to checkout again to generate a new invoice.",
            color=discord.Color.orange()
        ).build()
        await channel.send(embed=embed)
        log.info(f"Sent invoice cancellation embed for cart {cart_data['id']} with reason: {reason}.")

class CancelInvoiceView(ui.View):
    def __init__(self, cart_id: int):
        super().__init__(timeout=None)
        self.cart_id = cart_id

    @ui.button(label='Cancel Transaction', style=discord.ButtonStyle.danger)
    async def cancel_transaction(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        cart_data = db.execute_query("SELECT * FROM carts WHERE id = %s", (self.cart_id,), fetch='one')
        
        if cart_data:
            channel = _bot_instance.get_channel(cart_data['channel_id']) if _bot_instance else None
            if channel:
                await cancel_invoice(cart_data, channel, reason="You manually canceled the transaction.")
                await interaction.followup.send("Your transaction has been canceled.", ephemeral=True)
            else:
                await interaction.followup.send("Could not find the cart channel to cancel the transaction.", ephemeral=True)
        else:
            await interaction.followup.send("Could not find your cart to cancel the transaction.", ephemeral=True)

class CryptoCoinSelectionView(ui.View):
    def __init__(self, cart_data: dict, total_price: float):
        super().__init__(timeout=180)
        self.cart_data = cart_data
        self.total_price = total_price
        
        available_coins = crypto_handler.wallet_addresses.keys()
        options = [discord.SelectOption(label=coin) for coin in available_coins if crypto_handler.wallet_addresses[coin]]

        if not options:
             self.children[0].disabled = True
             self.children[0].placeholder = "No cryptocurrencies available."
        
        self.coin_select.options = options

    @ui.select(placeholder="Choose a cryptocurrency...")
    async def coin_select(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.defer()
        
        selected_coin = select.values[0]
        coin_id_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "LTC": "litecoin",
        }
        coin_id = coin_id_map.get(selected_coin, selected_coin.lower())
        
        price_usd = crypto_handler.get_coin_price(coin_id)
        if not price_usd:
            await interaction.followup.send("Sorry, I could not retrieve the current price for this coin. Please try again later.", ephemeral=True)
            return

        wallet_address = crypto_handler.wallet_addresses.get(selected_coin)
        if not wallet_address:
            await interaction.followup.send("Error: Wallet address for this coin is not configured.", ephemeral=True)
            return
            
        amount_crypto = self.total_price / price_usd

        db.execute_query(
            "UPDATE carts SET payment_method = %s, status = 'pending_payment', last_activity = %s WHERE id = %s",
            (f"crypto_{selected_coin}", datetime.now(timezone.utc), self.cart_data['id'])
        )

        embed = EmbedBuilder(
            title=f"Crypto Payment: {selected_coin}",
            description=f"Please send the exact amount to the address below.",
            color=discord.Color.blue()
        ).add_field(
            name="Amount",
            value=f"```{amount_crypto:.8f} {selected_coin}```"
        ).add_field(
            name="Address",
            value=f"```{wallet_address}```"
        ).add_field(
            name="Total Value",
            value=f"${self.total_price:.2f} USD"
        ).set_footer(
            text="Once you have sent the payment, click 'I Have Paid'."
        ).build()

        view = CryptoConfirmationView(cart_id=self.cart_data['id'])
        
        cart_channel = _bot_instance.get_channel(self.cart_data['channel_id'])
        if cart_channel:
            invoice_message = await cart_channel.send(embed=embed, view=view)
            db.execute_query("UPDATE carts SET invoice_message_id = %s WHERE id = %s", (invoice_message.id, self.cart_data['id']))
            await interaction.followup.send(f"Payment instructions have been sent to your cart channel: {cart_channel.mention}", ephemeral=True)
        else:
            await interaction.followup.send("Error: Could not find your cart channel.", ephemeral=True)
            
        await interaction.edit_original_response(content="Payment instructions sent.", view=None)

class CryptoConfirmationView(ui.View):
    def __init__(self, cart_id: int):
        super().__init__(timeout=3600)
        self.cart_id = cart_id

    @ui.button(label="I Have Paid", style=discord.ButtonStyle.success)
    async def confirm_payment(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        
        db.execute_query("UPDATE carts SET status = 'pending_manual_verification' WHERE id = %s", (self.cart_id,))
        
        delivery_role_id = os.getenv("SHOP_DELIVERY_PING_ROLE_ID")
        ping_message = ""
        if delivery_role_id:
            delivery_role = interaction.guild.get_role(int(delivery_role_id))
            if delivery_role:
                ping_message = f"{delivery_role.mention}"

        embed = EmbedBuilder(
            title="Payment Pending Verification",
            description=f"{interaction.user.mention} has marked this order as paid. An admin needs to manually verify the transaction on the blockchain.",
            color=discord.Color.gold()
        ).build()

        await interaction.channel.send(content=ping_message, embed=embed)

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        
    @ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_payment(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        cart_data = db.execute_query("SELECT * FROM carts WHERE id = %s", (self.cart_id,), fetch='one')
        if cart_data:
            await cancel_invoice(cart_data, interaction.channel, reason="You manually canceled the transaction.")
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content="Transaction canceled.", view=self, embed=None)

class PaymentMethodView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='PayPal', style=discord.ButtonStyle.primary)
    async def paypal_checkout(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_checkout(interaction, 'paypal')

    @ui.button(label='Crypto', style=discord.ButtonStyle.secondary)
    async def crypto_checkout(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')

        if not cart_data:
            await interaction.followup.send("Could not find your cart.", ephemeral=True)
            return
            
        if cart_data['status'] in ['paid', 'completed', 'closed']:
            await interaction.followup.send("This order has already been processed or closed and cannot be checked out again.", ephemeral=True)
            return
        elif cart_data['status'] == 'pending_payment':
            await interaction.followup.send("You already have a pending payment for this cart. Please complete it or use the 'Cancel Transaction' button on the invoice to generate a new one.", ephemeral=True)
            return

        if db.get_setting('shop_status') == 'closed':
            await interaction.followup.send("The shop is currently closed. You cannot proceed with checkout.", ephemeral=True)
            return

        cart = json.loads(cart_data['cart_data'])
        total_price = sum(i['quantity'] * i['price'] for i in cart.values())
        purchase_minimum = float(os.getenv("SHOP_PURCHASE_MINIMUM", "0.50"))

        if total_price < purchase_minimum:
            await interaction.followup.send(f"You must have at least ${purchase_minimum:.2f} in your cart to checkout.", ephemeral=True)
            return
            
        if cart_data.get('invoice_message_id'):
            channel = _bot_instance.get_channel(cart_data['channel_id']) if _bot_instance else None
            if channel:
                await cancel_invoice(cart_data, channel, reason="A new payment method was selected.")
                cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')

        await interaction.followup.send("Please select the cryptocurrency you wish to pay with:", view=CryptoCoinSelectionView(cart_data=cart_data, total_price=total_price), ephemeral=True)

    @ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel_checkout(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Checkout canceled.", view=None)

    async def handle_checkout(self, interaction: discord.Interaction, method: str):
        await interaction.response.defer(ephemeral=True) 
        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')

        if not cart_data:
            await interaction.followup.send("Could not find your cart.", ephemeral=True)
            return

        if cart_data['status'] in ['paid', 'completed', 'closed']:
            await interaction.followup.send("This order has already been processed or closed and cannot be checked out again.", ephemeral=True)
            return
        elif cart_data['status'] == 'pending_payment':
            await interaction.followup.send("You already have a pending payment for this cart. Please complete it or use the 'Cancel Transaction' button on the invoice to generate a new one.", ephemeral=True)
            return

        if db.get_setting('shop_status') == 'closed' and not cart_data.get('payment_id'):
            await interaction.followup.send("The shop is currently closed. You cannot proceed with checkout.", ephemeral=True)
            return

        cart = json.loads(cart_data['cart_data'])
        total_price = sum(i['quantity'] * i['price'] for i in cart.values())
        purchase_minimum = float(os.getenv("SHOP_PURCHASE_MINIMUM", "0.50"))

        if total_price < purchase_minimum:
            await interaction.followup.send(f"You must have at least ${purchase_minimum:.2f} in your cart to checkout.", ephemeral=True)
            return

        if cart_data.get('invoice_message_id'):
            channel = _bot_instance.get_channel(cart_data['channel_id']) if _bot_instance else None
            if channel:
                await cancel_invoice(cart_data, channel, reason="A new payment method was selected or a new invoice was generated.")
                cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
                if not cart_data:
                    await interaction.followup.send("Error: Cart data disappeared after canceling old invoice.", ephemeral=True)
                    return

        items_for_api = [{"name": i['name'], "unit_amount": {"currency_code": "USD", "value": f"{i['price']:.2f}"}, "quantity": i['quantity']} for i in cart.values()]
        description = "Your 2b2tStore order."
        
        base_webhook_url = os.getenv('WEBHOOK_BASE_URL')
        return_url = (
            f"{base_webhook_url}/payment-success?"
            f"username={interaction.user.display_name}&"
            f"order_id={cart_data['id']}&"
            f"cart_id={cart_data['id']}&"
            f"amount={total_price:.2f}"
        )
        cancel_url = f"{base_webhook_url}/payment-cancel"

        handler = paypal_handler
        approval_url, payment_id = handler.create_payment(total_price, items_for_api, description, return_url, cancel_url, cart_data['id'])

        if approval_url and payment_id:
            db.execute_query(
                "UPDATE carts SET payment_id = %s, payment_method = %s, status = 'pending_payment', last_activity = %s WHERE id = %s",
                (payment_id, method, datetime.now(timezone.utc), cart_data['id'])
            )
            
            embed = EmbedBuilder(
                title="Checkout",
                description=f"Please complete your payment here: [Pay Now]({approval_url})",
                color=discord.Color.blue()
            ).add_field(name="Instructions", value="I will automatically confirm your payment. Please do not close your cart.").build()
            
            invoice_message = await interaction.channel.send(embed=embed, view=CancelInvoiceView(cart_id=cart_data['id']))
            
            db.execute_query("UPDATE carts SET invoice_message_id = %s WHERE id = %s", (invoice_message.id, cart_data['id']))

            await interaction.followup.send(f"A payment link has been generated in your cart channel: {interaction.channel.mention}", ephemeral=True)
        else:
            await interaction.followup.send(f"Sorry, there was an error creating the {method} payment link.", ephemeral=True)

class LeaveReviewView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        reviews_channel_id = os.getenv("SHOP_REVIEWS_CHANNEL_ID")
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if reviews_channel_id and guild_id:
            reviews_channel_url = f"https://discord.com/channels/{guild_id}/{reviews_channel_id}"
            self.add_item(ui.Button(label='Leave a Review', style=discord.ButtonStyle.link, url=reviews_channel_url))

    @ui.button(label='Close Cart', style=discord.ButtonStyle.danger, custom_id='final_close_cart')
    async def close_cart(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
        if not cart_data: return

        db.execute_query("UPDATE carts SET status = 'completed' WHERE id = %s", (cart_data['id'],))
        archive_category = interaction.guild.get_channel(int(os.getenv("SHOP_ARCHIVE_CATEGORY_ID")))
        admin_role = interaction.guild.get_role(int(os.getenv("DISCORD_ADMIN_ROLE_ID")))
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True),
            admin_role: discord.PermissionOverwrite(read_messages=True)
        }
        await interaction.channel.edit(name=f"completed-cart-{cart_data['id']}", category=archive_category, overwrites=overwrites)
        await interaction.channel.send("This cart has been completed and archived.", view=DeleteCartView())
        self.stop()

async def process_paid_order(channel: discord.TextChannel, cart_data: dict, credit_spent: float = 0):
    cart = json.loads(cart_data['cart_data'])
    total_price = sum(i['quantity'] * i['price'] for i in cart.values())
    real_money_spent = total_price - credit_spent

    db.execute_query("INSERT INTO users (id, lifetime_spent) VALUES (%s, %s) ON DUPLICATE KEY UPDATE lifetime_spent = lifetime_spent + %s", (cart_data['user_id'], real_money_spent, real_money_spent))
    db.execute_query("UPDATE carts SET status = 'paid' WHERE id = %s", (cart_data['id'],))

    analytics_cog = _bot_instance.get_cog('AnalyticsCog') if _bot_instance else None
    for item_id in cart.keys():
        if analytics_cog:
            analytics_cog.log_event('purchase', item_id=int(item_id), user_id=cart_data['user_id'])

    await check_and_apply_roles(guild=channel.guild, user_id=cart_data['user_id'])
    
    delivery_role = channel.guild.get_role(int(os.getenv("SHOP_DELIVERY_PING_ROLE_ID")))
    if delivery_role:
        ping_message = await channel.send(f"{delivery_role.mention}")
        await ping_message.delete()

    embed = EmbedBuilder(title="Payment Successful", description="An admin will be with you shortly to complete your order.", color=discord.Color.green()).build()
    await channel.send(embed=embed)
    await channel.edit(name=f"paid-cart-{cart_data['id']}")

async def check_and_apply_roles(guild: discord.Guild, user_id: int):
    user_data = db.execute_query("SELECT lifetime_spent FROM users WHERE id = %s", (user_id,), fetch='one')
    if user_data:
        member = await guild.fetch_member(user_id)
        role_tiers = db.execute_query("SELECT * FROM role_tiers ORDER BY amount_required ASC", fetch='all')
        for tier in role_tiers:
            if user_data['lifetime_spent'] >= tier['amount_required']:
                role = guild.get_role(tier['role_id'])
                if role and role not in member.roles:
                    await member.add_roles(role)

class CreditModal(ui.Modal, title='Apply Store Credit'):
    amount = ui.TextInput(label='Amount to Apply')
    async def on_submit(self, interaction: discord.Interaction): await interaction.response.defer()

class QuantityModal(ui.Modal, title='Specify Quantity'):
    quantity = ui.TextInput(label='Quantity')
    async def on_submit(self, interaction: discord.Interaction): await interaction.response.defer()

class DeleteCartView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label='Delete Cart', style=discord.ButtonStyle.danger, custom_id='delete_cart')
    async def delete_cart(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.channel.delete()
        db.execute_query("DELETE FROM carts WHERE channel_id = %s", (interaction.channel.id,))

class DeleteTicketView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label='Delete Ticket', style=discord.ButtonStyle.danger, custom_id="delete_ticket")
    async def delete_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.channel.delete()
        db.execute_query("DELETE FROM tickets WHERE channel_id = %s", (interaction.channel.id,))

class ShopItemView(ui.View):
    def __init__(self): super().__init__(timeout=None)

    async def handle_cart_action(self, interaction: discord.Interaction, add: bool):
        if db.get_setting('shop_status') == 'closed':
            await interaction.response.send_message("The shop is currently closed.", ephemeral=True)
            return

        modal = QuantityModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        quantity = int(str(modal.quantity))

        item = db.execute_query("SELECT * FROM items WHERE message_id = %s", (interaction.message.id,), fetch='one')
        
        cart_data = db.execute_query("SELECT * FROM carts WHERE user_id = %s AND status = 'active'", (interaction.user.id,), fetch='one')
        
        cart_channel = None
        if not cart_data:
            cart_id = db.execute_query("INSERT INTO carts (user_id, cart_data, last_activity) VALUES (%s, %s, %s)", (interaction.user.id, json.dumps({}), datetime.now(timezone.utc)))
            category = interaction.guild.get_channel(int(os.getenv("SHOP_CART_CATEGORY_ID")))
            admin_role = interaction.guild.get_role(int(os.getenv("DISCORD_ADMIN_ROLE_ID")))
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True),
                admin_role: discord.PermissionOverwrite(read_messages=True)
            }
            cart_channel = await interaction.guild.create_text_channel(f"cart-{cart_id}", overwrites=overwrites, category=category)
            
            db.execute_query("UPDATE carts SET channel_id = %s WHERE id = %s", (cart_channel.id, cart_id))
            cart_data = db.execute_query("SELECT * FROM carts WHERE id = %s", (cart_id,), fetch='one')
        else:
            cart_channel = _bot_instance.get_channel(cart_data['channel_id']) if _bot_instance else None


        if add:
            if not item or item['quantity'] < quantity:
                await interaction.followup.send("Sorry, this item is sold out or has insufficient stock.", ephemeral=True)
                return
            db.execute_query("UPDATE items SET quantity = quantity - %s WHERE id = %s", (quantity, item['id']))
        else:
            if not cart_data:
                await interaction.followup.send("You do not have an active cart.", ephemeral=True)
                return
            db.execute_query("UPDATE items SET quantity = quantity + %s WHERE id = %s", (quantity, item['id']))

        cart = json.loads(cart_data['cart_data']) if cart_data else {}
        
        if cart_data and cart_data.get('invoice_message_id'):
            await cancel_invoice(cart_data, cart_channel)

        item_id = str(item['id'])
        if add:
            cart[item_id] = {'quantity': cart.get(item_id, {}).get('quantity', 0) + quantity, 'price': item['price'], 'name': item['name']}
        else:
            if item_id in cart:
                cart[item_id]['quantity'] -= quantity
                if cart[item_id]['quantity'] <= 0: del cart[item_id]
        
        total_price = sum(i['quantity'] * i['price'] for i in cart.values())
        embed = EmbedBuilder(title=f"{interaction.user.name.capitalize()}'s Cart", color=discord.Color.green())
        for i in cart.values(): embed.add_field(name=i['name'], value=f"Quantity: {i['quantity']}\nPrice: ${i['price']:.2f}", inline=False)
        embed.set_footer(text=f"Total Price: ${total_price:.2f}" if cart else "Your cart is empty.")

        if not cart_data['message_id']:
            cart_message = await cart_channel.send(embed=embed.build(), view=CartView())
            db.execute_query("UPDATE carts SET message_id = %s, cart_data = %s WHERE id = %s", (cart_message.id, json.dumps(cart), cart_data['id']))
        else:
            cart_message = await cart_channel.fetch_message(cart_data['message_id'])
            await cart_message.edit(embed=embed.build())
            db.execute_query("UPDATE carts SET cart_data = %s, last_activity = %s WHERE id = %s", (json.dumps(cart), datetime.now(timezone.utc), cart_data['id']))

    @ui.button(label='Add to Cart', style=discord.ButtonStyle.primary, custom_id='add_to_cart')
    async def add_to_cart(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_cart_action(interaction, add=True)

    @ui.button(label='Remove from Cart', style=discord.ButtonStyle.danger, custom_id='remove_from_cart')
    async def remove_from_cart(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_cart_action(interaction, add=False)

class CartView(ui.View):
    def __init__(self): super().__init__(timeout=None)

    @ui.button(label='Apply Credit', style=discord.ButtonStyle.secondary, custom_id='apply_credit')
    async def apply_credit(self, interaction: discord.Interaction, button: ui.Button):
        if db.get_setting('shop_status') == 'closed':
            await interaction.response.send_message("The shop is currently closed.", ephemeral=True)
            return

        modal = CreditModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        amount_to_apply = float(str(modal.amount))

        user_data = db.execute_query("SELECT balance FROM users WHERE id = %s", (interaction.user.id,), fetch='one')
        if not user_data or amount_to_apply > user_data['balance']:
            await interaction.channel.send("You do not have enough credit.")
            return

        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
        cart = json.loads(cart_data['cart_data'])
        total_price = sum(i['quantity'] * i['price'] for i in cart.values())
        credit_to_apply = min(amount_to_apply, total_price)

        db.execute_query("UPDATE users SET balance = balance - %s WHERE id = %s", (credit_to_apply, interaction.user.id))
        db.execute_query("UPDATE carts SET credit_applied = credit_applied + %s WHERE id = %s", (credit_to_apply, cart_data['id']))

        embed = interaction.message.embeds[0]
        embed.add_field(name="Credit Applied", value=f"${credit_to_apply:.2f}", inline=False)
        embed.set_footer(text=f"New Total Price: ${total_price - credit_to_apply:.2f}")
        
        if total_price - credit_to_apply <= 0:
            self.children[1].disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await process_paid_order(interaction.channel, cart_data, credit_spent=credit_to_apply)
        else:
            await interaction.message.edit(embed=embed)
        
    @ui.button(label='Checkout', style=discord.ButtonStyle.success, custom_id='checkout')
    async def checkout(self, interaction: discord.Interaction, button: ui.Button):
        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
        if db.get_setting('shop_status') == 'closed' and not (cart_data and cart_data.get('payment_id')):
            await interaction.response.send_message("The shop is currently closed.", ephemeral=True)
            return
        await interaction.response.send_message("Please select your payment method:", view=PaymentMethodView(), ephemeral=True)

    @ui.button(label='Close Cart', style=discord.ButtonStyle.danger, custom_id='close_cart')
    async def close_cart(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        cart_data = db.execute_query("SELECT * FROM carts WHERE channel_id = %s", (interaction.channel.id,), fetch='one')
        if not cart_data: return

        cart = json.loads(cart_data['cart_data'])
        for item_id, i in cart.items():
            db.execute_query("UPDATE items SET quantity = quantity + %s WHERE id = %s", (i['quantity'], item_id))
        if cart_data['credit_applied'] > 0:
            db.execute_query("UPDATE users SET balance = balance + %s WHERE id = %s", (cart_data['credit_applied'], cart_data['user_id']))

        archive_category = interaction.guild.get_channel(int(os.getenv("SHOP_ARCHIVE_CATEGORY_ID")))
        admin_role = interaction.guild.get_role(int(os.getenv("DISCORD_ADMIN_ROLE_ID")))
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True),
            admin_role: discord.PermissionOverwrite(read_messages=True)
        }
        await interaction.channel.edit(name=f"closed-cart-{cart_data['id']}", category=archive_category, overwrites=overwrites)
        await interaction.channel.send("This cart has been completed and archived.", view=DeleteCartView())
        db.execute_query("UPDATE carts SET status = 'closed' WHERE id = %s", (cart_data['id'],))

class GiveawayView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, custom_id="enter_giveaway")
    async def enter_giveaway(self, interaction: discord.Interaction, button: ui.Button):
        giveaway = db.execute_query("SELECT * FROM giveaways ORDER BY id DESC LIMIT 1", fetch='one')
        if not giveaway:
            await interaction.response.send_message("There is no active giveaway.", ephemeral=True)
            return
        if db.execute_query("SELECT * FROM giveaway_entrants WHERE giveaway_id = %s AND user_id = %s", (giveaway['id'], interaction.user.id), fetch='one'):
            await interaction.response.send_message("You have already entered this giveaway.", ephemeral=True)
        else:
            db.execute_query("INSERT INTO giveaway_entrants (giveaway_id, user_id) VALUES (%s, %s)", (giveaway['id'], interaction.user.id))
            await interaction.response.send_message("You have entered the giveaway!", ephemeral=True)

class TicketCreationView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        if db.execute_query("SELECT * FROM tickets WHERE user_id = %s AND status = 'open'", (interaction.user.id,), fetch='one'):
            await interaction.followup.send("You already have an open ticket.", ephemeral=True)
            return
        category = interaction.guild.get_channel(int(os.getenv("TICKETS_CATEGORY_ID")))
        admin_role = interaction.guild.get_role(int(os.getenv("DISCORD_ADMIN_ROLE_ID")))
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True),
            admin_role: discord.PermissionOverwrite(read_messages=True)
        }
        channel = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        db.execute_query("INSERT INTO tickets (user_id, channel_id) VALUES (%s, %s)", (interaction.user.id, channel.id))
        await channel.send(f"Welcome {interaction.user.mention}! Please describe your issue.", view=TicketChannelView())
        await interaction.followup.send(f"Your ticket has been created: {channel.mention}", ephemeral=True)

class TicketChannelView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        db.execute_query("UPDATE tickets SET status = 'closed' WHERE channel_id = %s", (interaction.channel.id,))
        archive_category = interaction.guild.get_channel(int(os.getenv("TICKETS_ARCHIVE_CATEGORY_ID")))
        await interaction.channel.edit(category=archive_category, sync_permissions=True)
        await interaction.channel.send("Ticket closed.", view=DeleteTicketView())
        self.stop()

class EmbedContentModal(ui.Modal, title='Edit Embed Content'):
    title_input = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    description_input = ui.TextInput(label='Description', style=discord.TextStyle.paragraph, required=False, max_length=4000)
    color_input = ui.TextInput(label='Color (Hex Code)', style=discord.TextStyle.short, required=False, min_length=6, max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class EmbedFieldModal(ui.Modal, title='Edit Embed Field'):
    name_input = ui.TextInput(label='Field Name', style=discord.TextStyle.short, required=True, max_length=256)
    value_input = ui.TextInput(label='Field Value', style=discord.TextStyle.paragraph, required=True, max_length=1024)
    inline_input = ui.TextInput(label='Inline (True/False)', style=discord.TextStyle.short, required=False, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class EmbedEditorView(ui.View):
    def __init__(self, target: discord.TextChannel | discord.Message, embed: discord.Embed):
        super().__init__(timeout=300)
        self.target = target
        self.embed = embed
        self.selected_field_index = None
        self.update_field_selector()

    def update_field_selector(self):
        selector = next((item for item in self.children if isinstance(item, ui.Select)), None)
        if not selector:
            return

        options = [
            discord.SelectOption(label=f"Field {i+1}: {field.name}", value=str(i))
            for i, field in enumerate(self.embed.fields)
        ]
        
        if not options:
            options.append(discord.SelectOption(label="No fields available", value="-1"))
            selector.disabled = True
        else:
            selector.disabled = False

        selector.options = options
        selector.placeholder = "Select a field to edit or remove"

    @ui.button(label='Edit Content', style=discord.ButtonStyle.primary, row=0)
    async def edit_content(self, interaction: discord.Interaction, button: ui.Button):
        modal = EmbedContentModal()
        modal.title_input.default = self.embed.title
        modal.description_input.default = self.embed.description
        modal.color_input.default = str(self.embed.color) if self.embed.color else ""

        await interaction.response.send_modal(modal)
        await modal.wait()

        self.embed.title = str(modal.title_input)
        self.embed.description = str(modal.description_input)
        try:
            color_str = str(modal.color_input).strip()
            if color_str:
                self.embed.color = discord.Color(int(color_str.replace("#", ""), 16))
            else:
                self.embed.color = None
        except (ValueError, TypeError):
            pass # Ignore invalid color

        await interaction.followup.edit_message(interaction.message.id, embed=self.embed, view=self)

    @ui.button(label='Add Field', style=discord.ButtonStyle.secondary, row=0)
    async def add_field(self, interaction: discord.Interaction, button: ui.Button):
        modal = EmbedFieldModal(title="Add New Field")
        await interaction.response.send_modal(modal)
        await modal.wait()

        name = str(modal.name_input)
        value = str(modal.value_input)
        inline = str(modal.inline_input).lower() == 'true'
        
        if len(self.embed.fields) < 25:
            self.embed.add_field(name=name, value=value, inline=inline)
            self.update_field_selector()
            await interaction.followup.edit_message(interaction.message.id, embed=self.embed, view=self)
        else:
            await interaction.followup.send("You can't have more than 25 fields.", ephemeral=True)

    @ui.select(placeholder="Select a field to edit or remove", row=1)
    async def field_selector(self, interaction: discord.Interaction, select: ui.Select):
        if select.values[0] == "-1":
            await interaction.response.defer()
            return

        self.selected_field_index = int(select.values[0])
        
        edit_button = next((item for item in self.children if isinstance(item, ui.Button) and item.label == "Edit Field"), None)
        remove_button = next((item for item in self.children if isinstance(item, ui.Button) and item.label == "Remove Field"), None)
        if edit_button: edit_button.disabled = False
        if remove_button: remove_button.disabled = False

        await interaction.response.edit_message(view=self)

    @ui.button(label='Edit Field', style=discord.ButtonStyle.secondary, row=2, disabled=True)
    async def edit_field(self, interaction: discord.Interaction, button: ui.Button):
        if self.selected_field_index is None:
            await interaction.response.send_message("Please select a field first.", ephemeral=True)
            return

        field = self.embed.fields[self.selected_field_index]
        modal = EmbedFieldModal(title="Edit Field")
        modal.name_input.default = field.name
        modal.value_input.default = field.value
        modal.inline_input.default = str(field.inline)

        await interaction.response.send_modal(modal)
        await modal.wait()

        name = str(modal.name_input)
        value = str(modal.value_input)
        inline = str(modal.inline_input).lower() == 'true'

        self.embed.set_field_at(self.selected_field_index, name=name, value=value, inline=inline)
        self.update_field_selector()
        
        button.disabled = True
        remove_button = next((item for item in self.children if isinstance(item, ui.Button) and item.label == "Remove Field"), None)
        if remove_button: remove_button.disabled = True
        
        await interaction.followup.edit_message(interaction.message.id, embed=self.embed, view=self)
        self.selected_field_index = None

    @ui.button(label='Remove Field', style=discord.ButtonStyle.danger, row=2, disabled=True)
    async def remove_field(self, interaction: discord.Interaction, button: ui.Button):
        if self.selected_field_index is None:
            await interaction.response.send_message("Please select a field first.", ephemeral=True)
            return

        self.embed.remove_field(self.selected_field_index)
        self.update_field_selector()
        
        button.disabled = True
        edit_button = next((item for item in self.children if isinstance(item, ui.Button) and item.label == "Edit Field"), None)
        if edit_button: edit_button.disabled = True

        await interaction.response.edit_message(embed=self.embed, view=self)
        self.selected_field_index = None

    @ui.button(label='Send/Save', style=discord.ButtonStyle.success, row=3)
    async def send_embed(self, interaction: discord.Interaction, button: ui.Button):
        if isinstance(self.target, discord.TextChannel):
            await self.target.send(embed=self.embed)
            await interaction.response.edit_message(content="Embed sent!", view=None, embed=None)
        elif isinstance(self.target, discord.Message):
            await self.target.edit(embed=self.embed)
            await interaction.response.edit_message(content="Embed saved!", view=None, embed=None)
        self.stop()

    @ui.button(label='Cancel', style=discord.ButtonStyle.danger, row=3)
    async def cancel_embed(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Canceled.", view=None, embed=None)
        self.stop()
