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
pip install fastapi uvicorn

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
