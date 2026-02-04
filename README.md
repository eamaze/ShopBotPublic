# ShopBot

ShopBot is a comprehensive Discord bot designed to manage a digital storefront directly within your Discord server. It features a fully automated shop system with PayPal integration, a support ticket system, daily giveaways, and robust admin tools.

## Features

### 🛒 Automated Shop System
- **Item Management**: Easily create, edit, restock, and remove items with rich embeds (images, descriptions, prices).
- **Shopping Cart**: Users can add items to their cart, view their cart, and checkout.
- **Payments**:
  - **PayPal**: Fully automated payment processing.
  - **Crypto**: Support for manual verification of crypto transactions.
- **Order Fulfillment**:
  - Automated delivery for digital goods.
  - Manual completion commands for specific orders.
- **Reviews**: Built-in review system for verified buyers.
- **Stock Control**: Toggle stock visibility (show exact quantity or just "In Stock").
- **Shop Status**: Open or close the shop with a single command.

### 🎫 Support Ticket System
- **One-Click Creation**: Users can open support tickets via a persistent button.
- **Private Channels**: Creates a private channel for each ticket between the user and staff.
- **Auto-Purge**: Automatically deletes closed ticket channels after a set period to keep your server clean.

### 🎁 Giveaway System
- **Daily Giveaways**: Automated daily giveaways for store credit.
- **Role Pings**: Automatically pings a specific role when a new giveaway starts.
- **Auto-End & Pick**: Automatically ends the giveaway and picks a winner after 24 hours.

### 🏆 Buyer Roles
- **Automated Tiers**: Configure roles that are automatically assigned to users once they reach a certain spending threshold.
- **Loyalty Rewards**: Reward your best customers with exclusive roles.

### 🛠️ Admin & Moderation
- **Admin Bypass**: Users with the configured Admin Role bypass all command checks.
- **Analytics**: Track sales and user spending.
- **Cart Management**: View active carts and wipe stale carts if necessary.
- **Spreadsheet Export**: Export your entire inventory to a CSV file.

## Setup

### Prerequisites
- Python 3.8+
- MySQL Database

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/ShopBotPublic.git
   cd ShopBotPublic
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Database Setup:**
   - Ensure you have a MySQL database running.
   - The bot will attempt to initialize tables on first run, but you need to provide connection details in `config.json` (see below).

4. **Configuration:**
   - Create a `config.json` file in the root directory. The bot reads this file and sets them as environment variables.
   - Alternatively, you can set these directly as environment variables.

   **Example `config.json` structure:**
   ```json
   {
       "discord": {
           "auth_token": "your_bot_token",
           "guild_id": "your_guild_id",
           "admin_role_id": "your_admin_role_id"
       },
       "db": {
           "host": "localhost",
           "user": "root",
           "password": "password",
           "name": "shopbot"
       },
       "paypal": {
           "mode": "sandbox",
           "sandbox_client_id": "your_sandbox_id",
           "sandbox_client_secret": "your_sandbox_secret",
           "live_client_id": "your_live_id",
           "live_client_secret": "your_live_secret"
       },
       "tickets": {
           "channel_id": "channel_id_for_ticket_panel"
       },
       "giveaway": {
           "channel_id": "channel_id_for_giveaways",
           "role_id": "role_id_to_ping",
           "credit_prize": 5.00
       },
       "shop": {
           "reminder_interval_hours": 48,
           "inactivity_threshold_hours": 48
       }
   }
   ```

5. **Run the bot:**
   ```bash
   python run_bot.py
   ```

## Usage

### Admin Commands
- `/shop create [name] [price] [quantity] [image_url] ...` - Create a new item.
- `/shop restock [item_id] [quantity]` - Add stock to an item.
- `/shop remove [item_id/name]` - Remove an item from the shop.
- `/shop set_status [open/closed]` - Open or close the shop.
- `/shop list_carts` - View all active carts.
- `/shop wipe_all_carts` - Emergency wipe of all carts.
- `/buyerroles add [role] [amount]` - Add a spending tier for a role.
- `/ticket setup` - Post the ticket creation panel in the configured channel.

### User Experience
- Users interact with the shop via buttons on the item embeds.
- "Add to Cart", "View Cart", and "Checkout" flows are entirely button-driven.

## License
[MIT License](LICENSE)
