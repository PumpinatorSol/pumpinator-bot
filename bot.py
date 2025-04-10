import os
import requests
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Initialize Solana client
solana_client = Client(SOLANA_RPC_URL)

# Metadata Program ID
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

# Function to get token metadata
def fetch_token_metadata(token_address):
    try:
        # Fetch metadata PDA (Program Derived Address)
        seeds = [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(Pubkey.from_string(token_address))]
        metadata_pda = Pubkey.find_program_address(seeds, METADATA_PROGRAM_ID)[0]

        res = solana_client.get_account_info(metadata_pda)
        value = res.get("result", {}).get("value", {})
        
        if not value:
            raise ValueError("No metadata found")

        data = value.get("data", [])[0]
        decoded = base64.b64decode(data)

        # Extract token name and symbol from metadata
        name = decoded[1 + 32 + 32:1 + 32 + 32 + 32].decode('utf-8').rstrip('\x00')
        symbol = decoded[1 + 32 + 32 + 32:1 + 32 + 32 + 32 + 10].decode('utf-8').rstrip('\x00')

        return name, symbol
    except Exception as e:
        print(f"[Error Fetching Metadata]: {e}")
        return "UnknownToken", "UNKNOWN"

# Function to fetch recent transactions (simplified for buy detection)
def fetch_recent_transactions(token_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [token_address, {"limit": 5}]
        }
        res = requests.post(SOLANA_RPC_URL, json=payload)
        return res.json().get("result", [])
    except Exception as e:
        print(f"[Transaction Fetch Error]: {e}")
        return []

# Function to send transaction data to Telegram
async def send_transaction_data(token_address, txs, application):
    token_name, token_symbol = fetch_token_metadata(token_address)

    for tx in txs:
        tx_hash = tx.get("signature", "N/A")

        message = f"""
<b>💸 ${token_symbol} Buy Detected!</b>

🔹 <b>{token_name}</b> ({token_symbol}) Purchased  
🔗 <a href="https://solscan.io/tx/{tx_hash}">Transaction Details</a>
""".strip()

        await application.bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode="HTML"
        )

# Command handler to add tokens to the tracking list
async def add_token(update: Update, context: CallbackContext):
    if len(context.args) == 1:
        token = context.args[0]
        await update.message.reply_text(f"✅ Tracking token: {token}")
    else:
        await update.message.reply_text("Usage: /add <token_mint>")

# Monitor loop to check for new transactions
async def monitor_transactions(application):
    print("✅ Monitoring started...")
    try:
        tokens = ["YourTokenMintAddressHere"]  # Add your token mint addresses here
        while True:
            for token in tokens:
                txs = fetch_recent_transactions(token)
                if txs:
                    await send_transaction_data(token, txs, application)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        print("🛑 Monitor task cancelled.")

# Main function to start the bot
def main():
    print("🟢 Initializing bot...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Add Telegram handlers
    app.add_handler(CommandHandler("add", add_token))

    # Start the monitoring loop in the background
    async def post_init(app):
        monitor_task = asyncio.create_task(monitor_transactions(app))

    app.post_init = post_init

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
