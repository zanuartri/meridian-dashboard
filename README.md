# Meridian Dashboard

Self-hosted monitoring dashboard for [Meridian](https://github.com/nicegoodboy/meridian) — an autonomous DLMM liquidity provider agent for Meteora on Solana.

## Features

- **Overview** — stat cards, performance trend, daily PnL, win/loss, fee accumulation
- **Positions** — active positions with status (HOLDING/OOR), PnL, fees
- **Candidates** — screening decisions table with pagination
- **Calendar** — monthly view with daily PnL, click to see positions per day
- **Learning** — Darwin lessons + pool memory stats
- **Settings** — full config view in 3-column grid
- **Mobile** — responsive with bottom nav (icon-only), sticky header
- **Auto-refresh** every 30 seconds

## Quick Start

```bash
# Clone
git clone https://github.com/zanuartri/meridian-dashboard.git
cd meridian-dashboard

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn yfinance

# Configure (optional — defaults to /root/meridian)
export MERIDIAN_PATH=/path/to/your/meridian
export MERIDIAN_WALLET=YourSolanaWalletAddress

# Run
python server.py
# → http://localhost:8888
```

## How It Works

The dashboard reads Meridian's state files (read-only, no API keys needed):

| File | Data |
|------|------|
| `state.json` | Active positions, PnL, fees |
| `lessons.json` | Closed trades, performance history |
| `user-config.json` | Runtime configuration |
| `pool-memory.json` | Pool deploy history |
| `signal-weights.json` | Darwin signal weights |
| `decision-log.json` | Screening decisions |

## Portfolio & Deposit Tracking

The dashboard tracks your total portfolio value in both USD and SOL, including:
- Live wallet SOL balance
- Active position values
- SOL rent fees
- **Deposit history** — incoming SOL transfers from your wallet to Meridian

### Prerequisites

| Requirement | Why | Free Tier |
|-------------|-----|-----------|
| **Alchemy API Key** | Fetch wallet transaction history (deposits) | 100M compute units/month — more than enough |
| **yfinance** | Historical SOL prices at deposit time (hourly precision) | Unlimited |

#### Get an Alchemy API Key

1. Go to [alchemy.com](https://www.alchemy.com/) → Sign up
2. Create an app → Select **Solana** as the chain
3. Copy the API key
4. Add it to Meridian's `.env`:
   ```
   ALCHEMY_API_KEY=your_key_here
   ```

> **Helius fallback:** If you have a Helius key in `.env`, the dashboard can use it as a fallback for RPC calls (balance + deposits). But Alchemy is preferred for better rate limits.

### Enable Portfolio Features

Edit `dashboard-config.json` in your Meridian directory:

```json
{
  "wallet_rpc_enabled": true,
  "wallet_rpc_interval_seconds": 60
}
```

Or use the Settings tab in the dashboard UI to toggle it on.

### How Deposit Backfill Works

On first run (or when `deposits.json` is empty/deleted), the dashboard:

1. **Fetches all transaction signatures** from your wallet via Alchemy RPC
2. **Filters incoming SOL transfers** — excludes Meteora/Jupiter/Raydium program transactions
3. **Matches each deposit to an hourly SOL price** via yfinance (1 call per unique date)
4. **Caches results** in `deposits.json` (in Meridian directory)

Subsequent runs use the cache and only fetch new transactions since the last known signature. Cache refreshes at most once per hour.

### Backfill Manually

If you need to re-fetch deposit history:

```bash
# Delete the cache → next dashboard request will re-fetch
rm /path/to/meridian/deposits.json

# Or clear just the cache entry to force refresh
# (deposits.json last_fetch resets to 0)
```

### Correcting Deposit Prices

The dashboard uses yfinance 1h Close prices (hourly precision). If a price doesn't match your actual deposit time:

1. Edit `deposits.json`
2. Update the `sol_price` field for the relevant deposit
3. The portfolio PnL recalculates automatically

Example deposit entry:
```json
{
  "sig": "5Kt...abc",
  "sol_amount": 0.5,
  "sol_price": 73.69,
  "usd_value": 36.85,
  "date": "2025-06-16T14:30:00Z",
  "hour": 14
}
```

### Deposit Detection Rules

A transaction is detected as a deposit when:
- It's a **transfer** instruction to the wallet address
- It's **NOT** from one of these programs:
  - 5Zz1G... (Meteora DLMM)
  - LBUZJ... (Meteora DLMM v2)
  - obriQ... (Meteora)
  - whirL... (Whirlpool)
  - CAMMC... (Meteora AMM)
  - JUP6L... (Jupiter)
  - 675kP... (Raydium)
- SOL amount > 0
- Deposits from **before Meridian start date** are excluded

### Portfolio PnL Formula

```
Current Total = (wallet_sol + positions_sol + rent_sol) × current_sol_price
Deposited Value = deposited_sol × avg_deposit_price
Portfolio PnL = Current Total - Deposited Value
```

### SOL Labels

All amounts show both USD and SOL values:
- Stats cards: `$255 now / $258 in` (USD)
- Position PnL: `+$4.50 +0.0664 SOL`
- Portfolio modal (ⓘ button): full breakdown with wallet, positions, rent, deposits

## PM2 (Production)

```bash
pm2 start server.py --name meridian-dashboard --interpreter /path/to/.venv/bin/python
pm2 save
```

## Stack

- **Backend:** FastAPI + Python 3.11
- **Frontend:** Vanilla JS + Chart.js
- **Font:** JetBrains Mono + Inter
- **Theme:** Charon-inspired dark terminal UI

## License

MIT
