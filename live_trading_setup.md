# Live Trading Setup Guide ($100 Account)

> This guide is for the retired Coinbase crypto bots (`bot.py`). For the stock
> bots on Alpaca, including the broker-paper rehearsal, see
> [`live_trading_stocks.md`](live_trading_stocks.md).

To start trading live with a small amount (like $100), follow these step-by-step instructions.

---

## 1. Fund Your Coinbase Account
* Log in to your retail **Coinbase** account.
* Ensure you have at least **$100 USD** available in your cash balance.

---

## 2. Obtain CDP API Keys
1. Go to the [Coinbase Developer Portal](https://portal.cdp.coinbase.com/).
2. Create a new set of **CDP API Keys** (Advanced Trade permissions).
3. Copy the **API Key Name** (formatted as `organizations/{org_id}/apiKeys/{key_id}`).
4. Download or copy the **Private Key** (PEM format).

---

## 3. Configure Your `.env` File
Open the local [`.env`](file:///home/leeunks/coinbase-trading-bot/.env) file in your editor and update the following settings:

```env
# Credentials
COINBASE_API_KEY=your_api_key_name_here
COINBASE_API_SECRET="your_full_pem_private_key_here"

# Live Trading Configuration
DRY_RUN=False

# Trade Amount (leave headroom for fees: 0.60% maker, 1.20% taker per side)
TRADE_AMOUNT_USD=95.0
```

> [!WARNING]
> Keep `TRADE_AMOUNT_USD` slightly below your total cash balance (e.g. `$95.00` instead of exactly `$100.00`). If you set it to exactly `$100.00`, the order will fail if you do not have extra cash to cover Coinbase's execution fee (0.60% maker, or 1.20% if the order fills as taker).

---

## 4. Run Persistently in the Background (PM2)
Since you already have **PM2** installed on this system, you can run the bot as a background daemon so it checks the market and trades automatically 24/7.

Run the following commands in your terminal inside the `coinbase-trading-bot` directory:

```bash
# 1. Start the bot under PM2 using the virtual environment python interpreter
pm2 start bot.py --name "coinbase-bot" --interpreter .venv/bin/python

# 2. Save the process list so PM2 remembers it
pm2 save
```

---

## 5. Monitoring & Maintenance
You can check on your bot at any time using the following terminal commands:

* **Check status**:
  ```bash
  pm2 status
  ```
* **View real-time logs**:
  ```bash
  pm2 logs coinbase-bot
  ```
* **View bot log file**:
  ```bash
  tail -f logs/bot.log
  ```
* **Stop the bot**:
  ```bash
  pm2 stop coinbase-bot
  ```

---

## 6. Manual Position Exit & Reset (`manual_sell.py`)
If you need to close out a position manually, do not just stop the bot. Stopping the bot leaves the asset in your account balance (live) or leaves the state file set to `LONG` (dry run).

To cleanly execute a sell order (both live or simulated) and reset the bot state:
1. Run the manual closeout script:
   ```bash
   .venv/bin/python manual_sell.py <coin_symbol>
   ```
   *Example:* `.venv/bin/python manual_sell.py btc`
2. Confirm the prompt. The script will fetch current prices, place the market sell order (if live), update `trades.csv` and `completed_trades.csv`, send an email alert, and reset the local position tracking to `NONE`.
3. If you want to keep the bot from entering a new trade immediately after closing, stop the PM2 bot process first:
   ```bash
   pm2 stop btc-bot
   .venv/bin/python manual_sell.py btc --yes
   ```
