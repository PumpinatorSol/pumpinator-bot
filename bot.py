import asyncio
import websockets
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext
from solders.pubkey import Pubkey
from solana.rpc.api import Client
import base64
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOLANA_RPC_URL = "wss://api.mainnet-beta.solana.com"  # WebSocket URL for Solana
TOKENS_FILE = 'added_tokens.txt'

# Set up Solana client
solana_client = Client(SOLANA_RPC_URL)

# Metadata Program ID for Solana tokens
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

# === PDA Calculation ===
def get_metadata_pda(mint):
    seeds = [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(Pubkey.from_string(mint))]
    return Pubkey.find_program_address(seeds, METADATA_PROGRAM_ID)[0]

# === Fetch Token Metadata ===
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
        return "UnknownToken", "UNKNOWN", 0

# === Token Save/Load ===
def load_tokens():
    return open(TOKENS_FILE).read().splitlines() if os.path.exists(TOKENS_FILE) else []

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        f.write('\n'.join(tokens))

# === Format & Send Message to Telegram ===
async def send_transaction_data(token_address, amount, buyer, tx_hash, application):
    token_name, token_symbol, decimals = fetch_token_metadata(token_address)

    # Formatting the message
    message = f"""
<b>💸 ${token_symbol} Buy Detected!</b>

🔹 <b>{amount}</b> {token_symbol} Purchased  
👤 Buyer: <a href="https://solscan.io/account/{buyer}">{buyer[:8]}...{buyer[-4:]}</a>
💰 TX Hash: <a href="https://solscan.io/tx/{tx_hash}">🔗 View TX</a>
""".strip()

    # Send message to the Telegram channel
    keyboard = InlineKeyboardMarkup([ 
        [InlineKeyboardButton("🔗 TX", url=f"https://solscan.io/tx/{tx_hash}")]
    ])
    await application.bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        parse_mode="HTML",
        reply_markup=keyboard
    )

# === WebSocket Listener for Solana ===
async def listen_solana_transactions():
    uri = "wss://api.mainnet-beta.solana.com"
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to Solana WebSocket!")
        
        # Subscribe to a particular token address or all token transfers
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [{
                "mentions": ["mint_address_here"]  # Specify the token's mint address
            }]
        }
        
        # Sending the subscription request
        await websocket.send(json.dumps(payload))

        # Listen for messages
        while True:
            response = await websocket.recv()
            data = json.loads(response)

            # Process incoming transaction data
            try:
                tx_hash = data.get("result", {}).get("signature", "N/A")
                amount = data.get("result", {}).get("amount", "?")  # Get the amount from the tx data
                buyer = data.get("result", {}).get("buyer", "unknown")  # Extract buyer info

                # Send the processed transaction to Telegram
                await send_transaction_data("mint_address_here", amount, buyer, tx_hash, application)
            except Exception as e:
                print(f"Error processing transaction: {e}")

# === Launch Bot ===
def main():
    print("🟢 Initializing bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add_token))
    app.add_handler(CommandHandler("remove", remove_token))

    # Start the WebSocket listener for Solana transactions
    asyncio.create_task(listen_solana_transactions())

    # Start the polling of Telegram bot (since we are no longer using webhooks)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
