require('dotenv').config();
console.log("✅ MONGO_URI loaded as:", process.env.MONGO_URI || '❌ MISSING');
console.log("🤖 BOT_TOKEN loaded:", process.env.BOT_TOKEN ? 'Yes' : '❌ MISSING');
console.log("📨 TELEGRAM_CHAT_ID:", process.env.TELEGRAM_CHAT_ID || '❌ MISSING');

const { Telegraf } = require('telegraf');
const { connectDB, getDB } = require('./db');
const axios = require('axios');

const BOT_TOKEN = process.env.BOT_TOKEN;
const MONGO_URI = process.env.MONGO_URI;
const CHAT_ID = process.env.TELEGRAM_CHAT_ID;
const ADMIN_ID = process.env.ADMIN_ID || CHAT_ID;  // Fallback to CHAT_ID

if (!BOT_TOKEN || !MONGO_URI || !CHAT_ID) {
  console.error('❌ Missing environment variables. Please check your .env file.');
  process.exit(1);
}

const bot = new Telegraf(BOT_TOKEN);
const userStates = new Map();

// Function to send buy alerts to Telegram
async function postBuyToTelegram(buy, tokenAddress) {
  const msg = `💰 *New Buy Detected!*\nSpent: ~$${Number(buy.amountUsd).toFixed(2)} USD\n[📈 View Chart](https://www.dexscreener.com/solana/${tokenAddress})`;
  console.log('📤 Sending buy alert:', msg);
  await bot.telegram.sendMessage(CHAT_ID, msg, { parse_mode: 'Markdown' });
}

// Fetch recent trades from the DexScreener API
async function getRecentTrades(tokenAddress) {
  try {
    console.log(`📡 Fetching recent trades for token: ${tokenAddress}`);
    const url = `https://api.dexscreener.com/latest/dex/pairs/solana/${tokenAddress}`;
    const { data } = await axios.get(url);
    console.log('🔍 DexScreener response:', data);

    if (!data.pair || !data.pair.txns) {
      console.log(`⚠️ No trades found for token: ${tokenAddress}`);
      return [];
    }
    return data.pair.txns.m5 || [];  // Fetch the last 5 minutes of trades
  } catch (err) {
    console.warn(`⚠️ Error fetching trades for ${tokenAddress}:`, err.message);
    return [];
  }
}

// Check and track trades
async function checkTrades() {
  const db = getDB();
  const tokens = await db.collection('tracked_tokens').find().toArray();
  console.log('🔍 Tracking the following tokens:', tokens);

  for (const token of tokens) {
    const trades = await getRecentTrades(token.mint); // Get trades for the token's address
    console.log(`📈 Trades for ${token.mint}:`, trades);

    for (const trade of trades.reverse()) {
      const exists = await db.collection('buy_logs').findOne({ tx: trade.txHash });
      if (!exists) {
        console.log(`✔️ New trade detected: ${trade.txHash} (Type: ${trade.type})`);
        await db.collection('buy_logs').insertOne({ tx: trade.txHash, type: trade.type, time: Date.now() });

        if (trade.type === 'buy') {
          await postBuyToTelegram(trade, token.mint); // Send buy alert for the trade
        }
      } else {
        console.log(`❌ Skipping duplicate trade: ${trade.txHash}`);
      }
    }
  }
}

// Bot commands for adding and removing tokens
bot.telegram.setMyCommands([
  { command: 'add', description: 'Add a token to track' },
  { command: 'remove', description: 'Remove a token from tracking' }
]);

// Command to add a token
bot.command('add', async (ctx) => {
  if (String(ctx.from.id) !== ADMIN_ID) return ctx.reply('⛔ Unauthorized');
  userStates.set(ctx.from.id, 'awaiting_add_mint');
  await ctx.reply('📥 Send the token contract address to add it.');
  console.log('🔔 Waiting for contract address to add token.');
});

// Command to remove a token
bot.command('remove', async (ctx) => {
  if (String(ctx.from.id) !== ADMIN_ID) return ctx.reply('⛔ Unauthorized');
  userStates.set(ctx.from.id, 'awaiting_remove_mint');
  await ctx.reply('📤 Send the token contract address to remove it.');
  console.log('🔔 Waiting for contract address to remove token.');
});

// Handle contract address input
bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = userStates.get(userId);
  const mint = ctx.message.text.trim(); // Token address
  const db = getDB();

  if (!state) return;

  if (state === 'awaiting_add_mint') {
    const exists = await db.collection('tracked_tokens').findOne({ mint });
    if (exists) {
      await ctx.reply('⚠️ Token is already being tracked.');
      console.log(`⚠️ Token already tracked: ${mint}`);
    } else {
      await db.collection('tracked_tokens').insertOne({ mint });
      await ctx.reply('✅ Token added and tracking started.');
      console.log(`✅ Token added and tracking started: ${mint}`);
    }
  }

  if (state === 'awaiting_remove_mint') {
    await db.collection('tracked_tokens').deleteOne({ mint });
    await ctx.reply('🗑️ Token removed from tracking.');
    console.log(`🗑️ Token removed from tracking: ${mint}`);
  }

  userStates.delete(userId);
});

// Initialize the bot
(async () => {
  await connectDB();
  await bot.launch();
  console.log('🚀 Pumpinator is live using DexScreener API...');
  setInterval(checkTrades, 60000);  // Check trades every 60 seconds
})();
