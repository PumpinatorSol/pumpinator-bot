require('dotenv').config();

const { Connection, PublicKey } = require('@solana/web3.js');
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');
const fs = require('fs');

const config = {
  botToken: process.env.BOT_TOKEN,
  chatId: process.env.TELEGRAM_CHAT_ID,
  adminId: process.env.ADMIN_ID,
  rpcUrl: process.env.SOLANA_RPC_URL,
  tokensFile: process.env.TOKENS_FILE || 'added_tokens.txt'
};

const connection = new Connection(config.rpcUrl, 'confirmed');
const bot = new TelegramBot(config.botToken, { polling: true });

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

    // Ensure file exists
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

connection.onLogs('all', async (logInfo) => {
  const trackedTokens = loadTrackedTokens();

  const { signature, logs } = logInfo;
  const logText = logs.join('\n');

  const tokenMatch = trackedTokens.find(token => logText.includes(token.mint));
  if (!tokenMatch) return;

  const { mint, decimals } = tokenMatch;
  console.log(`🎯 Buy detected for ${mint} — TX: ${signature}`);

  try {
    const txDetails = await connection.getParsedTransaction(signature, 'confirmed');
    if (!txDetails) return;

    const buyer = txDetails.transaction.message.accountKeys.find(k => k.signer)?.pubkey.toString() || 'Unknown';
    const slot = txDetails.slot;

    let tokenAmount = 0;
    const innerInstructions = txDetails.meta.innerInstructions || [];

    innerInstructions.forEach(ix => {
      ix.instructions.forEach(inner => {
        if (inner.parsed?.info?.mint === mint && inner.parsed?.type === 'transfer') {
          tokenAmount += parseInt(inner.parsed.info.amount);
        }
      });
    });

    const tokenAmountFormatted = tokenAmount / Math.pow(10, decimals);

    // Get USD price
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
