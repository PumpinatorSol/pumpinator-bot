require('dotenv').config();

const express = require('express');
const { Connection, PublicKey } = require('@solana/web3.js');
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');
const fs = require('fs');

const config = {
  botToken: process.env.BOT_TOKEN,
  chatId: process.env.TELEGRAM_CHAT_ID,
  adminId: process.env.ADMIN_ID,
  rpcUrl: process.env.SOLANA_RPC_URL,
  tokensFile: process.env.TOKENS_FILE || '/data/added_tokens.txt',
  baseUrl: process.env.RENDER_EXTERNAL_URL
};

const connection = new Connection(config.rpcUrl, 'confirmed');
const bot = new TelegramBot(config.botToken, {
  webHook: {
    port: process.env.PORT || 3000
  }
});

const app = express();
app.use(express.json());

app.post(`/bot${config.botToken}`, (req, res) => {
  bot.processUpdate(req.body);
  res.sendStatus(200);
});

const HOST = '0.0.0.0';
const PORT = process.env.PORT || 3000;
app.listen(PORT, HOST, () => {
  console.log(`✨ Webhook server running on http://localhost:${PORT}`);
});

const WEBHOOK_URL = `${config.baseUrl}/bot${config.botToken}`;
console.log('✨ Attempting to register webhook:', WEBHOOK_URL);
bot.setWebHook(WEBHOOK_URL);

console.log('✅ Buybot is running and connected to Solana RPC...');

const loadTrackedTokens = () => {
  try {
    return fs.readFileSync(config.tokensFile, 'utf-8')
      .split('\n')
      .filter(Boolean)
      .map(line => {
        const [mint, decimals] = line.split(',');
        return {
          mint: mint.trim(),
          decimals: parseInt(decimals.trim())
        };
      });
  } catch {
    return [];
  }
};

bot.onText(/\/add (.+)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const mintAddress = match[1].trim();

  try {
    const mintPubkey = new PublicKey(mintAddress);
    const info = await connection.getParsedAccountInfo(mintPubkey);

    if (!info.value) return bot.sendMessage(chatId, '❌ Invalid mint or token not found.');

    const decimals = info.value.data.parsed.info.decimals;
    if (!fs.existsSync(config.tokensFile)) fs.writeFileSync(config.tokensFile, '');

    const current = fs.readFileSync(config.tokensFile, 'utf-8').split('\n').filter(Boolean);
    if (current.find(l => l.startsWith(mintAddress))) {
      return bot.sendMessage(chatId, '⚠️ Token already tracked.');
    }

    fs.appendFileSync(config.tokensFile, `${mintAddress},${decimals}\n`);
    console.log(`✅ Token saved: ${mintAddress},${decimals}`);
    bot.sendMessage(chatId, `✅ Token added!\nMint: \`${mintAddress}\`\nDecimals: ${decimals}`, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error(err);
    bot.sendMessage(chatId, '❌ Failed to add token.');
  }
});

bot.onText(/\/remove (.+)/, (msg, match) => {
  const chatId = msg.chat.id;
  const mint = match[1].trim();

  try {
    const lines = fs.readFileSync(config.tokensFile, 'utf-8').split('\n').filter(Boolean);
    const filtered = lines.filter(l => !l.startsWith(mint));
    fs.writeFileSync(config.tokensFile, filtered.join('\n') + '\n');
    bot.sendMessage(chatId, `✅ Token removed: \`${mint}\``, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error(err);
    bot.sendMessage(chatId, '❌ Failed to remove token.');
  }
});

connection.onLogs('all', async logInfo => {
  const tracked = loadTrackedTokens();
  const logs = logInfo.logs.join('\n');
  const match = tracked.find(t => logs.includes(t.mint));

  if (!match) return;

  const { signature } = logInfo;
  console.log(`🌟 Log match for ${match.mint} at TX ${signature}`);

  try {
    const tx = await connection.getParsedTransaction(signature, 'confirmed');
    if (!tx) return;

    const instructions = tx.meta?.innerInstructions || [];
    let amount = 0;

    for (const group of instructions) {
      for (const inner of group.instructions) {
        if (
          inner.parsed?.type === 'transfer' &&
          inner.parsed.info?.mint === match.mint
        ) {
          amount += parseInt(inner.parsed.info.amount);
        }
      }
    }

    const formatted = amount / Math.pow(10, match.decimals);
    let price = 0;

    try {
      const res = await fetch(`https://api.dexscreener.com/latest/dex/pairs/solana/${match.mint}`);
      const data = await res.json();
      price = parseFloat(data?.pair?.priceUsd || 0);
    } catch (err) {
      console.warn('❌ Dex price error:', err);
    }

    const value = price * formatted;
    const buyer = tx.transaction.message.accountKeys.find(k => k.signer)?.pubkey?.toString() || 'unknown';
    const slot = tx.slot;

    const message = `💰 *New Buy Detected!*\nToken: [${match.mint}](https://solscan.io/token/${match.mint})\nBuyer: [${buyer}](https://solscan.io/account/${buyer})\nSlot: ${slot}\nAmount: ${formatted.toFixed(2)} tokens\n💵 ~$${value.toFixed(2)} USD\n[View on Solscan](https://solscan.io/tx/${signature})`;

    bot.sendMessage(config.chatId, message, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error('❌ Error processing buy log:', err);
  }
});
