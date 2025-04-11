require('dotenv').config(); // Load environment variables

const { Connection, PublicKey } = require('@solana/web3.js');
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');

// Set up config using .env values
const config = {
  botToken: process.env.BOT_TOKEN,
  chatId: process.env.TELEGRAM_CHAT_ID,
  adminId: process.env.ADMIN_ID,
  rpcUrl: process.env.SOLANA_RPC_URL,
  tokensFile: process.env.TOKENS_FILE || 'added_tokens.txt'
};

console.log('🔐 Loaded config:');
console.log(`  - RPC: ${config.rpcUrl}`);
console.log(`  - Chat ID: ${config.chatId}`);
console.log(`  - Token File: ${config.tokensFile}`);

const connection = new Connection(config.rpcUrl, 'confirmed');
console.log('✅ Connected to Solana WebSocket...');

const bot = new TelegramBot(config.botToken, { polling: false });

// Replace with the token you want to track
const TOKEN_MINT = 'TOKEN_MINT_ADDRESS_HERE';

// Replace with the Jupiter or Raydium market address or pool ID if needed
const MARKET_PROGRAM_ID = new PublicKey('JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB');

console.log('🚀 Buybot is running... waiting for buys...');

connection.onLogs('all', async (logInfo) => {
  try {
    const { signature, logs } = logInfo;
    const logText = logs.join('\n');

    // Filter: Only continue if this log mentions our token
    if (!logText.includes(TOKEN_MINT)) return;

    console.log(`🎯 Transaction matched token ${TOKEN_MINT}`);
    console.log(`🔍 Signature: ${signature}`);

    const txDetails = await connection.getParsedTransaction(signature, 'confirmed');
    if (!txDetails) {
      console.log('⚠️ Transaction details not found.');
      return;
    }

    const buyer = txDetails.transaction.message.accountKeys.find(k => k.signer)?.pubkey.toString() || 'Unknown';
    const slot = txDetails.slot;

    // Attempt to detect how many tokens were bought
    let tokenAmount = 0;
    try {
      const innerInstructions = txDetails.meta.innerInstructions || [];
      innerInstructions.forEach(ix => {
        ix.instructions.forEach(inner => {
          if (inner.parsed?.info?.mint === TOKEN_MINT && inner.parsed?.type === 'transfer') {
            tokenAmount += parseInt(inner.parsed.info.amount);
          }
        });
      });
    } catch (e) {
      console.warn('Could not determine token amount.');
    }

    // Convert raw token amount (assumes 9 decimals, adjust if needed)
    const tokenAmountFormatted = tokenAmount / Math.pow(10, 9);

    // 💵 Get USD price from DexScreener
    let usdPrice = 0;
    let usdValue = 0;

    try {
      const dexRes = await fetch(`https://api.dexscreener.com/latest/dex/pairs/solana/${TOKEN_MINT}`);
      const dexData = await dexRes.json();

      if (dexData.pair && dexData.pair.priceUsd) {
        usdPrice = parseFloat(dexData.pair.priceUsd);
        usdValue = tokenAmountFormatted * usdPrice;
      }
    } catch (e) {
      console.warn('Failed to fetch USD price from DexScreener.');
    }

    const msg = `💰 *New Buy Detected!*
Token: [${TOKEN_MINT}](https://solscan.io/token/${TOKEN_MINT})
Buyer: [${buyer}](https://solscan.io/account/${buyer})
Slot: ${slot}
Amount: ${tokenAmountFormatted.toFixed(2)} tokens
💵 Value: ~$${usdValue.toFixed(2)} USD
[View on Solscan](https://solscan.io/tx/${signature})`;

    bot.sendMessage(config.chatId, msg, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error('❌ Error in buybot:', err);
  }
});
