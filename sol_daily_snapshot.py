#!/usr/bin/env python3
"""
Write today's opening SOL snapshot to sol-daily-snapshot.json.

Run by cron once daily at 00:01 UTC (= 07:01 WIB), the same day boundary the
dashboard already uses for pnl_today (today_start = UTC midnight). Only writes
the entry if today's key doesn't exist yet, so it captures the value at the
cutoff rather than being overwritten by a later re-run that day.

Dashboard-only — reuses server.py's own dashboard() computation for current_sol
(wallet + open positions + token holdings + rent) instead of re-deriving it, and
never touches anything under /root/meridian.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402

SNAPSHOT_FILE = Path(__file__).parent / "sol-daily-snapshot.json"
MAX_DAYS_KEPT = 400  # ~13 months of daily entries before trimming


def load_snapshots():
    if SNAPSHOT_FILE.exists():
        try:
            return json.loads(SNAPSHOT_FILE.read_text())
        except Exception:
            pass
    return {}


async def main():
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshots = load_snapshots()
    if today_key in snapshots:
        print(f"snapshot for {today_key} already exists — skipping")
        return 0

    d = await server.dashboard(paper=False)
    components = d.get("portfolio_components") or {}
    current_sol = components.get("current_sol")
    if current_sol is None:
        print("no portfolio_components.current_sol available yet — skipping")
        return 0

    snapshots[today_key] = {
        "current_sol": current_sol,
        "current_usd": components.get("current_usd"),
        "sol_price": components.get("sol_price"),
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Trim oldest entries beyond MAX_DAYS_KEPT to keep the file small indefinitely.
    if len(snapshots) > MAX_DAYS_KEPT:
        for k in sorted(snapshots)[: len(snapshots) - MAX_DAYS_KEPT]:
            del snapshots[k]

    tmp = SNAPSHOT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshots, indent=1, sort_keys=True))
    tmp.replace(SNAPSHOT_FILE)  # atomic
    print(f"wrote snapshot for {today_key}: current_sol={current_sol}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
