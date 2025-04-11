const { Connection, PublicKey } = require('@solana/web3.js');
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');
const config = require('./config.json');

const connection = new Connection(config.rpcUrl);
const bot = new TelegramBot(config.botToken, { polling: false });

// Replace with the token you want to track
const TOKEN_MINT = 'TOKEN_MINT_ADDRESS_HERE';

// Replace with the Jupiter or Raydium market address or pool ID if needed
const MARKET_PROGRAM_ID = new PublicKey('JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB');

// Subscribe to all logs on the chain, filtering later
connection.onLogs('all', async (logInfo) => {
  try {
    const { signature, logs } = logInfo;
    const logText = logs.join('\n');

    // Filter: Make sure this is a Jupiter or Raydium log, and it includes the token mint
    if (!logText.includes(TOKEN_MINT)) return;

    console.log(`Transaction detected for token ${TOKEN_MINT} - Signature: ${signature}`);

    const txDetails = await connection.getParsedTransaction(signature, 'confirmed');
    if (!txDetails) return;

    const buyer = txDetails.transaction.message.accountKeys.find(k => k.signer).pubkey.toString();
    const slot = txDetails.slot;

    const msg = `💰 *New Buy Detected!*
Token: [${TOKEN_MINT}](https://solscan.io/token/${TOKEN_MINT})
Buyer: [${buyer}](https://solscan.io/account/${buyer})
Slot: ${slot}
[View on Solscan](https://solscan.io/tx/${signature})`;

    bot.sendMessage(config.chatId, msg, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error('Error in buybot:', err);
  }
});
