"""
Meridian Dashboard API — Charon-inspired dark terminal UI
Read-only visualization of /root/meridian/ state files
"""
import json, os, urllib.request, urllib.error, time, secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Query, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="Meridian Dashboard")
MERIDIAN = Path(os.environ.get("MERIDIAN_PATH", "/root/meridian"))

DASHBOARD_CONFIG = Path(__file__).parent / "dashboard-config.json"

def load_dashboard_config():
    if DASHBOARD_CONFIG.exists():
        return json.loads(DASHBOARD_CONFIG.read_text())
    return {}

def save_dashboard_config(cfg):
    DASHBOARD_CONFIG.write_text(json.dumps(cfg, indent=2))

# Session secret — persist across restarts
cfg = load_dashboard_config()
if "session_secret" not in cfg:
    cfg["session_secret"] = secrets.token_hex(32)
    save_dashboard_config(cfg)

# Auth middleware — must come before SessionMiddleware in code
# (Starlette applies in reverse order, so session runs first)
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Login page + favicon are public
    if path in ("/login", "/favicon.svg"):
        return await call_next(request)
    # API: return 401 JSON if not authenticated
    if path.startswith("/api/") and not request.session.get("authenticated", False):
        return Response(content=json.dumps({"error": "Unauthorized"}), status_code=401, media_type="application/json")
    # All other routes: redirect to login if not authenticated
    if not request.session.get("authenticated", False):
        return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)

app.add_middleware(SessionMiddleware, secret_key=cfg["session_secret"])

