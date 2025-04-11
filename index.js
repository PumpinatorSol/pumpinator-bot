require('dotenv').config();

const express = require('express');
const { Connection, PublicKey } = require('@solana/web3.js');
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');
const fs = require('fs');
const path = require('path');

// ✅ Use /tmp directory for safe write access on Render
const tokenFilePath = path.join('/tmp', 'added_tokens.txt');

const config = {
  botToken: process.env.BOT_TOKEN,
  chatId: process.env.TELEGRAM_CHAT_ID,
  adminId: process.env.ADMIN_ID,
  rpcUrl: process.env.SOLANA_RPC_URL,
  tokensFile: tokenFilePath,
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

// --- Token Add Command ---
bot.onText(/\/add (.+)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const mintAddress = match[1].trim();

  try {
    const mintPubkey = new PublicKey(mintAddress);
    const mintAccountInfo = await connection.getParsedAccountInfo(mintPubkey);

    if (!mintAccountInfo || !mintAccountInfo.value) {
      return bot.sendMessage(chatId, '❌ Invalid token mint or not found.');
    }

    const decimals = mintAccountInfo.value.data.parsed.info.decimals;

    if (!fs.existsSync(config.tokensFile)) {
      fs.writeFileSync(config.tokensFile, '');
    }

    const existing = fs.readFileSync(config.tokensFile, 'utf-8').split('\n').filter(Boolean);
    if (existing.find(line => line.startsWith(mintAddress))) {
      return bot.sendMessage(chatId, `⚠️ Token already tracked.`);
    }

    const tokenLine = `${mintAddress},${decimals}\n`;
    fs.appendFileSync(config.tokensFile, tokenLine);

    console.log(`✅ Token saved to ${config.tokensFile}: ${tokenLine.trim()}`);
    console.log('📦 Updated tracked tokens list:\n', fs.readFileSync(config.tokensFile, 'utf-8'));

    bot.sendMessage(chatId, `✅ Token added!\nMint: \`${mintAddress}\`\nDecimals: ${decimals}`, {
      parse_mode: 'Markdown'
    });

  } catch (err) {
    console.error('❌ Error in /add:', err);
    bot.sendMessage(chatId, '❌ Failed to fetch token info. Make sure the mint is valid.');
  }
});

// --- Token Remove Command ---
bot.onText(/\/remove (.+)/, (msg, match) => {
  const chatId = msg.chat.id;
  const mintAddress = match[1].trim();

  try {
    const tokens = fs.readFileSync(config.tokensFile, 'utf-8').split('\n').filter(Boolean);
    const updated = tokens.filter(line => !line.startsWith(mintAddress));

    if (tokens.length === updated.length) {
      return bot.sendMessage(chatId, '⚠️ Token not found in tracked list.');
    }

    fs.writeFileSync(config.tokensFile, updated.join('\n') + '\n');
    bot.sendMessage(chatId, `✅ Token removed: \`${mintAddress}\``, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error('❌ Error in /remove:', err);
    bot.sendMessage(chatId, '❌ Failed to update token list.');
  }
});

// --- Load token list on start ---
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

// --- Log Listener ---
console.log('🔍 Starting transaction log listener...');
connection.onLogs('all', async (logInfo) => {
  const trackedTokens = loadTrackedTokens();
  const { signature, logs } = logInfo;
  const logText = logs.join('\n');

  console.log(`📱 Received TX Signature: ${signature}`);

  const tokenMatch = trackedTokens.find(token => logText.includes(token.mint));
  if (!tokenMatch) return;

  const { mint, decimals } = tokenMatch;
  console.log(`🎯 Log match for ${mint} — checking TX: ${signature}`);

  try {
    const txDetails = await connection.getParsedTransaction(signature, 'confirmed');
    if (!txDetails) return;

    const buyer = txDetails.transaction.message.accountKeys.find(k => k.signer)?.pubkey.toString() || 'Unknown';
    const slot = txDetails.slot;

    let tokenAmount = 0;
    const innerInstructions = txDetails.meta?.innerInstructions || [];

    // ✅ Improved transfer detection logic
    innerInstructions.forEach(ix => {
      ix.instructions.forEach(inner => {
        const parsed = inner.parsed;
        if (!parsed || !parsed.info) return;

        const info = parsed.info;
        const isRelevantTransfer =
          parsed.type === 'transferChecked' ||
          parsed.type === 'transfer';

        const involvedMint =
          info.mint ||
          info.sourceMint ||
          info.destinationMint;

        if (isRelevantTransfer && involvedMint === mint) {
          tokenAmount += parseInt(info.amount || '0');
        }
      });
    });

    if (tokenAmount === 0) return;

    const tokenAmountFormatted = tokenAmount / Math.pow(10, decimals);

    let usdPrice = 0;
    let usdValue = 0;
    try {
      const dexRes = await fetch(`https://api.dexscreener.com/latest/dex/pairs/solana/${mint}`);
      const dexData = await dexRes.json();

      if (dexData.pair && dexData.pair.priceUsd) {
        usdPrice = parseFloat(dexData.pair.priceUsd);
        usdValue = tokenAmountFormatted * usdPrice;
      }
    } catch (e) {
      console.warn('❌ DexScreener price fetch failed.');
    }

    const msg = `💰 *New Buy Detected!*\nToken: [${mint}](https://solscan.io/token/${mint})\nBuyer: [${buyer}](https://solscan.io/account/${buyer})\nSlot: ${slot}\nAmount: ${tokenAmountFormatted.toFixed(2)} tokens\n💵 Value: ~$${usdValue.toFixed(2)} USD\n[View on Solscan](https://solscan.io/tx/${signature})`;

    bot.sendMessage(config.chatId, msg, { parse_mode: 'Markdown' });
  } catch (err) {
    console.error('❌ Error parsing transaction:', err);
  }
});
