import os
import json
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from dotenv import load_dotenv

print("🚀 Starting bot...")

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN") or "7845913453:AAGdE4k2nQy-jVqwpQe6gVydT819Eth-aPA"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "5405376313"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
TOKENS_FILE = 'added_tokens.txt'

# === Load & Save token list ===
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, 'r') as f:
            return f.read().splitlines()
    return []

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        f.write('\n'.join(tokens))

# === Telegram Commands ===
async def add_token(update: Update, context: CallbackContext):
    if len(context.args) == 1:
        token = context.args[0]
        tokens = load_tokens()
        if token not in tokens:
            tokens.append(token)
            save_tokens(tokens)
            await update.message.reply_text(f"✅ Token added: {token}")
        else:
            await update.message.reply_text("⚠️ Token already being tracked.")
    else:
        await update.message.reply_text("Usage: /add <token_address>")

async def remove_token(update: Update, context: CallbackContext):
    if len(context.args) == 1:
        token = context.args[0]
        tokens = load_tokens()
        if token in tokens:
            tokens.remove(token)
            save_tokens(tokens)
            await update.message.reply_text(f"❌ Token removed: {token}")
        else:
            await update.message.reply_text("Token not found.")
    else:
        await update.message.reply_text("Usage: /remove <token_address>")

# === Solana Fetchers ===
def fetch_recent_transactions(token_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [token_address, {"limit": 5}]
        }
        response = requests.post(SOLANA_RPC_URL, json=payload)
        return response.json().get("result", [])
    except Exception as e:
        print(f"[ERROR fetching txs]: {e}")
        return []

def fetch_transaction_details(signature):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, "jsonParsed"]
        }
        response = requests.post(SOLANA_RPC_URL, json=payload)
        return response.json().get("result", {})
    except:
        return None

def fetch_token_info(token_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [token_address, {"encoding": "jsonParsed"}]
        }
        response = requests.post(SOLANA_RPC_URL, json=payload)
        parsed = response.json()["result"]["value"]["data"]["parsed"]["info"]
        return parsed.get("name", "UnknownToken"), parsed.get("symbol", "UNKNOWN")
    except:
        return "UnknownToken", "UNKNOWN"

# === Messaging Logic ===
async def send_transaction_data(token_address, txs, application):
    token_name, token_symbol = fetch_token_info(token_address)

    for tx in txs:
        tx_hash = tx.get("signature", "N/A")
        details = fetch_transaction_details(tx_hash)
        if not details:
            continue

        try:
            meta = details.get("meta", {})
            sol_spent = (meta.get("preBalances", [0])[0] - meta.get("postBalances", [0])[0]) / 1e9
            keys = details["transaction"]["message"].get("accountKeys", [])
            buyer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]

            # Detect token amount bought
            amount_bought = "?"
            for inner in meta.get("innerInstructions", []):
                for ix in inner.get("instructions", []):
                    parsed = ix.get("parsed", {})
                    if parsed.get("type") == "transfer":
                        info = parsed.get("info", {})
                        if info.get("mint") == token_address:
                            amount_bought = info.get("amount")
        except:
            sol_spent = 0
            buyer = "unknown"
            amount_bought = "?"

        message = f"""
<b>💸 ${token_symbol} Buy Detected!</b>

🔹 <b>{amount_bought}</b> {token_symbol} Purchased  
💰 <b>{sol_spent:.4f} SOL</b> Spent  
👤 Buyer: <a href="https://solscan.io/account/{buyer}">{buyer[:8]}...{buyer[-4:]}</a>
        """.strip()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 TX", url=f"https://solscan.io/tx/{tx_hash}")]
        ])
        await application.bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard
        )

# === Monitoring Loop ===
async def monitor_transactions(application):
    print("✅ Monitoring started...")
    while True:
        tokens = load_tokens()
        if not tokens:
            print("⚠️ No tokens being tracked. Use /add <mint>")
        for token in tokens:
            txs = fetch_recent_transactions(token)
            await send_transaction_data(token, txs, application)
        await asyncio.sleep(60)

# === Launch Bot ===
def main():
    print("🟢 Initializing bot...")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("add", add_token))
    application.add_handler(CommandHandler("remove", remove_token))

    async def post_init(app):
        print("🛠️ post_init triggered. Launching monitor...")
        asyncio.create_task(monitor_transactions(app))

    application.post_init = post_init
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
