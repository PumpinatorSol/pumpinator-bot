import os
import json
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

TOKENS_FILE = 'added_tokens.txt'

# === Load & Save ===
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, 'r') as f:
            return f.read().splitlines()
    return []

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        f.write('\n'.join(tokens))

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
            return None

        # Print the raw JSON response to understand its structure
        response_data = response.json()
        print("Raw Response Data:", response_data)

        txs = response_data.get('result', [])
        if isinstance(txs, list):
            print(f"Fetched {len(txs)} transactions.")
            return txs
        else:
            print(f"Error: Expected list of transactions but got {type(txs)}.")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

# Function to fetch token info from DexScreener using mint
def get_token_info_from_dexscreener(mint):
    url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{mint}"
    response = requests.get(url)
    if response.ok:
        data = response.json()
        if data.get("pair"):
            base_token = data['pair']['baseToken']
            price = data['pair']['priceUsd']
            symbol = base_token.get('symbol', 'TKN')
            name = base_token.get('name', mint)
            return {
                'name': name,
                'symbol': symbol,
                'price_usd': price
            }
    return None

# === Send Transaction Data ===
async def send_transaction_data(data, application):
    if data:
        for tx in data:
            # Check if tx is a dictionary (this is where the error was happening before)
            if isinstance(tx, dict):
                tx_hash = tx.get("signature", "N/A")

                # If the transaction is not a dictionary, we need to skip it
                if not tx.get("signature"):
                    print("Transaction does not have a signature.")
                    continue
                
                # Extract transaction details from the transaction and fetch token info
                mint = tx.get("signature")  # This might be a mint address, or you can extract as needed
                token_info = get_token_info_from_dexscreener(mint)

                if token_info:
                    token_name = token_info.get('name', 'Unknown Token')
                    token_symbol = token_info.get('symbol', 'TKN')
                    token_price = token_info.get('price_usd', 'Unknown')

                    # Simulate some example data for now (this can be replaced with actual values)
                    amount_spent = '0.72 SOL'
                    usd_value = '106.34'
                    token_amount = '843,212.22'

                    message = f"""
<b>{token_name.upper()} BUY!</b>

💰 Amount Spent: {amount_spent} (${usd_value})  
🔹 {token_amount} {token_symbol} Purchased  
🔸 Price: ${token_price}  
📈 Position Change: +3.4%

📝 <a href="https://solscan.io/tx/{tx_hash}">Transaction</a>
"""
                    button = InlineKeyboardButton("🔗 View Transaction", url=f"https://solscan.io/tx/{tx_hash}")
                    keyboard = InlineKeyboardMarkup([[button]])

                    await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML", reply_markup=keyboard)
                else:
                    print(f"Failed to fetch token info for transaction: {tx_hash}")
            else:
                print(f"Transaction is not a dictionary: {tx}")
    else:
        print("No new transactions.")

# === Main Bot Setup ===
async def monitor_transactions(application):
    while True:
        token_addresses = load_tokens()
        for token_address in token_addresses:
            txs = fetch_recent_transactions(token_address, limit=5)  # Fetch up to 5 transactions per token
            if txs:
                for tx in txs:
                    await send_transaction_data([tx], application)  # Pass each transaction individually
        await asyncio.sleep(60)  # Check every 60 seconds for new transactions

# === Launch Bot ===
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers for add, remove, and start commands
    application.add_handler(CommandHandler("add", add_token))
    application.add_handler(CommandHandler("remove", remove_token))
    application.add_handler(CommandHandler("start", lambda update, context: update.message.reply_text("Bot is live!")))

    # Run monitor_transactions as a repeating task using asyncio
    asyncio.run(monitor_transactions(application))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
