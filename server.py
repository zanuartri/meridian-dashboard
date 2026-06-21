"""
Meridian Dashboard API — Charon-inspired dark terminal UI
Read-only visualization of /root/meridian/ state files
"""
import json, os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Meridian Dashboard")
MERIDIAN = Path(os.environ.get("MERIDIAN_PATH", "/root/meridian"))
WALLET = os.environ.get("MERIDIAN_WALLET", "")
def load(fn):
    fp = MERIDIAN / fn
    if not fp.exists(): return {}
    try:
        with open(fp) as f: return json.load(f)
    except: return {}

def active_cooldowns(pool_mem):
    """Dev-mint cooldowns from pool memory that are still in effect."""
    now = datetime.now(timezone.utc)
    out = []
    for addr, pm in pool_mem.items():
        if not isinstance(pm, dict): continue
        cu = pm.get("base_mint_cooldown_until")
        if not cu: continue
        try:
            until = datetime.fromisoformat(cu.replace("Z", "+00:00"))
        except: continue
        if until <= now: continue
        out.append({
            "name": pm.get("name", "?"),
            "until": cu,
            "hours_left": round((until - now).total_seconds() / 3600, 1),
            "reason": pm.get("base_mint_cooldown_reason", ""),
        })
    out.sort(key=lambda x: x["until"])
    return out

def blocklist_entries():
    bl = load("dev-blocklist.json")
    if not isinstance(bl, dict): return []
    out = []
    for mint, v in bl.items():
        v = v if isinstance(v, dict) else {}
        out.append({
            "mint": mint,
            "label": v.get("label", ""),
            "reason": v.get("reason", ""),
            "added_at": v.get("added_at", ""),
        })
    out.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return out

def latest_wallet_balance():
    """Read the most recent get_wallet_balance result from Meridian's action logs.
    Meridian doesn't persist balance to state — it logs each tool call to
    logs/actions-YYYY-MM-DD.jsonl. We scan newest files first for the last success."""
    logdir = MERIDIAN / "logs"
    if not logdir.exists(): return None
    files = sorted(logdir.glob("actions-*.jsonl"), reverse=True)
    for fp in files:
        try:
            lines = fp.read_text().splitlines()
        except: continue
        for line in reversed(lines):
            line = line.strip()
            if not line or '"get_wallet_balance"' not in line: continue
            try:
                rec = json.loads(line)
            except: continue
            if rec.get("tool") != "get_wallet_balance" or not rec.get("success"): continue
            res = rec.get("result", {}) or {}
            res["as_of"] = rec.get("timestamp")
            return res
    return None

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

    # Wallet — auto-detect from env or state.json owner
    wallet = WALLET
    if not wallet:
        wallet = state.get("owner", "") or state.get("wallet", "")
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

    # Boot time for accurate uptime
    boot_time = None
    boot_file = MERIDIAN / "boot_time"
    if boot_file.exists():
        try:
            boot_time = boot_file.read_text().strip()
        except: pass

    # Agent liveness — derive from state.json freshness
    last_updated = state.get("lastUpdated")
    stale_min = None
    if last_updated:
        try:
            lu = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            stale_min = (datetime.now(timezone.utc) - lu).total_seconds() / 60
        except: pass

    # Recent events feed (deploy/close) from state
    raw_events = state.get("recentEvents", []) if isinstance(state, dict) else []
    recent_events = sorted(
        [e for e in raw_events if isinstance(e, dict)],
        key=lambda x: x.get("ts", ""), reverse=True
    )[:15]

    # Wallet balance (from logs — Meridian doesn't persist it)
    wb = latest_wallet_balance()
    wallet_balance = None
    if wb:
        wallet_balance = {
            "sol": fmt(wb.get("sol"), 4),
            "sol_usd": fmt(wb.get("sol_usd")),
            "sol_price": fmt(wb.get("sol_price")),
            "usdc": fmt(wb.get("usdc")),
            "total_usd": fmt(wb.get("total_usd")),
            "tokens": [
                {"symbol": t.get("symbol", "?"), "balance": fmt(t.get("balance"), 4), "usd": fmt(t.get("usd"))}
                for t in (wb.get("tokens") or []) if isinstance(t, dict)
            ],
            "as_of": wb.get("as_of"),
        }
        if not wallet:
            wallet = wb.get("wallet", "") or wallet

    # Total equity = wallet total + open position value
    positions_value = sum((p.get("total_value_usd") or 0) for p in active)
    total_equity = None
    if wallet_balance and wallet_balance.get("total_usd") is not None:
        total_equity = fmt(wallet_balance["total_usd"] + positions_value)

    # Active dev-mint cooldowns + blocklist
    cooldowns = active_cooldowns(pool_mem)
    blocklist_count = len(blocklist_entries())

    return {
        "wallet": (wallet[:6] + "..." + wallet[-4:]) if wallet else "—",
        "wallet_full": wallet,
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
        "boot_time": boot_time,
        "last_updated": last_updated,
        "stale_min": fmt(stale_min, 1),
        "recent_events": recent_events,
        "wallet_balance": wallet_balance,
        "positions_value_usd": fmt(positions_value),
        "total_equity_usd": total_equity,
        "cooldowns": cooldowns,
        "blocklist_count": blocklist_count,
        "config": config_summary,
    }

