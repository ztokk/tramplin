#!/usr/bin/env python3
import json
import os
import time
import requests
from datetime import datetime, timezone
from collections import defaultdict

HELIUS_API_KEY = os.environ.get(“HELIUS_API_KEY”, “DEIN_API_KEY_HIER”)
CONTRACT_ADDRESS = “3NJyzGWjSHP4hZvsqakodi7jAtbufwd52vn1ek6EzQ35”
OUTPUT_FILE = “winners.json”
MAX_PAGES = 100
WIN_MIN_SOL = 0.05

# Nur Transaktionen ab diesem Datum (Unix timestamp)

# 1.3.2025 = 1740787200

START_TIMESTAMP = 1740787200

HELIUS_URL = “https://api.helius.xyz/v0/addresses/” + CONTRACT_ADDRESS + “/transactions”

def fetch_transactions(before_sig=None):
params = {
“api-key”: HELIUS_API_KEY,
“limit”: 100,
}
if before_sig:
params[“before”] = before_sig
try:
resp = requests.get(HELIUS_URL, params=params, timeout=30)
resp.raise_for_status()
return resp.json()
except Exception as e:
print(”  Fehler beim Abrufen: “ + str(e))
return []

def load_existing_data():
if os.path.exists(OUTPUT_FILE):
with open(OUTPUT_FILE, “r”) as f:
return json.load(f)
return {“winners”: [], “wallets”: {}, “stats”: {}, “last_updated”: None}

def parse_winner_from_tx(tx):
try:
native_transfers = tx.get(“nativeTransfers”, [])
timestamp = tx.get(“timestamp”, 0)
sig = tx.get(“signature”, “”)

```
    for transfer in native_transfers:
        from_addr = transfer.get("fromUserAccount", "")
        to_addr = transfer.get("toUserAccount", "")
        amount_lamports = transfer.get("amount", 0)

        if from_addr == CONTRACT_ADDRESS and to_addr and to_addr != CONTRACT_ADDRESS:
            sol_amount = amount_lamports / 1000000000
            if sol_amount >= WIN_MIN_SOL:
                return {
                    "wallet": to_addr,
                    "sol": round(sol_amount, 4),
                    "timestamp": timestamp,
                    "signature": sig,
                    "time_str": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                }
except Exception:
    pass
return None
```

def build_leaderboard(wins_list):
wallets = defaultdict(lambda: {“total_sol”: 0.0, “win_count”: 0, “wins”: []})
for w in wins_list:
wallet = w[“wallet”]
wallets[wallet][“total_sol”] = round(wallets[wallet][“total_sol”] + w[“sol”], 4)
wallets[wallet][“win_count”] += 1
wallets[wallet][“wins”].append({
“sol”: w[“sol”],
“time_str”: w[“time_str”],
“timestamp”: w[“timestamp”],
“signature”: w[“signature”]
})
sorted_wallets = dict(
sorted(wallets.items(), key=lambda x: x[1][“total_sol”], reverse=True)
)
return sorted_wallets

def main():
print(“Tramplin.io Scanner startet…”)
print(“Contract: “ + CONTRACT_ADDRESS)

```
existing = load_existing_data()
known_sigs = {w["signature"] for w in existing.get("winners", [])}
print("Bekannte Transaktionen: " + str(len(known_sigs)))

all_wins = list(existing.get("winners", []))
new_count = 0
before_sig = None

print("Scanne Transaktionen ab 1.3.2025...")

for page in range(MAX_PAGES):
    txns = fetch_transactions(before_sig)
    if not txns:
        print("Seite " + str(page+1) + ": Keine weiteren Transaktionen.")
        break

    print("Seite " + str(page+1) + ": " + str(len(txns)) + " Transaktionen...")

    stop_scanning = False
    for tx in txns:
        sig = tx.get("signature", "")
        timestamp = tx.get("timestamp", 0)

        # Stoppen wenn wir vor dem Startdatum sind
        if timestamp > 0 and timestamp < START_TIMESTAMP:
            print("Startdatum 1.3.2025 erreicht, fertig.")
            stop_scanning = True
            break

        if sig in known_sigs:
            continue

        result = parse_winner_from_tx(tx)
        if result:
            all_wins.append(result)
            known_sigs.add(sig)
            new_count += 1

    if stop_scanning:
        break

    before_sig = txns[-1].get("signature")
    time.sleep(0.3)

print(str(new_count) + " neue Gewinne gefunden.")

all_wins.sort(key=lambda x: x["timestamp"], reverse=True)
wallets = build_leaderboard(all_wins)

total_sol = sum(w["sol"] for w in all_wins)
stats = {
    "total_wins": len(all_wins),
    "total_sol_distributed": round(total_sol, 4),
    "unique_winners": len(wallets),
    "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
}

output = {
    "stats": stats,
    "winners": all_wins[:500],
    "leaderboard": [
        {
            "rank": i + 1,
            "wallet": wallet,
            "total_sol": data["total_sol"],
            "win_count": data["win_count"],
            "last_win": data["wins"][0]["time_str"] if data["wins"] else ""
        }
        for i, (wallet, data) in enumerate(list(wallets.items())[:100])
    ]
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print("Gesamt Wins: " + str(stats["total_wins"]))
print("Gesamt SOL: " + str(stats["total_sol_distributed"]))
print("Unique Gewinner: " + str(stats["unique_winners"]))
print("Top 5:")
for entry in output["leaderboard"][:5]:
    print("#" + str(entry["rank"]) + " " + entry["wallet"][:8] + "... -> " + str(entry["total_sol"]) + " SOL (" + str(entry["win_count"]) + "x)")
```

if **name** == “**main**”:
main()
