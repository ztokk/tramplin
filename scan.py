#!/usr/bin/env python3
“””
Tramplin.io SOL Winners Scanner
Scannt alle Transaktionen vom Smart Contract und baut winners.json
“””

import json
import os
import time
import requests
from datetime import datetime, timezone
from collections import defaultdict

# ── Konfiguration ─────────────────────────────────────────────────────────────

HELIUS_API_KEY = os.environ.get(“HELIUS_API_KEY”, “DEIN_API_KEY_HIER”)
CONTRACT_ADDRESS = “3NJyzGWjSHP4hZvsqakodi7jAtbufwd52vn1ek6EzQ35”
OUTPUT_FILE = “winners.json”
MAX_PAGES = 50  # max. Seiten rückwirkend scannen (1 Seite = 100 Txns)

HELIUS_URL = f”https://api.helius.xyz/v0/addresses/{CONTRACT_ADDRESS}/transactions”
WIN_MIN_SOL = 0.05  # Mindest-SOL für einen Gewinn (filtert Fees raus)

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def fetch_transactions(before_sig=None):
“”“Holt eine Seite Transaktionen vom Contract.”””
params = {
“api-key”: HELIUS_API_KEY,
“limit”: 100,
}
if before_sig:
params[“before”] = before_sig

```
try:
    resp = requests.get(HELIUS_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
except Exception as e:
    print(f"  ⚠ Fehler beim Abrufen: {e}")
    return []
```

def load_existing_data():
“”“Lädt bestehende winners.json falls vorhanden.”””
if os.path.exists(OUTPUT_FILE):
with open(OUTPUT_FILE, “r”) as f:
return json.load(f)
return {“winners”: [], “wallets”: {}, “stats”: {}, “last_updated”: None}

def parse_winner_from_tx(tx):
“””
Extrahiert Gewinner-Wallet und SOL-Betrag aus einer Transaktion.
Gibt (wallet, sol_amount, timestamp) oder None zurück.
“””
try:
# Helius gibt native transfers direkt zurück
native_transfers = tx.get(“nativeTransfers”, [])
timestamp = tx.get(“timestamp”, 0)
sig = tx.get(“signature”, “”)

```
    # Wir suchen Transfers VOM Contract an andere Wallets (= Gewinnauszahlung)
    for transfer in native_transfers:
        from_addr = transfer.get("fromUserAccount", "")
        to_addr = transfer.get("toUserAccount", "")
        amount_lamports = transfer.get("amount", 0)

        # Transfer vom Contract an andere Wallet = Gewinn
        if from_addr == CONTRACT_ADDRESS and to_addr and to_addr != CONTRACT_ADDRESS:
            sol_amount = amount_lamports / 1_000_000_000  # Lamports → SOL
            if sol_amount >= WIN_MIN_SOL:  # Mindestbetrag filtern (Fees ignorieren)
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
“”“Baut Wallet-Statistiken aus der Wins-Liste.”””
wallets = defaultdict(lambda: {“total_sol”: 0.0, “win_count”: 0, “wins”: []})

```
for w in wins_list:
    wallet = w["wallet"]
    wallets[wallet]["total_sol"] = round(wallets[wallet]["total_sol"] + w["sol"], 4)
    wallets[wallet]["win_count"] += 1
    wallets[wallet]["wins"].append({
        "sol": w["sol"],
        "time_str": w["time_str"],
        "timestamp": w["timestamp"],
        "signature": w["signature"]
    })

# Sortieren nach Gesamt-SOL
sorted_wallets = dict(
    sorted(wallets.items(), key=lambda x: x[1]["total_sol"], reverse=True)
)
return sorted_wallets
```

def main():
print(“🚀 Tramplin.io Scanner startet…”)
print(f”   Contract: {CONTRACT_ADDRESS}”)
print(f”   API Key:  {HELIUS_API_KEY[:8]}…”)

```
# Bestehende Daten laden
existing = load_existing_data()
known_sigs = {w["signature"] for w in existing.get("winners", [])}
print(f"   Bekannte Transaktionen: {len(known_sigs)}")

all_wins = list(existing.get("winners", []))
new_count = 0
before_sig = None

print("\n📡 Scanne Transaktionen...")

for page in range(MAX_PAGES):
    txns = fetch_transactions(before_sig)
    if not txns:
        print(f"   Seite {page+1}: Keine weiteren Transaktionen.")
        break

    print(f"   Seite {page+1}: {len(txns)} Transaktionen...")

    found_new = False
    for tx in txns:
        sig = tx.get("signature", "")
        if sig in known_sigs:
            continue  # schon bekannt, überspringen

        result = parse_winner_from_tx(tx)
        if result:
            all_wins.append(result)
            known_sigs.add(sig)
            new_count += 1
            found_new = True

    before_sig = txns[-1].get("signature")

    # Wenn alle Txns auf dieser Seite bekannt waren → fertig
    if not found_new and len(known_sigs) > 0:
        print("   Alle bekannten Daten erreicht, fertig.")
        break

    time.sleep(0.3)  # Rate limiting

print(f"\n✅ {new_count} neue Gewinne gefunden.")

# Sortieren (neueste zuerst)
all_wins.sort(key=lambda x: x["timestamp"], reverse=True)

# Leaderboard bauen
wallets = build_leaderboard(all_wins)

# Statistiken
total_sol = sum(w["sol"] for w in all_wins)
stats = {
    "total_wins": len(all_wins),
    "total_sol_distributed": round(total_sol, 4),
    "unique_winners": len(wallets),
    "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
}

# Output speichern
output = {
    "stats": stats,
    "winners": all_wins[:500],  # max. 500 letzte Wins
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

print(f"\n📊 Ergebnis:")
print(f"   Gesamte Wins:       {stats['total_wins']}")
print(f"   Gesamt SOL:         {stats['total_sol_distributed']} SOL")
print(f"   Unique Gewinner:    {stats['unique_winners']}")
print(f"   Gespeichert in:     {OUTPUT_FILE}")
print(f"\n🏆 Top 5 Gewinner:")
for entry in output["leaderboard"][:5]:
    print(f"   #{entry['rank']} {entry['wallet'][:8]}... → {entry['total_sol']} SOL ({entry['win_count']}x)")
```

if **name** == “**main**”:
main()
