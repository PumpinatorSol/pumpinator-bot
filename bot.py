import os
import json
import base64
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from dotenv import load_dotenv
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solders.rpc.config import RpcAccountInfoConfig

print("🚀 Starting bot...")

# Replace with your bot token directly
BOT_TOKEN = "7845913453:AAGdE4k2nQy-jVqwpQe6gVydT819Eth-aPA"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
TOKENS_FILE = 'added_tokens.txt'

METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
solana_client = Client(SOLANA_RPC_URL)

monitor_task = None

# === PDA Calculation ===
def get_metadata_pda(mint):
    seeds = [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(Pubkey.from_string(mint))]
    return Pubkey.find_program_address(seeds, METADATA_PROGRAM_ID)[0]

# === Fetch Metadata with Birdeye fallback ===
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
        print(f"[Fallback] Using Birdeye for {token_address}")
        try:
            res = requests.get(f"https://public-api.birdeye.so/public/token/{token_address}", headers={"X-API-KEY": "public"})
            data = res.json().get("data", {})
            return data.get("name", "UnknownToken"), data.get("symbol", "UNKNOWN"), int(data.get("decimals", 0))
        except Exception as fallback_error:
            print(f"[Birdeye ERROR]: {fallback_error}")

    return "UnknownToken", "UNKNOWN", 0

# === Token Save/Load ===
def load_tokens():
    return open(TOKENS_FILE).read().splitlines() if os.path.exists(TOKENS_FILE) else []

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
            await update.message.reply_text("⚠️ Already tracking that token.")
    else:
        await update.message.reply_text("Usage: /add <token_mint>")

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
        await update.message.reply_text("Usage: /remove <token_mint>")

# === Solana Fetchers ===
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
        print(f"[TX Fetch ERROR]: {e}")
        return []

def fetch_transaction_details(sig):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [sig, "jsonParsed"]
        }
        res = requests.post(SOLANA_RPC_URL, json=payload)
        return res.json().get("result", {})
    except Exception as e:
        print(f"[Transaction Details Fetch ERROR]: {e}")
        return {}

# === Format & Send Message ===
async def send_transaction_data(token_address, txs, application):
    token_name, token_symbol, decimals = fetch_token_metadata(token_address)

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

            amount_bought = "?"
            for inner in meta.get("innerInstructions", []):
                for ix in inner.get("instructions", []):
                    parsed = ix.get("parsed", {})
                    if parsed.get("type") == "transfer":
                        info = parsed.get("info", {})
                        if info.get("mint") == token_address:
                            raw = int(info.get("amount", 0))
                            amount_bought = f"{raw / (10**decimals):,.4f}"

        except Exception as e:
            print(f"[Error Processing Transaction]: {e}")
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

# === Monitor Loop ===
async def monitor_transactions(application):
    print("✅ Monitoring started...")
    try:
        while True:
            tokens = load_tokens()
            if not tokens:
                print("⚠️ No tokens being tracked.")
            for token in tokens:
                txs = fetch_recent_transactions(token)
                await send_transaction_data(token, txs, application)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        print("🛑 Monitor task cancelled.")

# === Launch Bot ===
def main():
    print("🟢 Initializing bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add_token))
    app.add_handler(CommandHandler("remove", remove_token))

    async def post_init(app):
        global monitor_task
        monitor_task = asyncio.create_task(monitor_transactions(app))

    async def shutdown(app):
        if monitor_task:
            monitor_task.cancel()

    app.post_init = post_init
    app.shutdown = shutdown
    app.run_polling(drop_pending_updates=True)  # Drop pending updates to avoid issues with webhooks

if __name__ == "__main__":
    main()
