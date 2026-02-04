import os
import json
import hmac
import hashlib
import asyncio
from aiohttp import web
from .logger import log

# Global instances populated by the main bot
bot_instance = None
db_instance = None

# Define the path to the web directory
WEB_DIR = os.path.join(os.path.dirname(__file__), '..', 'web')

def set_webhook_dependencies(bot, db):
    """Sets the bot and database instances for the webhook handler."""
    global bot_instance, db_instance
    bot_instance = bot
    db_instance = db
    log.info("Webhook dependencies (bot, db) have been set.")

async def _read_html_file(filename: str) -> str:
    """Helper function to read an HTML file asynchronously."""
    filepath = os.path.join(WEB_DIR, filename)
    try:
        # Use asyncio.to_thread for blocking file I/O in an async context
        return await asyncio.to_thread(lambda: open(filepath, 'r', encoding='utf-8').read())
    except FileNotFoundError:
        log.error(f"HTML file not found: {filepath}")
        return "<h1>404 - Not Found</h1>"
    except Exception as e:
        log.error(f"Error reading HTML file {filepath}: {e}")
        return "<h1>500 - Internal Server Error</h1>"

async def index_handler(request: web.Request):
    """Handles requests to the root path and serves the home page."""
    log.info(f"Serving index.html for request from {request.remote}")
    content = await _read_html_file('index.html')
    return web.Response(text=content, content_type='text/html')

async def process_webhook_payment(cart_id: int, status: str, payload: dict):
    """Generic function to process a payment notification from a webhook."""
    cart_data = db_instance.execute_query("SELECT * FROM carts WHERE id = %s", (cart_id,), fetch='one')
    if not cart_data:
        log.error(f"Webhook received for non-existent cart ID: {cart_id}")
        return

    if cart_data['status'] in ['paid', 'completed', 'closed']:
        log.info(f"Webhook for already processed cart {cart_id}. Ignoring.")
        return

    channel = bot_instance.get_channel(cart_data['channel_id'])
    if not channel:
        log.error(f"Could not find channel {cart_data['channel_id']} for cart {cart_id} from webhook.")
        return

    from ui.views import process_paid_order, cancel_invoice

    try:
        if status in ['confirmed', 'finished', 'approved']:
            log.info(f"Webhook: Payment for cart {cart_id} confirmed with status '{status}'.")
            await process_paid_order(channel, cart_data)
        
        elif status in ['failed', 'refunded', 'expired', 'partially_paid']:
            log.warning(f"Webhook: Payment for cart {cart_id} failed with status: {status}")
            reason = f"Your payment has {status}. Please try again or contact support."
            await cancel_invoice(cart_data, channel, reason=reason)
        
        else:
            log.info(f"Webhook for cart {cart_id} received with unhandled status: {status}")
    except Exception as e:
        log.error(f"Error processing webhook for cart {cart_id}: {e}", exc_info=True)


async def generic_success_handler(request: web.Request):
    """A generic handler for successful payment redirects, serving a personalized HTML page."""
    log.info(f"Redirect success handler triggered for {request.path}")
    
    # Extract query parameters
    username = request.query.get('username', 'Customer')
    order_id = request.query.get('order_id', 'N/A')
    cart_id = request.query.get('cart_id', 'N/A')
    amount = request.query.get('amount', 'N/A')

    # Read the HTML template
    html_content = await _read_html_file('payment-success.html')

    # Replace placeholders
    html_content = html_content.replace('<span id="username-placeholder">Customer</span>', f'<span id="username-placeholder">{username}</span>')
    html_content = html_content.replace('<span id="order-id-placeholder">N/A</span>', f'<span id="order-id-placeholder">{order_id}</span>')
    html_content = html_content.replace('<span id="cart-id-placeholder">N/A</span>', f'<span id="cart-id-placeholder">{cart_id}</span>')
    html_content = html_content.replace('<span id="amount-placeholder">N/A</span>', f'<span id="amount-placeholder">${amount}</span>')

    return web.Response(text=html_content, content_type='text/html')

async def generic_cancel_handler(request: web.Request):
    """A generic handler for canceled payment redirects, serving an HTML page."""
    log.info(f"Redirect cancel handler triggered for {request.path}")
    html_content = await _read_html_file('payment-cancel.html')
    return web.Response(text=html_content, content_type='text/html')

async def start_webhook_server(bot, db):
    """Initializes and starts the aiohttp web server."""
    set_webhook_dependencies(bot, db)
    
    app = web.Application()
    # Routes for automated webhook notifications

    # Routes for user-facing browser redirects
    app.router.add_get('/', index_handler) # New home page route
    app.router.add_get('/payment-success', generic_success_handler) # Generic success page
    app.router.add_get('/payment-cancel', generic_cancel_handler) # Generic cancel page
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("WEBHOOK_PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    try:
        await site.start()
        log.info(f"Webhook server started successfully on port {port}.")
    except Exception as e:
        log.critical(f"Failed to start webhook server: {e}", exc_info=True)