# Auth dependency for route-level checks
def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401)
    return True

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meridian • Login</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'JetBrains Mono',monospace;background:#0d0d0d;color:#e5e5e5;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#141414;border:1px solid #252525;border-radius:8px;padding:32px;width:360px;max-width:90vw}
.card h1{font-size:16px;font-weight:700;color:#00e676;letter-spacing:2px;text-transform:uppercase;margin-bottom:4px}
.card p{font-size:11px;color:#666;margin-bottom:24px}
.card input{width:100%;padding:10px 12px;background:#1a1a1a;border:1px solid #333;border-radius:4px;color:#e5e5e5;font-family:inherit;font-size:13px;margin-bottom:12px;outline:none;transition:border .15s}
.card input:focus{border-color:#00e676}
.card button{width:100%;padding:10px;background:#00e676;color:#0d0d0d;border:none;border-radius:4px;font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;letter-spacing:1px;text-transform:uppercase;transition:opacity .15s}
.card button:hover{opacity:.85}
.err{color:#ff5252;font-size:11px;margin-bottom:12px;display:none}
.ft{text-align:center;margin-top:16px;font-size:9px;color:#444}
</style>
</head>
<body>
<div class="card">
<h1>Meridian</h1>
<p>DLMM Agent Dashboard</p>
<form method="post" action="/login">
<input type="password" name="password" placeholder="Enter password" autofocus>
<button type="submit">Login</button>
<div class="err" id="err">{error}</div>
</form>
<div class="ft">Session • Secure</div>
</div>
</body>
</html>"""
WALLET = os.environ.get("MERIDIAN_WALLET", "")

# Load Helius API key from Meridian .env
HELIUS_API_KEY = ""
ALCHEMY_API_KEY = ""
_meridian_env = MERIDIAN / ".env"
if _meridian_env.exists():
    try:
        for line in _meridian_env.read_text().splitlines():
            line = line.strip()
            if line.startswith("HELIUS_API_KEY="):
                HELIUS_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("ALCHEMY_API_KEY="):
                ALCHEMY_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
    except:
        pass
# Fallback: check .env.bak for Alchemy key
if not ALCHEMY_API_KEY:
    _bak = MERIDIAN / ".env.bak"
    if _bak.exists():
        try:
            import re
            for line in _bak.read_text().splitlines():
                if "WRITE_RPC_URLS" in line and "alchemy.com" in line:
                    m = re.search(r'alchemy\.com/v2/([a-zA-Z0-9_-]+)', line)
                    if m:
                        ALCHEMY_API_KEY = m.group(1)
                        break
        except:
            pass

PAPER = Path("/root/meridian/paper")

def get_meridian(paper=False):
    """Return the active meridian path (real or paper)."""
    return PAPER if paper else MERIDIAN

def load(fn, paper=False):
    fp = get_meridian(paper) / fn
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
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except:
                    res = {}
            if not isinstance(res, dict):
                res = {}
            res["as_of"] = rec.get("timestamp")
            return res
    return None


def fetch_wallet_rpc():
    """Fetch wallet balance directly via Helius RPC API.
    Returns SOL balance, SOL price, and token accounts."""
    config = load_dashboard_config()
    if not config.get("wallet_rpc_enabled", False) or not HELIUS_API_KEY:
        return None

    # Derive wallet address from state or config
    wallet = WALLET
    if not wallet:
        state = load("state.json")
        wallet = state.get("owner", "") or state.get("wallet", "")
    if not wallet:
        # Try to get from latest log
        wb = latest_wallet_balance()
        if wb:
            wallet = wb.get("wallet", "")

    if not wallet:
        return None

    try:
        # Get SOL balance via getBalance
        balance_url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        balance_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [wallet]
        }
        data = json.dumps(balance_payload).encode("utf-8")
        req = urllib.request.Request(balance_url, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        balance_result = json.loads(resp.read())

        if "result" not in balance_result:
            return None

        lamports = balance_result["result"]["value"]
        sol = lamports / 1e9

        # Get SOL price (cached, with Jupiter fallback)
        sol_price = get_sol_price()

        sol_usd = sol * sol_price

        # Get token accounts via getTokenAccountsByOwner
        token_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"}
            ]
        }
        token_data = json.dumps(token_payload).encode("utf-8")
        token_req = urllib.request.Request(balance_url, data=token_data, headers={"Content-Type": "application/json"})
        token_resp = urllib.request.urlopen(token_req, timeout=10)
        token_result = json.loads(token_resp.read())

        tokens = []
        total_usd = sol_usd
        usdc = 0

        for account in token_result.get("result", {}).get("value", []):
            info = account["account"]["data"]["parsed"]["info"]
            token_amount = info["tokenAmount"]
            mint = info["mint"]
            balance = float(token_amount["uiAmount"] or 0)

            if balance == 0:
                continue

            # Known tokens
            symbol = mint[:8]
            usd_value = 0

            if mint == "So11111111111111111111111111111111111111112":
                symbol = "SOL"
                usd_value = balance * sol_price
            elif mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                symbol = "USDC"
                usdc = balance
                usd_value = balance
            elif mint == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":
                symbol = "USDT"
                usd_value = balance
            else:
                # Try to get price for other tokens (skip for now)
                usd_value = 0

            total_usd += usd_value
            tokens.append({
                "mint": mint,
                "symbol": symbol,
                "balance": round(balance, 4),
                "usd": round(usd_value, 2)
            })

        return {
            "wallet": wallet,
            "sol": round(sol, 4),
            "sol_price": round(sol_price, 2),
            "sol_usd": round(sol_usd, 2),
            "usdc": round(usdc, 2),
            "tokens": tokens,
            "total_usd": round(total_usd, 2),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f"[RPC] Error fetching wallet balance: {e}")
        return None

_sol_price_cache = {"price": 0, "ts": 0}  # cache for 60s to avoid CoinGecko 429

def get_sol_price():
    """Fetch current SOL price from CoinGecko. Cached for 60s. Falls back to Jupiter."""
    import time
    now = time.time()
    if _sol_price_cache["price"] > 0 and now - _sol_price_cache["ts"] < 60:
        return _sol_price_cache["price"]
    # Try CoinGecko first
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        price = float(data["solana"]["usd"])
        _sol_price_cache["price"] = price
        _sol_price_cache["ts"] = now
        return price
    except Exception as e:
        print(f"[SOL_PRICE] CoinGecko error: {type(e).__name__}: {e}")
    # Fallback: Jupiter price API
    try:
        url = "https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        price = float(data["data"]["So11111111111111111111111111111111111111112"]["price"])
        _sol_price_cache["price"] = price
        _sol_price_cache["ts"] = now
        return price
    except Exception as e2:
        print(f"[SOL_PRICE] Jupiter fallback error: {type(e2).__name__}: {e2}")
    return _sol_price_cache["price"] or 0
DEPOSITS_FILE = MERIDIAN / "deposits.json"
DEPOSIT_CACHE_TTL = 3600  # refresh at most once per hour

def load_deposits_cache():
    if DEPOSITS_FILE.exists():
        try:
            return json.loads(DEPOSITS_FILE.read_text())
        except:
            pass
    return {"deposits": [], "last_sig": None, "last_fetch": 0, "stats": {}}

def save_deposits_cache(cache):
    try:
        DEPOSITS_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        print(f"[Deposits] Cache save error: {e}")

def get_wallet_addr():
    """Get wallet address from state.json or wallet balance logs."""
    state = load("state.json")
    w = state.get("owner", "") or state.get("wallet", "")
    if not w:
        wb = latest_wallet_balance()
        if wb:
            w = wb.get("wallet", "")
    return w

_sol_hourly_cache = {}  # { "YYYY-MM-DD": { hour: price } }

def fetch_sol_hourly_prices(date_str):
    """Fetch all 1h SOL prices for a date (DD-MM-YYYY) from yfinance.
    Returns dict {hour: close_price}. Caches in memory to avoid repeated calls.
    """
    # Convert DD-MM-YYYY to YYYY-MM-DD for yfinance
    from datetime import datetime as dt
    d = dt.strptime(date_str, "%d-%m-%Y")
    yf_date = d.strftime("%Y-%m-%d")

    if yf_date in _sol_hourly_cache:
        return _sol_hourly_cache[yf_date]

    try:
        import yfinance as yf
        start = yf_date
        end = (d + timedelta(days=1)).strftime("%Y-%m-%d")
        hist = yf.Ticker("SOL-USD").history(start=start, end=end, interval="1h")
        hourly = {}
        for idx in hist.index:
            hourly[idx.hour] = float(hist.loc[idx, "Close"])
        _sol_hourly_cache[yf_date] = hourly
        return hourly
    except Exception as e:
        print(f"[Deposit Price] yfinance error for {date_str}: {e}")
        return {}

def fetch_historical_sol_price(date_str, hour=None):
    """Fetch SOL price for a specific date/hour. Falls back to daily open if no hourly data."""
    hourly = fetch_sol_hourly_prices(date_str)
    if hour is not None and hour in hourly:
        return hourly[hour]
    # Fallback: first available hour or 0
    if hourly:
        return next(iter(hourly.values()))
    return 0

def fetch_deposits():
    """Fetch deposit history via Alchemy RPC (getSignaturesForAddress + getTransaction).
    Detects incoming SOL transfers (not swaps/LP/claims).
    Caches in deposits.json, refreshes at most once per hour.
    API usage: ~1-2 Alchemy calls + ~N CoinGecko calls per refresh.
    """
    cache = load_deposits_cache()

    # Rate limit: don't fetch more than once per hour
    if time.time() - cache.get("last_fetch", 0) < DEPOSIT_CACHE_TTL:
        return cache.get("stats", {})

    wallet = get_wallet_addr()
    if not wallet:
        return cache.get("stats", {})

    # Use Alchemy RPC (preferred) or Helius RPC fallback
    if ALCHEMY_API_KEY:
        rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        print(f"[Deposits] Using Alchemy RPC")
    elif HELIUS_API_KEY:
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        print(f"[Deposits] Using Helius RPC fallback")
    else:
        print(f"[Deposits] No RPC available (no Alchemy or Helius key)")
        return cache.get("stats", {})

    def rpc_call(method, params):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())

    try:
        # Backfill mode: only on first run (empty cache)
        has_cache = cache.get("last_sig") or len(cache.get("deposits", [])) > 0
        is_backfill = not has_cache
        MAX_BACKFILL_TXS = 500  # scan up to 500 txs on first run
        BATCH_SIZE = 100
        
        all_sigs = []
        before_sig = None
        
        if is_backfill:
            print(f"[Deposits] Backfill mode: scanning up to {MAX_BACKFILL_TXS} transactions...")
            while len(all_sigs) < MAX_BACKFILL_TXS:
                params = [wallet, {"limit": BATCH_SIZE}]
                if before_sig:
                    params[1]["before"] = before_sig
                result = rpc_call("getSignaturesForAddress", params)
                batch = result.get("result", [])
                if not batch:
                    break
                all_sigs.extend(batch)
                before_sig = batch[-1].get("signature")
                print(f"[Deposits] Backfill: {len(all_sigs)} signatures scanned...")
                time.sleep(0.5)  # Rate limit: stay under 500 CU/s
            sigs = all_sigs
            print(f"[Deposits] Backfill complete: {len(sigs)} total signatures")
        else:
            # Normal mode: only fetch new transactions
            sig_params = [wallet, {"limit": BATCH_SIZE}]
            if cache.get("last_sig"):
                sig_params[1]["before"] = cache["last_sig"]
            sig_result = rpc_call("getSignaturesForAddress", sig_params)
            sigs = sig_result.get("result", [])

        if not sigs:
            cache["last_fetch"] = time.time()
            save_deposits_cache(cache)
            return cache.get("stats", {})

        # Step 2: Get transaction details (batch of 5 to stay under rate limit)
        existing_sigs = {d["sig"] for d in cache["deposits"]}
        new_deposits = []

        # Known programs to exclude (LP operations, swaps, DeFi interactions)
        EXCLUDE_PROGRAMS = {
            "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM
            "DF1ow4tspfHX9JwWJsAb9epbkA8hmp",                # Meteora pool operations
            "L2TExMFKdjpN9kozasaurPirfHy9P8",                # Meteora DLMM helper
        }

        for sig_obj in sigs:
            sig = sig_obj.get("signature", "")
            if sig in existing_sigs:
                continue
            if sig_obj.get("err"):  # Skip failed transactions
                continue

            # Get transaction details
            try:
                tx_result = rpc_call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
                tx = tx_result.get("result")
                if not tx:
                    continue

                # Skip if transaction involves excluded programs (top-level or inner instructions)
                accounts = [a.get("pubkey", "") if isinstance(a, dict) else str(a) for a in tx.get("transaction", {}).get("message", {}).get("accountKeys", [])]
                meta_temp = tx.get("meta", {})
                inner_programs = set()
                for inner_group in meta_temp.get("innerInstructions", []):
                    for inner_inst in inner_group.get("instructions", []):
                        inner_programs.add(inner_inst.get("programId", ""))
                all_programs = set(accounts) | inner_programs
                if any(acc in EXCLUDE_PROGRAMS for acc in all_programs):
                    continue

                # Only count simple SOL transfers as deposits (not DeFi operations)
                instructions = tx.get("transaction", {}).get("message", {}).get("instructions", [])
                has_parsed_transfer = False
                for inst in instructions:
                    parsed = inst.get("parsed", {})
                    if parsed and parsed.get("type") == "transfer":
                        info = parsed.get("info", {})
                        if info.get("destination") == wallet:
                            has_parsed_transfer = True
                            break
                if not has_parsed_transfer:
                    continue

                # Check for incoming SOL via pre/postBalances
                meta = tx.get("meta", {})
                pre_balances = meta.get("preBalances", [])
                post_balances = meta.get("postBalances", [])
                account_keys = [a.get("pubkey", "") if isinstance(a, dict) else str(a) for a in tx.get("transaction", {}).get("message", {}).get("accountKeys", [])]

                wallet_idx = None
                for i, key in enumerate(account_keys):
                    if key == wallet:
                        wallet_idx = i
                        break

                if wallet_idx is not None and wallet_idx < len(pre_balances) and wallet_idx < len(post_balances):
                    balance_change = (post_balances[wallet_idx] - pre_balances[wallet_idx]) / 1e9
                    if balance_change >= 0.05:  # Minimum deposit threshold
                        block_time = tx.get("blockTime", sig_obj.get("blockTime", 0))
                        new_deposits.append({
                            "sig": sig,
                            "ts": block_time or 0,
                            "amount_sol": round(balance_change, 6),
                            "from": "on-chain",
                        })

                time.sleep(0.5)  # Rate limit: stay under 500 CU/s with Meridian agent
            except Exception as e:
                print(f"[Deposits] TX fetch error for {sig[:12]}: {e}")
                continue



        # Fetch historical SOL prices — 1 yfinance call per unique date
        dates_needed = set()
        for dep in new_deposits:
            dt = datetime.fromtimestamp(dep["ts"], tz=timezone.utc)
            dates_needed.add(dt.strftime("%d-%m-%Y"))

        for date_str in dates_needed:
            fetch_sol_hourly_prices(date_str)
            time.sleep(0.3)  # small delay between dates

        # Assign prices to deposits
        for dep in new_deposits:
            dt = datetime.fromtimestamp(dep["ts"], tz=timezone.utc)
            dep["sol_price"] = fetch_historical_sol_price(dt.strftime("%d-%m-%Y"), dt.hour)

        # Update cache
        cache["deposits"].extend(new_deposits)
        if sigs:
            cache["last_sig"] = sigs[0].get("signature", cache.get("last_sig"))
        cache["last_fetch"] = time.time()

        # Compute stats (weighted average deposit price)
        deposits = cache["deposits"]
        total_sol = sum(d.get("amount_sol", 0) for d in deposits)
        weighted_usd = sum(
            d.get("amount_sol", 0) * d.get("sol_price", 0)
            for d in deposits if d.get("sol_price", 0) > 0
        )
        avg_price = weighted_usd / total_sol if total_sol > 0 else 0
        with_price = sum(1 for d in deposits if d.get("sol_price", 0) > 0)

        cache["stats"] = {
            "total_sol": round(total_sol, 4),
            "total_usd": round(weighted_usd, 2),
            "avg_price": round(avg_price, 2),
            "count": len(deposits),
            "with_price": with_price,
            "last_deposit_ts": deposits[-1]["ts"] if deposits else 0,
        }

        save_deposits_cache(cache)
        return cache["stats"]
    except Exception as e:
        print(f"[Deposits] Error: {e}")
        return cache.get("stats", {})

def fmt(n, d=2):
    if n is None or n != n: return None
    return round(float(n), d)

@app.get("/api/dashboard")
async def dashboard(paper: bool = Query(False)):
    state = load("state.json", paper=paper)
    lessons = load("lessons.json", paper=paper)  # Agent-specific — overview shows agent's own PnL
    config = load("user-config.json", paper=paper)
    pool_mem = load("pool-memory.json", paper=paper)

    perf = lessons.get("performance", []) if isinstance(lessons, dict) else []
    closed = [p for p in perf if isinstance(p, dict)]

    # Wallet — auto-detect from env or state.json owner
    wallet = WALLET
    if not wallet:
        wallet = state.get("owner", "") or state.get("wallet", "")

    # Deposit tracking — fetch from Helius if cached data is stale (live only; paper uses simulated)
    deposit_stats = fetch_deposits() if not paper else None
    
    # Update wallet if still empty (found from deposit tracking logs)
    if not wallet:
        wallet = get_wallet_addr()

    # Active positions
    positions = state.get("positions", {})
    active = []
    total_unrealized = 0
    total_unclaimed_fees = 0
    total_unrealized_sol = 0
    total_unclaimed_fees_sol = 0
    sol_price_for_pnl = get_sol_price()
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
            "unrealized_pnl_sol": fmt(pos.get("amount_sol", 0) * (pos.get("last_pnl_pct", 0) or 0) / 100, 6) if pos.get("last_pnl_pct") else None,
            "unclaimed_fees_sol": fmt((pos.get("last_unclaimed_fees_usd", 0) or 0) / sol_price_for_pnl, 6) if sol_price_for_pnl else None,
            "total_value_sol": fmt(pos.get("amount_sol", 0) * (1 + (pos.get("last_pnl_pct", 0) or 0) / 100), 6) if pos.get("last_pnl_pct") is not None else pos.get("amount_sol"),
        })
    # Compute SOL unrealized totals
    for p in active:
        if p.get("unrealized_pnl_sol") is not None:
            total_unrealized_sol += p["unrealized_pnl_sol"]
        if p.get("unclaimed_fees_sol") is not None:
            total_unclaimed_fees_sol += p["unclaimed_fees_sol"]

    # Closed stats
    total_pnl = sum(p.get("pnl_usd", 0) for p in closed if isinstance(p, dict))
    wins = [p for p in closed if (p.get("pnl_pct", 0) or 0) > 0]
    losses = [p for p in closed if (p.get("pnl_pct", 0) or 0) <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win = sum(p.get("pnl_pct", 0) for p in wins) / len(wins) if wins else 0
    avg_loss = sum(p.get("pnl_pct", 0) for p in losses) / len(losses) if losses else 0
    total_fees = sum(
        (p.get("fee_pnl_usd") if p.get("fee_pnl_usd") is not None else p.get("fees_earned_usd", 0)) or 0
        for p in closed if isinstance(p, dict)
    )
    # SOL-denominated closed stats
    total_pnl_sol = sum(
        (p.get("amount_sol", 0) or 0) * ((p.get("pnl_pct", 0) or 0) / 100)
        for p in closed if isinstance(p, dict)
    )
    total_fees_sol = sum(
        ((p.get("fee_pnl_usd") if p.get("fee_pnl_usd") is not None else p.get("fees_earned_usd", 0)) or 0)
        / (p.get("initial_value_usd", 0) / p.get("amount_sol", 1) if p.get("amount_sol") else sol_price_for_pnl or 1)
        for p in closed if isinstance(p, dict)
    )
    # Deposit tracking — real PnL accounting for SOL price changes
    total_sol_deposited = sum((p.get("amount_sol", 0) or 0) for p in closed if isinstance(p, dict))
    total_initial_usd = sum((p.get("initial_value_usd", 0) or 0) for p in closed if isinstance(p, dict))
    avg_deposit_price = total_initial_usd / total_sol_deposited if total_sol_deposited else 0
    sol_price_change_pct = ((sol_price_for_pnl - avg_deposit_price) / avg_deposit_price * 100) if avg_deposit_price and sol_price_for_pnl else 0
    # Real PnL = SOL gains × current price (what your LP profits are worth TODAY)
    real_pnl_usd = total_pnl_sol * sol_price_for_pnl if sol_price_for_pnl else 0
    # vs Hold = if you just held the deposited SOL at current price vs actual outcome
    # Actual: wallet has current_balance, LP gained total_pnl_sol
    # Hold: would have total_sol_deposited × current_price
    # Net effect: real_pnl_usd already captures this — it's the USD value of LP gains at today's price
    # Price impact: how much SOL price dropped since avg deposit
    hold_times = [p.get("minutes_held", 0) for p in closed if p.get("minutes_held")]
    avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
    # Fee-yield vs inventory-bleed (negative-skew objective; split data since Fase A)
    split = [p for p in closed if isinstance(p, dict) and p.get("inventory_pnl_usd") is not None]
    fee_pnl_total = sum((p.get("fee_pnl_usd") if p.get("fee_pnl_usd") is not None else p.get("fees_earned_usd", 0)) or 0 for p in split)
    inventory_pnl_total = sum((p.get("inventory_pnl_usd") or 0) for p in split)
    split_trades = len(split)
    win_usd = [p.get("pnl_usd", 0) or 0 for p in wins]
    loss_usd = [p.get("pnl_usd", 0) or 0 for p in losses if (p.get("pnl_usd", 0) or 0) < 0]
    avg_win_usd = sum(win_usd) / len(win_usd) if win_usd else 0
    avg_loss_usd = sum(loss_usd) / len(loss_usd) if loss_usd else 0
    payoff_ratio = abs(avg_win_usd / avg_loss_usd) if avg_loss_usd else 0
    expectancy = total_pnl / len(closed) if closed else 0
    biggest_loss = min([p.get("pnl_usd", 0) or 0 for p in closed if isinstance(p, dict)], default=0)
    biggest_win = max([p.get("pnl_usd", 0) or 0 for p in closed if isinstance(p, dict)], default=0)
    fee_cover_pct = (fee_pnl_total / abs(inventory_pnl_total) * 100) if inventory_pnl_total < 0 else None

    # TP/SL stats
    tp_count = sum(1 for p in closed if "take profit" in (p.get("close_reason") or "").lower() or "trailing" in (p.get("close_reason") or "").lower())
    sl_count = sum(1 for p in closed if "stop loss" in (p.get("close_reason") or "").lower())
    oor_count = sum(1 for p in closed if "rule 3" in (p.get("close_reason") or "").lower() or "rule 4" in (p.get("close_reason") or "").lower() or "pumped" in (p.get("close_reason") or "").lower())

    # Daily PnL for chart (UTC timezone — matching calendar)
    daily = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            day = dt.strftime("%Y-%m-%d")
        except:
            day = ts[:10]
        if day not in daily:
            daily[day] = {"date": day, "pnl_usd": 0, "pnl_sol": 0, "trades": 0, "wins": 0, "fees": 0, "fees_sol": 0}
        daily[day]["pnl_usd"] += p.get("pnl_usd", 0) or 0
        daily[day]["pnl_sol"] += (p.get("amount_sol", 0) or 0) * ((p.get("pnl_pct", 0) or 0) / 100)
        daily[day]["trades"] += 1
        daily[day]["fees"] += p.get("fees_earned_usd", 0) or 0
        _deploy_sol = p.get("amount_sol", 0) or 0
        _deploy_usd = p.get("initial_value_usd", 0) or 0
        _sp_at_deploy = _deploy_usd / _deploy_sol if _deploy_sol else 0
        daily[day]["fees_sol"] += (p.get("fees_earned_usd", 0) or 0) / (_sp_at_deploy or sol_price_for_pnl or 1)
        if (p.get("pnl_pct", 0) or 0) > 0: daily[day]["wins"] += 1
    days = sorted(daily.values(), key=lambda x: x["date"])
    cum = 0
    cum_sol = 0
    for d in days:
        cum += d["pnl_usd"]
        d["cumulative"] = round(cum, 4)
        cum_sol += d["pnl_sol"]
        d["cumulative_sol"] = round(cum_sol, 6)

    # History (recent)
    history = sorted(closed, key=lambda x: x.get("recorded_at", ""), reverse=True)[:50]
    # Add SOL PnL to history entries
    for h in history:
        if isinstance(h, dict):
            _amt = h.get("amount_sol", 0) or 0
            _pct = h.get("pnl_pct", 0) or 0
            h["pnl_sol"] = round(_amt * _pct / 100, 6)
            _iv = h.get("initial_value_usd", 0) or 0
            _sp = _iv / _amt if _amt else 0
            h["fees_sol"] = round((h.get("fees_earned_usd", 0) or 0) / (_sp or sol_price_for_pnl or 1), 6)
            # Deposit SOL price tracking
            h["sol_price_at_deploy"] = round(_sp, 2) if _sp else None
            if _sp and sol_price_for_pnl:
                h["sol_price_change_pct"] = round((sol_price_for_pnl - _sp) / _sp * 100, 1)
            else:
                h["sol_price_change_pct"] = None
            # Real PnL for this trade at today's price
            h["real_pnl_usd"] = round(_amt * _pct / 100 * sol_price_for_pnl, 4) if sol_price_for_pnl else None

    # Config — normalize strategy if it's a nested object (paper config has {strategy, minBinsBelow, maxBinsBelow})
    raw_strategy = config.get("strategy")
    if isinstance(raw_strategy, dict):
        config["strategy"] = raw_strategy.get("strategy", "spot")
    config_summary = dict(config)
    config_summary["solMode"] = config.get("solMode", False)
    strategy_name = config.get("strategy", "spot")
    config_summary["strategyDetail"] = "Single-side SOL" if strategy_name == "spot" else "Dual-side"

    # Boot time for accurate uptime
    boot_time = None
    boot_file = get_meridian(paper) / "boot_time"
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

    # Wallet balance — paper uses simulated, live uses RPC
    if paper:
        # Paper agent: simulated 100 SOL starting balance
        sol_price = get_sol_price()
        total_deployed = sum(p.get("amount_sol", 0) or 0 for p in active)
        paper_sol = max(0, 100.0 - total_deployed)
        wallet_balance = {
            "sol": round(paper_sol, 4),
            "sol_usd": round(paper_sol * sol_price, 2),
            "sol_price": round(sol_price, 2),
            "usdc": 0,
            "total_usd": round(paper_sol * sol_price, 2),
            "tokens": [],
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        wallet = state.get("wallet", "") or "DR2UaR2nhR1Wc7QezUyvDH655nTDCquvMijs2pDaY8Sy"
        rpc_enabled = False
        # Paper: no deposit tracking — portfolio card hidden in UI
        deposit_stats = {}
    else:
        dc = load_dashboard_config()
        rpc_enabled = dc.get("wallet_rpc_enabled", False) and bool(HELIUS_API_KEY)
        wb = fetch_wallet_rpc() if rpc_enabled else None
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

    # Net worth = tokens holding (wallet) + open positions + rent fees.
    # Position value: prefer last_total_value_usd (on-chain from SDK), fallback to amount_sol × sol_price
    sol_price = wallet_balance.get("sol_price") if wallet_balance else 0
    positions_value = 0
    rent_sol_total = 0
    for p in active:
        # SDK writes last_total_value_usd; total_value_usd may not exist
        val_usd = p.get("last_total_value_usd") or p.get("total_value_usd")
        if val_usd is None or val_usd == 0:
            # Fallback: use amount_sol from state.json
            amount_sol = p.get("amount_sol", 0) or 0
            val_usd = amount_sol * sol_price if sol_price else 0
        positions_value += (val_usd or 0)
    
    # Rent: each DLMM position locks ~0.057 SOL for rent exemption (account size 3228 bytes)
    # This is a protocol constant — no need to query on-chain per position
    RENT_PER_POSITION_SOL = 0.057406  # getMinimumBalanceForRentExemption(3228) / 1e9
    rent_sol_total = len(active) * RENT_PER_POSITION_SOL
    
    rent_usd = round(rent_sol_total * sol_price, 2) if sol_price else 0
    total_equity = None
    if wallet_balance and wallet_balance.get("total_usd") is not None:
        total_equity = fmt(wallet_balance["total_usd"] + positions_value + (rent_usd or 0))

    # Portfolio PnL from deposit tracking: current total portfolio vs total deposited
    # "current SOL" = wallet SOL + open positions (in SOL) + token holdings (in SOL) + rent (in SOL)
    portfolio_pnl_sol = None
    portfolio_pnl_usd = None
    portfolio_total_usd = None
    portfolio_components = None
    if deposit_stats and deposit_stats.get("total_sol", 0) > 0 and wallet:
        current_sol = 0
        comp_wallet_sol = 0
        comp_positions_sol = 0
        comp_tokens_usd = 0
        comp_rent_sol = 0
        if wallet_balance and wallet_balance.get("sol"):
            current_sol = wallet_balance["sol"]
            comp_wallet_sol = wallet_balance["sol"]
        elif ALCHEMY_API_KEY:
            try:
                rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
                payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [wallet]}).encode()
                req = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req, timeout=10)
                result = json.loads(resp.read())
                current_sol = result.get("result", {}).get("value", 0) / 1e9
            except:
                pass
        
        # Add CURRENT value of open positions in SOL (total_value_sol reflects unrealized PnL; fallback amount_sol)
        # This avoids double-counting: wallet SOL is POST-deploy (what's left),
        # positions Sol is what was deployed INTO LP positions.
        # Use last_total_value_usd from state.json (on-chain value) instead of amount_sol fallback.
        for p in active:
            # Prefer on-chain value: last_total_value_usd / sol_price (SDK writes this field)
            pv_usd = p.get("last_total_value_usd") or p.get("total_value_usd")
            if pv_usd and sol_price_for_pnl:
                pv = pv_usd / sol_price_for_pnl
            else:
                pv = (p.get("total_value_sol") or p.get("amount_sol", 0) or 0)
            current_sol += pv
            comp_positions_sol += pv
        
        # Add rent fees (SOL locked in rent)
        if rent_sol_total > 0:
            current_sol += rent_sol_total
            comp_rent_sol = rent_sol_total
        
        # Add token holdings value (convert USD → SOL)
        if wallet_balance:
            tokens_usd = 0
            for t in wallet_balance.get("tokens", []):
                try:
                    tokens_usd += float(t.get("usd", 0) or 0)
                except:
                    pass
            usdc = 0
            try:
                usdc = float(wallet_balance.get("usdc", 0) or 0)
            except:
                pass
            tokens_sol = (tokens_usd + usdc) / sol_price_for_pnl if sol_price_for_pnl else 0
            current_sol += tokens_sol
            comp_tokens_usd = tokens_usd + usdc
        
        if current_sol > 0:
            deposited_usd = deposit_stats.get("total_usd", 0)
            current_usd = round(current_sol * sol_price_for_pnl, 2) if sol_price_for_pnl else 0
            portfolio_pnl_usd = round(current_usd - deposited_usd, 2)
            portfolio_pnl_sol = round(portfolio_pnl_usd / sol_price_for_pnl, 6) if sol_price_for_pnl else None
            portfolio_total_usd = current_usd
            portfolio_components = {
                "wallet_sol": round(comp_wallet_sol, 4),
                "positions_sol": round(comp_positions_sol, 4),
                "tokens_usd": round(comp_tokens_usd, 2),
                "rent_sol": round(comp_rent_sol, 4),
                "current_sol": round(current_sol, 4),
                "current_usd": current_usd,
                "deposited_sol": deposit_stats.get("total_sol", 0),
                "deposited_usd": deposited_usd,
                "avg_deposit_price": deposit_stats.get("avg_price", 0),
                "sol_price": sol_price_for_pnl,
            }

    # Active dev-mint cooldowns + blocklist
    cooldowns = active_cooldowns(pool_mem)
    blocklist_count = len(blocklist_entries())

    return {
        "wallet": (wallet[:6] + "..." + wallet[-4:]) if wallet else "—",
        "wallet_full": wallet,
        "has_helius_key": bool(HELIUS_API_KEY),
        "wallet_rpc_enabled": rpc_enabled,
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
        "net_pnl_sol": fmt(total_pnl_sol, 6),
        "unrealized_pnl_sol": fmt(total_unrealized_sol, 6),
        "unclaimed_fees_sol": fmt(total_unclaimed_fees_sol, 6),
        "total_fees_sol": fmt(total_fees_sol, 6),
        "sol_price": fmt(sol_price_for_pnl),
        "deposit_stats": deposit_stats,
        "portfolio_pnl_sol": portfolio_pnl_sol,
        "portfolio_pnl_usd": portfolio_pnl_usd,
        "portfolio_total_usd": portfolio_total_usd if portfolio_total_usd else None,
        "portfolio_components": portfolio_components,
         "real_pnl_usd": fmt(real_pnl_usd, 2),
        "total_sol_deposited": fmt(total_sol_deposited, 4),
        "avg_deposit_price": fmt(avg_deposit_price, 2),
        "sol_price_change_pct": fmt(sol_price_change_pct, 1),
        "avg_hold_min": round(avg_hold),
        "fee_pnl_total": fmt(fee_pnl_total, 2),
        "inventory_pnl_total": fmt(inventory_pnl_total, 2),
        "split_trades": split_trades,
        "avg_win_usd": fmt(avg_win_usd, 3),
        "avg_loss_usd": fmt(avg_loss_usd, 3),
        "payoff_ratio": fmt(payoff_ratio, 2),
        "expectancy_usd": fmt(expectancy, 3),
        "biggest_loss_usd": fmt(biggest_loss, 2),
        "biggest_win_usd": fmt(biggest_win, 2),
        "fee_cover_pct": (fmt(fee_cover_pct, 0) if fee_cover_pct is not None else None),
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
        "rent_usd": rent_usd,
        "rent_sol": fmt(rent_sol_total, 4),
        "total_equity_usd": total_equity,
        "cooldowns": cooldowns,
        "blocklist_count": blocklist_count,
        "config": config_summary,
    }

@app.get("/api/wallet")
async def wallet_endpoint():
    wb = fetch_wallet_rpc() or latest_wallet_balance()
    if not wb:
        return {"available": False, "has_api_key": bool(HELIUS_API_KEY)}
    return {"available": True, "has_api_key": bool(HELIUS_API_KEY), **wb}

@app.get("/api/config")
async def get_config():
    config = load_dashboard_config()
    config["has_helius_key"] = bool(HELIUS_API_KEY)
    return config

@app.patch("/api/config")
async def update_config(body: dict):
    config = load_dashboard_config()
    if "wallet_rpc_enabled" in body:
        config["wallet_rpc_enabled"] = bool(body["wallet_rpc_enabled"])
    save_dashboard_config(config)
    return {"ok": True, **config}

@app.get("/api/candidates")
async def candidates(paper: bool = Query(False)):
    import re
    decision_log = load("decision-log.json", paper=paper)
    decisions = decision_log.get("decisions", []) if isinstance(decision_log, dict) else []
    pool_mem = load("pool-memory.json", paper=paper)

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

@app.get("/api/pool-candidates")
async def pool_candidates(paper: bool = Query(False)):
    """Return pool candidates from pool-memory.json for the Candidates tab."""
    pool_mem = load("pool-memory.json", paper=paper)
    state_data = load("state.json", paper=paper)
    
    # Get open positions
    open_positions = state_data.get("positions", {})
    open_pools = set()
    for pos in open_positions.values() if isinstance(open_positions, dict) else []:
        open_pools.add(pos.get("pool", ""))
    
    candidates = []
    for addr, data in pool_mem.items():
        deploys = data.get("deploys", [])
        total_deploys = len(deploys)
        if total_deploys == 0:
            continue
            
        # Calculate stats
        pnl_values = [d.get("pnl_pct", 0) or 0 for d in deploys]
        wins = sum(1 for p in pnl_values if p > 0)
        avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0
        total_fees_usd = sum(d.get("fees_earned_usd", 0) or 0 for d in deploys)
        total_pnl_usd = sum(d.get("pnl_usd", 0) or 0 for d in deploys)
        
        # Last deploy info
        last_deploy = deploys[-1] if deploys else {}
        last_outcome = data.get("last_outcome", "unknown")
        last_pnl = last_deploy.get("pnl_pct", 0) or 0
        last_held = last_deploy.get("minutes_held", 0) or 0
        
        candidates.append({
            "pool": addr,
            "name": data.get("name", "?"),
            "base_mint": data.get("base_mint", ""),
            "total_deploys": total_deploys,
            "wins": wins,
            "losses": total_deploys - wins,
            "win_rate": round(wins / total_deploys * 100) if total_deploys > 0 else 0,
            "avg_pnl_pct": round(avg_pnl, 1),
            "total_pnl_usd": round(total_pnl_usd, 2),
            "total_fees_usd": round(total_fees_usd, 2),
            "last_outcome": last_outcome,
            "last_pnl_pct": round(last_pnl, 1),
            "last_held_min": last_held,
            "is_open": addr in open_pools,
        })
    
    # Sort by total deploys (most deployed first)
    candidates.sort(key=lambda x: x["total_deploys"], reverse=True)
    
    return {
        "candidates": candidates,
        "total": len(candidates),
        "open_pools": len(open_pools),
    }

@app.get("/api/candidates-latest")
async def candidates_latest(paper: bool = Query(False)):
    """Return latest cached candidates from Meridian screening (candidates-cache.json)."""
    cache_path = get_meridian(paper) / "candidates-cache.json"
    if not cache_path.exists():
        return {"candidates": [], "updatedAt": None, "total": 0}
    try:
        data = json.loads(cache_path.read_text())
        return {
            "candidates": data.get("candidates", []),
            "updatedAt": data.get("updatedAt"),
            "total": len(data.get("candidates", [])),
        }
    except Exception:
        return {"candidates": [], "updatedAt": None, "total": 0}

@app.get("/api/learning")
async def learning(paper: bool = Query(False)):
    lessons_data = load("lessons.json", paper=paper)
    signal_weights = load("signal-weights.json", paper=paper)
    pool_mem = load("pool-memory.json", paper=paper)

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

# Default password — stored in dashboard-config.json
DASHBOARD_PASSWORD = cfg.get("password", "meridian")  # CHANGE THIS after first login

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    error = request.query_params.get("error", "")
    err_html = f'<div class="err" style="display:block">{error}</div>' if error else ""
    return HTMLResponse(LOGIN_HTML.replace("{error}", err_html))

@app.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if password == DASHBOARD_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url="/login?error=Wrong+password", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

@app.get("/", response_class=HTMLResponse)
async def index():
    from fastapi.responses import Response
    content = (Path(__file__).parent / "index.html").read_text()
    return Response(content=content, media_type="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

@app.get("/favicon.svg")
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent / "favicon.svg", media_type="image/svg+xml")

@app.get("/api/calendar")
async def calendar(paper: bool = Query(False)):
    state = load("state.json", paper=paper)
    lessons = load("lessons.json", paper=paper)
    config = load("user-config.json", paper=paper)

    perf = lessons.get("performance", []) if isinstance(lessons, dict) else []
    closed = [p for p in perf if isinstance(p, dict)]

    # Build daily data (UTC — matches Meteora/Meridian timezone)
    def _utc_day(ts_str):
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except:
            return ts_str[:10]

    daily = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = _utc_day(ts)
        if day not in daily:
            daily[day] = {"date": day, "pnl_usd": 0, "pnl_sol": 0, "trades": 0, "wins": 0, "fees": 0, "fees_sol": 0, "positions": 0}
        daily[day]["pnl_usd"] += p.get("pnl_usd", 0) or 0
        daily[day]["pnl_sol"] += (p.get("amount_sol", 0) or 0) * ((p.get("pnl_pct", 0) or 0) / 100)
        daily[day]["trades"] += 1
        daily[day]["fees"] += p.get("fees_earned_usd", 0) or 0
        _ds = p.get("amount_sol", 0) or 0
        _du = p.get("initial_value_usd", 0) or 0
        _sp = _du / _ds if _ds else 1
        daily[day]["fees_sol"] += (p.get("fees_earned_usd", 0) or 0) / _sp if _sp else 0
        if (p.get("pnl_pct", 0) or 0) > 0: daily[day]["wins"] += 1

    # Count positions opened per day (from closed trades = each closed = 1 opened)
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = _utc_day(ts)
        if day in daily:
            daily[day]["positions"] = daily[day].get("positions", 0) + 1

    # Build position details per day
    by_day = {}
    for p in closed:
        ts = p.get("recorded_at", "")
        if not ts: continue
        day = _utc_day(ts)
        if day not in by_day: by_day[day] = []
        pnl = p.get("pnl_pct", 0) or 0
        by_day[day].append({
            "pool": p.get("pool_name", "?"),
            "pnl_pct": round(pnl, 2),
            "pnl_usd": round(p.get("pnl_usd", 0) or 0, 4),
            "pnl_sol": round((_amt := p.get("amount_sol", 0) or 0) * (pnl / 100), 6),
            "fees": round(p.get("fees_earned_usd", 0) or 0, 4),
            "fees_sol": round((p.get("fees_earned_usd", 0) or 0) / ((_du := p.get("initial_value_usd", 0) or 0) / _amt if _amt else 1), 6),
            "held": p.get("minutes_held", 0),
            "reason": (p.get("close_reason") or "")[:60],
            "strategy": p.get("strategy", "?"),
        })

    return {"daily": list(daily.values()), "by_day": by_day}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
