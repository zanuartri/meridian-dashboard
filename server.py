"""
Meridian Dashboard API — Charon-inspired dark terminal UI
Read-only visualization of /root/meridian/ state files
"""
import json, os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Meridian Dashboard")
MERIDIAN = Path("/root/meridian")
WALLET = "DR2UaR2nhR1Wc7QezUyvDH655nTDCquvMijs2pDaY8Sy"

def load(fn):
    fp = MERIDIAN / fn
    if not fp.exists(): return {}
    try:
        with open(fp) as f: return json.load(f)
    except: return {}

def fmt(n, d=2):
    if n is None or n != n: return None
    return round(float(n), d)

@app.get("/api/dashboard")
async def dashboard():
    state = load("state.json")
    lessons = load("lessons.json")
    config = load("user-config.json")
    pool_mem = load("pool-memory.json")

    perf = lessons.get("performance", []) if isinstance(lessons, dict) else []
    closed = [p for p in perf if isinstance(p, dict)]

    # Wallet
    
    # Active positions
    positions = state.get("positions", {})
    active = []
    total_unrealized = 0
    total_unclaimed_fees = 0
    for addr, pos in positions.items():
        if not isinstance(pos, dict) or pos.get("closed"): continue
        br = pos.get("bin_range", {}) or {}
        # Unclaimed fees from management cycle snapshot
        unclaimed = pos.get("last_unclaimed_fees_usd", 0) or 0
        total_unclaimed_fees += unclaimed
        # Unrealized PnL from management cycle snapshot
        unrealized = pos.get("last_pnl_usd", 0) or 0
        total_unrealized += unrealized
        active.append({
            "address": addr,
            "pair": pos.get("pool_name") or pos.get("base_mint", "?")[:8],
            "pool": pos.get("pool") or "?",
            "strategy": pos.get("strategy") or config.get("strategy", "?"),
            "amount_sol": fmt(pos.get("amount_sol")),
            "bin_step": pos.get("bin_step"),
            "bins_below": br.get("bins_below", 0),
            "bins_above": br.get("bins_above", 0),
            "active_bin": pos.get("active_bin_at_deploy"),
            "organic_score": pos.get("organic_score"),
            "entry_mcap": fmt(pos.get("entry_mcap")),
            "deployed_at": pos.get("deployed_at"),
            "note": (pos.get("notes") or [""])[0] if pos.get("notes") else "",
            "rebalance_count": pos.get("rebalance_count", 0),
            "fees_claimed_usd": fmt(pos.get("total_fees_claimed_usd", 0)),
            "out_of_range_since": pos.get("out_of_range_since"),
            "trailing_active": pos.get("trailing_active", False),
            "peak_pnl_pct": fmt(pos.get("peak_pnl_pct")),
            "unrealized_pnl_usd": fmt(pos.get("last_pnl_usd")),
            "unrealized_pnl_pct": fmt(pos.get("last_pnl_pct")),
            "unclaimed_fees_usd": fmt(pos.get("last_unclaimed_fees_usd")),
            "total_value_usd": fmt(pos.get("last_total_value_usd")),
            "last_pnl_at": pos.get("last_pnl_at"),
        })

    # Closed stats
    total_pnl = sum(p.get("pnl_usd", 0) for p in closed if isinstance(p, dict))
    wins = [p for p in closed if (p.get("pnl_pct", 0) or 0) > 0]
    losses = [p for p in closed if (p.get("pnl_pct", 0) or 0) <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win = sum(p.get("pnl_pct", 0) for p in wins) / len(wins) if wins else 0
    avg_loss = sum(p.get("pnl_pct", 0) for p in losses) / len(losses) if losses else 0
    total_fees = sum(p.get("fees_earned_usd", 0) for p in closed if isinstance(p, dict))
    hold_times = [p.get("minutes_held", 0) for p in closed if p.get("minutes_held")]
    avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0

    # TP/SL stats
    tp_count = sum(1 for p in closed if "take profit" in (p.get("close_reason") or "").lower() or "trailing" in (p.get("close_reason") or "").lower())
    sl_count = sum(1 for p in closed if "stop loss" in (p.get("close_reason") or "").lower())
    oor_count = sum(1 for p in closed if "rule 3" in (p.get("close_reason") or "").lower() or "rule 4" in (p.get("close_reason") or "").lower() or "pumped" in (p.get("close_reason") or "").lower())

    # Daily PnL for chart
    daily = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = ts[:10]
        if day not in daily:
            daily[day] = {"date": day, "pnl_usd": 0, "trades": 0, "wins": 0, "fees": 0}
        daily[day]["pnl_usd"] += p.get("pnl_usd", 0) or 0
        daily[day]["trades"] += 1
        daily[day]["fees"] += p.get("fees_earned_usd", 0) or 0
        if (p.get("pnl_pct", 0) or 0) > 0: daily[day]["wins"] += 1
    days = sorted(daily.values(), key=lambda x: x["date"])
    cum = 0
    for d in days:
        cum += d["pnl_usd"]
        d["cumulative"] = round(cum, 4)

    # History (recent)
    history = sorted(closed, key=lambda x: x.get("recorded_at", ""), reverse=True)[:50]

    # Config — pass full config + computed fields
    config_summary = dict(config)
    config_summary["solMode"] = config.get("solMode", False)
    config_summary["strategyDetail"] = "Single-side SOL" if config.get("strategy") == "spot" else "Dual-side"

    return {
        "wallet": WALLET[:6] + "..." + WALLET[-4:],
        "wallet_full": WALLET,
        "positions": active,
        "position_count": len(active),
        "max_positions": config.get("maxPositions", 2),
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": fmt(win_rate, 1),
        "avg_win": fmt(avg_win),
        "avg_loss": fmt(avg_loss),
        "net_pnl_usd": fmt(total_pnl),
        "unrealized_pnl_usd": fmt(total_unrealized),
        "unclaimed_fees_usd": fmt(total_unclaimed_fees),
        "total_fees": fmt(total_fees, 4),
        "avg_hold_min": round(avg_hold),
        "tp_count": tp_count,
        "sl_count": sl_count,
        "oor_count": oor_count,
        "daily": days,
        "history": history,
        "config": config_summary,
    }

@app.get("/api/candidates")
async def candidates():
    decision_log = load("decision-log.json")
    decisions = decision_log.get("decisions", []) if isinstance(decision_log, dict) else []
    pool_mem = load("pool-memory.json")

    # Sort by timestamp descending, return last 50
    recent = sorted(decisions, key=lambda x: x.get("ts", ""), reverse=True)[:50]

    # Enrich with pool memory data
    for dec in recent:
        pool_addr = dec.get("pool")
        if pool_addr and pool_addr in pool_mem:
            pm = pool_mem[pool_addr]
            dec["pool_history"] = {
                "total_deploys": pm.get("total_deploys", 0),
                "avg_pnl_pct": fmt(pm.get("avg_pnl_pct")),
                "win_rate": fmt(pm.get("win_rate")),
                "last_outcome": pm.get("last_outcome"),
            }
        # Format metrics if present
        metrics = dec.get("metrics", {})
        if metrics:
            dec["formatted_metrics"] = {
                "mcap": f"${metrics.get('mcap', 0)/1000:.0f}K" if metrics.get("mcap") else None,
                "tvl": f"${metrics.get('tvl', 0)/1000:.0f}K" if metrics.get("tvl") else None,
                "volume": f"${metrics.get('volume', 0):.0f}" if metrics.get("volume") else None,
                "organic": metrics.get("organic_score"),
                "holders": metrics.get("holder_count"),
                "fee_tvl": f"{metrics.get('fee_tvl_ratio', 0)*100:.2f}%" if metrics.get("fee_tvl_ratio") else None,
            }

    # Stats
    deploy_count = sum(1 for d in decisions if d.get("type") == "deploy")
    no_deploy_count = sum(1 for d in decisions if d.get("type") == "no_deploy")
    skip_count = sum(1 for d in decisions if d.get("type") == "skip")
    close_count = sum(1 for d in decisions if d.get("type") == "close")

    return {
        "decisions": recent,
        "stats": {
            "total": len(decisions),
            "deploy": deploy_count,
            "no_deploy": no_deploy_count,
            "skip": skip_count,
            "close": close_count,
        }
    }

@app.get("/api/learning")
async def learning():
    lessons_data = load("lessons.json")
    signal_weights = load("signal-weights.json")
    pool_mem = load("pool-memory.json")

    lessons = lessons_data.get("lessons", []) if isinstance(lessons_data, dict) else []
    perf = lessons_data.get("performance", []) if isinstance(lessons_data, dict) else []

    # Sort lessons by created_at desc
    lessons_sorted = sorted(lessons, key=lambda x: x.get("created_at", ""), reverse=True)[:30]

    # Pool memory stats
    pool_stats = []
    for addr, pm in pool_mem.items():
        if not isinstance(pm, dict): continue
        pool_stats.append({
            "address": addr,
            "name": pm.get("name", "?"),
            "total_deploys": pm.get("total_deploys", 0),
            "avg_pnl_pct": fmt(pm.get("avg_pnl_pct")),
            "win_rate": fmt(pm.get("win_rate")),
            "adjusted_win_rate": fmt(pm.get("adjusted_win_rate")),
            "last_outcome": pm.get("last_outcome"),
            "last_deployed": pm.get("last_deployed_at"),
            "cooldown_until": pm.get("base_mint_cooldown_until"),
            "cooldown_reason": pm.get("base_mint_cooldown_reason"),
        })
    pool_stats.sort(key=lambda x: x.get("total_deploys", 0), reverse=True)

    # Performance breakdown
    total_pnl = sum(p.get("pnl_usd", 0) for p in perf if isinstance(p, dict))
    avg_pnl_pct = sum(p.get("pnl_pct", 0) for p in perf) / len(perf) if perf else 0
    avg_range_eff = sum(p.get("range_efficiency", 0) for p in perf if p.get("range_efficiency")) / max(1, len([p for p in perf if p.get("range_efficiency")]))

    return {
        "lessons": lessons_sorted,
        "signal_weights": signal_weights,
        "pool_stats": pool_stats,
        "performance_summary": {
            "total_trades": len(perf),
            "total_pnl_usd": fmt(total_pnl),
            "avg_pnl_pct": fmt(avg_pnl_pct),
            "avg_range_efficiency": fmt(avg_range_eff),
        }
    }

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((Path(__file__).parent / "index.html").read_text())

@app.get("/api/calendar")
async def calendar():
    state = load("state.json")
    lessons = load("lessons.json")
    config = load("user-config.json")

    perf = lessons.get("performance", []) if isinstance(lessons, dict) else []
    closed = [p for p in perf if isinstance(p, dict)]

    # Build daily data
    daily = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = ts[:10]
        if day not in daily:
            daily[day] = {"date": day, "pnl_usd": 0, "trades": 0, "wins": 0, "fees": 0, "positions": 0}
        daily[day]["pnl_usd"] += p.get("pnl_usd", 0) or 0
        daily[day]["trades"] += 1
        daily[day]["fees"] += p.get("fees_earned_usd", 0) or 0
        if (p.get("pnl_pct", 0) or 0) > 0: daily[day]["wins"] += 1

    # Count positions opened per day (from closed trades = each closed = 1 opened)
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = ts[:10]
        if day in daily:
            daily[day]["positions"] = daily[day].get("positions", 0) + 1

    # Build position details per day
    by_day = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = ts[:10]
        if day not in by_day: by_day[day] = []
        pnl = p.get("pnl_pct", 0) or 0
        by_day[day].append({
            "pool": p.get("pool_name", "?"),
            "pnl_pct": round(pnl, 2),
            "pnl_usd": round(p.get("pnl_usd", 0) or 0, 4),
            "fees": round(p.get("fees_earned_usd", 0) or 0, 4),
            "held": p.get("minutes_held", 0),
            "reason": (p.get("close_reason") or "")[:60],
            "strategy": p.get("strategy", "?"),
        })

    return {"daily": list(daily.values()), "by_day": by_day}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