@app.get("/api/wallet")
async def wallet_endpoint():
    wb = latest_wallet_balance()
    if not wb:
        return {"available": False}
    return {"available": True, **wb}

@app.get("/api/candidates")
async def candidates():
    import re
    decision_log = load("decision-log.json")
    decisions = decision_log.get("decisions", []) if isinstance(decision_log, dict) else []
    pool_mem = load("pool-memory.json")

    # Sort by timestamp descending — return ALL, frontend handles pagination
    recent = sorted(decisions, key=lambda x: x.get("ts", ""), reverse=True)

    # Enrich with pool memory data + compute display fields
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

        tp = dec.get("type", "skip")
        metrics = dec.get("metrics", {})
        rejected = dec.get("rejected", [])

        # Compute pool_display
        pool_display = dec.get("pool_name") or ""
        if not pool_display and rejected:
            # Extract first pool name from rejected list
            for r in rejected:
                m = re.match(r"(\S+-(?:SOL|USDC))", str(r))
                if m:
                    pool_display = m.group(1)
                    break
        if not pool_display and dec.get("reason"):
            m = re.match(r"-?\s*(\S+-(?:SOL|USDC))", str(dec["reason"]))
            if m:
                pool_display = m.group(1)
        dec["pool_display"] = pool_display or "—"

        # Compute detail_display per type
        if tp == "deploy" and metrics:
            amt = metrics.get("amount_sol", "")
            strat = metrics.get("strategy", "")
            abin = metrics.get("active_bin")
            mn = metrics.get("min_bin")
            mx = metrics.get("max_bin")
            parts = []
            if amt: parts.append(f"{amt} SOL")
            if strat: parts.append(strat)
            if abin is not None: parts.append(f"bin#{abin}")
            if mn is not None and mx is not None: parts.append(f"range {mn}→{mx}")
            dec["detail_display"] = " · ".join(parts) if parts else dec.get("summary", "—")
        elif tp == "close" and metrics:
            pnl = metrics.get("pnl_pct")
            pnl_usd = metrics.get("pnl_usd")
            fees = metrics.get("fees_usd")
            held = metrics.get("minutes_held")
            parts = []
            if pnl is not None:
                parts.append(f"{'+' if pnl >= 0 else ''}{pnl:.1f}%")
            if pnl_usd is not None:
                parts.append(f"${pnl_usd:+.4f}")
            if fees is not None:
                parts.append(f"${fees:.4f} fees")
            if held:
                parts.append(f"{held}m")
            dec["detail_display"] = " · ".join(parts) if parts else dec.get("summary", "—")
        elif tp == "no_deploy" and rejected:
            # Show rejection reasons
            reasons = [str(r)[:80] for r in rejected[:3]]
            extra = len(rejected) - 3
            display = " | ".join(reasons)
            if extra > 0:
                display += f" (+{extra} more)"
            dec["detail_display"] = display[:200]
        else:
            dec["detail_display"] = dec.get("summary") or dec.get("reason", "—")[:200]

        # Risks display
        risks = dec.get("risks", [])
        dec["risks_display"] = [str(r)[:60] for r in risks[:5]] if risks else []

    # Stats — skip merged into rejected (both mean "not deployed")
    deploy_count = sum(1 for d in decisions if d.get("type") == "deploy")
    no_deploy_count = sum(1 for d in decisions if d.get("type") in ("no_deploy", "skip"))
    close_count = sum(1 for d in decisions if d.get("type") == "close")

    return {
        "decisions": recent,
        "stats": {
            "total": len(decisions),
            "deploy": deploy_count,
            "no_deploy": no_deploy_count,
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

    cooldowns = active_cooldowns(pool_mem)
    blocklist = blocklist_entries()

    return {
        "lessons": lessons_sorted,
        "signal_weights": signal_weights,
        "pool_stats": pool_stats,
        "cooldowns": cooldowns,
        "blocklist": blocklist,
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

@app.get("/favicon.svg")
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent / "favicon.svg", media_type="image/svg+xml")

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
