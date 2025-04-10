import os
import json
import base64
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext
from dotenv import load_dotenv
from solders.pubkey import Pubkey
from solana.rpc.api import Client

print("🚀 Starting bot...")

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
TOKENS_FILE = 'added_tokens.txt'

# Initialize Solana Client
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
solana_client = Client(SOLANA_RPC_URL)

# === Load & Save Tokens ===
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, 'r') as f:
            return f.read().splitlines()
    return []

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        f.write('\n'.join(tokens))

# === Fetch Metadata ===
def get_metadata_pda(mint):
    seeds = [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(Pubkey.from_string(mint))]
    return Pubkey.find_program_address(seeds, METADATA_PROGRAM_ID)[0]

def fetch_token_metadata(token_address):
    try:
        metadata_pda = get_metadata_pda(token_address)
        res = solana_client.get_account_info(metadata_pda)
        value = res.get("result", {}).get("value", {})

        if not value:
            raise ValueError("No metadata found")

        data = value.get("data", [])[0]
        decoded = base64.b64decode(data)

        name = decoded[1 + 32 + 32:1 + 32 + 32 + 32].decode('utf-8').rstrip('\x00')
        symbol = decoded[1 + 32 + 32 + 32:1 + 32 + 32 + 32 + 10].decode('utf-8').rstrip('\x00')
        decimals = int(solana_client.get_token_supply(Pubkey.from_string(token_address))["result"]["value"]["decimals"])
        return name, symbol, decimals
    except Exception as e:
        print(f"[Metaplex ERROR]: {e}")
        return None, None, None

# === Fetch Transactions ===
def fetch_recent_transactions(token_address, limit=5):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [token_address, {"limit": limit}]
        }
        response = requests.post(SOLANA_RPC_URL, json=payload)
        if response.status_code != 200:
            print("Error fetching transactions:", response.status_code)
            return []

        # Debug: Print raw response data to understand its structure
        response_data = response.json()
        print("Raw Response Data:", response_data)

        txs = response_data.get('result', [])
        return txs if isinstance(txs, list) else []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []

# === Send Transaction Data ===
async def send_transaction_data(tx, application):
    if tx:
        tx_hash = tx.get("signature", "N/A")
        if not tx_hash:
            print("Skipping transaction with no signature.")
            return

        # Fetch metadata for the token associated with this transaction
        token_name, token_symbol, decimals = fetch_token_metadata(tx_hash)  # assuming tx_hash is token address here
        if not token_name:
            token_name = "Unknown Token"
            token_symbol = "UNKNOWN"

        # Example data for now
        amount_spent = '0.72 SOL'
        usd_value = '106.34'
        token_amount = '843,212.22'

        message = f"""
<b>{token_name.upper()} BUY!</b>

💰 Amount Spent: {amount_spent} (${usd_value})  
🔹 {token_amount} {token_symbol} Purchased  
🔸 Price: $0.000126  
📈 Position Change: +3.4%

📝 <a href="https://solscan.io/tx/{tx_hash}">Transaction</a>
"""
        button = InlineKeyboardButton("🔗 View Transaction", url=f"https://solscan.io/tx/{tx_hash}")
        keyboard = InlineKeyboardMarkup([[button]])

        await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML", reply_markup=keyboard)

# === Monitor Loop ===
async def monitor_transactions(application):
    while True:
        token_addresses = load_tokens()
        for token_address in token_addresses:
            txs = fetch_recent_transactions(token_address, limit=5)  # Fetch up to 5 transactions per token
            if txs:
                for tx in txs:
                    await send_transaction_data(tx, application)  # Pass each transaction individually
        await asyncio.sleep(60)  # Check every 60 seconds for new transactions

# === Bot Setup ===
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("add", add_token))
    application.add_handler(CommandHandler("remove", remove_token))
    application.add_handler(CommandHandler("start", lambda update, context: update.message.reply_text("Bot is live!")))

    asyncio.run(monitor_transactions(application))  # Run monitoring task

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
