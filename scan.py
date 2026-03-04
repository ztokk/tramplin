import requests
import time
import json
from datetime import datetime, timezone
from collections import defaultdict

import os
API_KEY = os.environ.get("HELIUS_API_KEY", "")
CONTRACT = "3NJyzGWjSHP4hZvsqakodi7jAtbufwd52vn1ek6EzQ35"
OUTPUT = "winners.json"
MIN_SOL = 0.05

URL = "https://api.helius.xyz/v0/addresses/" + CONTRACT + "/transactions"

def fetch_page(before=None):
    params = {"api-key": API_KEY, "limit": 100}
    if before:
        params["before"] = before
    for _ in range(5):
        try:
            r = requests.get(URL, params=params, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()
        except:
            time.sleep(2)
    return []

def load_existing():
    if __import__('os').path.exists(OUTPUT):
        with open(OUTPUT) as f:
            return json.load(f)
    return {"stats": {}, "winners": [], "leaderboard": []}

print("Tramplin.io incremental scan starting...\n")

existing = load_existing()
known_sigs = {w["signature"] for w in existing.get("winners", [])}

# Get last scan timestamp
last_ts = 0
for w in existing.get("winners", []):
    if w.get("timestamp", 0) > last_ts:
        last_ts = w["timestamp"]

if last_ts > 0:
    last_str = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("Last scan:", last_str)
    print("Scanning only NEW transactions since then...\n")
else:
    print("No existing data - full scan\n")

new_wins = []
before = None
page = 0
stop = False

while not stop:
    txns = fetch_page(before)
    if not txns:
        break

    page += 1
    print("Page", page, "| New wins:", len(new_wins))

    for tx in txns:
        sig = tx.get("signature", "")
        timestamp = tx.get("timestamp", 0)

        # Stop if we reach already scanned transactions
        if last_ts > 0 and timestamp <= last_ts:
            print("Reached last scan timestamp - stopping.")
            stop = True
            break

        if sig in known_sigs:
            continue

        account_data = tx.get("accountData", [])
        if not account_data:
            continue

        candidates = []
        for acc in account_data:
            chg = acc.get("nativeBalanceChange", 0)
            sol = chg / 1e9
            if sol >= MIN_SOL:
                candidates.append((acc.get("account", ""), sol))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            winner_wallet, winner_sol = candidates[0]
            if winner_wallet and winner_wallet != CONTRACT:
                time_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if timestamp else "unknown"
                new_wins.append({
                    "wallet": winner_wallet,
                    "sol": round(winner_sol, 4),
                    "timestamp": timestamp,
                    "signature": sig,
                    "time_str": time_str
                })
                known_sigs.add(sig)

    if not stop:
        before = txns[-1].get("signature")
    time.sleep(0.2)

print("\nNew wins found:", len(new_wins))

all_wins = new_wins + existing.get("winners", [])
all_wins.sort(key=lambda x: x["timestamp"], reverse=True)
all_wins = all_wins[:2000]

lb = defaultdict(lambda: {"total_sol": 0.0, "win_count": 0, "last_win": ""})
for w in all_wins:
    lb[w["wallet"]]["total_sol"] = round(lb[w["wallet"]]["total_sol"] + w["sol"], 4)
    lb[w["wallet"]]["win_count"] += 1
    if not lb[w["wallet"]]["last_win"]:
        lb[w["wallet"]]["last_win"] = w["time_str"]

sorted_lb = sorted(lb.items(), key=lambda x: x[1]["total_sol"], reverse=True)
total_sol = sum(w["sol"] for w in all_wins)

output = {
    "stats": {
        "total_wins": len(all_wins),
        "total_sol_distributed": round(total_sol, 2),
        "unique_winners": len(lb),
        "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    },
    "winners": all_wins[:500],
    "leaderboard": [
        {
            "rank": i + 1,
            "wallet": wallet,
            "total_sol": round(data["total_sol"], 2),
            "win_count": data["win_count"],
            "last_win": data["last_win"]
        }
        for i, (wallet, data) in enumerate(sorted_lb[:100])
    ]
}

with open(OUTPUT, "w") as f:
    json.dump(output, f, indent=2)

print("Saved to", OUTPUT)
print("Total wins:", len(all_wins))
print("Total SOL:", round(total_sol, 2))
print("Unique winners:", len(lb))
print("\nTop 5:")
for e in output["leaderboard"][:5]:
    print("#" + str(e["rank"]), e["wallet"][:8] + "...", "->", str(e["total_sol"]) + " SOL (" + str(e["win_count"]) + "x)")
