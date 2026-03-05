import os
import json
import time
import requests
from datetime import datetime, timezone
from collections import defaultdict

# ---------------- CONFIG via ENV (GitHub Secrets/Vars) ----------------
HELIUS_API_KEY = os.environ["HELIUS_API_KEY"]  # required
CONTRACT = os.environ.get("CONTRACT", "3NJyzGWjSHP4hZvsqakodi7jAtbufwd52vn1ek6EzQ35")
MIN_SOL = float(os.environ.get("MIN_SOL", "0.05"))
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "11"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "50"))  # safety
OUT_FILE = os.environ.get("OUT_FILE", "winners.json")

HELIUS_URL = f"https://api.helius.xyz/v0/addresses/{CONTRACT}/transactions"

def utc_iso(ts=None):
    if ts is None:
        ts = time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def log(msg):
    t = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def read_json(path):
    if not os.path.exists(path):
        return {
            "stats": {
                "total_wins": 0,
                "total_sol_distributed": 0,
                "unique_winners": 0,
                "last_updated": None,
                "last_scan_ts": 0,
                "last_win_ts": 0,
                "interval_minutes": INTERVAL_MINUTES
            },
            "winners": [],
            "leaderboard": []
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def fetch_page(before=None):
    params = {"api-key": HELIUS_API_KEY, "limit": 100}
    if before:
        params["before"] = before

    for attempt in range(6):
        try:
            r = requests.get(HELIUS_URL, params=params, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 + attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log(f"Helius error (attempt {attempt+1}): {e}")
            time.sleep(2 + attempt)
    return []

def extract_winner(tx):
    sig = tx.get("signature", "")
    timestamp = int(tx.get("timestamp") or 0)
    if not sig or not timestamp:
        return None

    # find wallets with positive SOL change >= MIN_SOL
    candidates = []
    for acc in tx.get("accountData", []) or []:
        sol = (acc.get("nativeBalanceChange", 0) or 0) / 1e9
        if sol >= MIN_SOL:
            wallet = acc.get("account", "")
            if wallet and wallet != CONTRACT:
                candidates.append((wallet, sol))

    if not candidates:
        return None

    # choose max payout as "winner"
    wallet, sol = max(candidates, key=lambda x: x[1])
    return {
        "wallet": wallet,
        "sol": round(float(sol), 4),
        "timestamp": timestamp,
        "signature": sig,
        "time_str": utc_iso(timestamp)
    }

def build_leaderboard(wins):
    lb = defaultdict(lambda: {"total_sol": 0.0, "win_count": 0, "last_win_ts": 0})
    for w in wins:
        wallet = w["wallet"]
        lb[wallet]["total_sol"] += float(w["sol"])
        lb[wallet]["win_count"] += 1
        lb[wallet]["last_win_ts"] = max(lb[wallet]["last_win_ts"], int(w["timestamp"]))

    rows = []
    for wallet, d in lb.items():
        rows.append({
            "wallet": wallet,
            "total_sol": round(d["total_sol"], 4),
            "win_count": d["win_count"],
            "last_win": utc_iso(d["last_win_ts"])
        })

    rows.sort(key=lambda r: r["total_sol"], reverse=True)
    top = []
    for i, r in enumerate(rows[:100]):
        top.append({"rank": i+1, **r})
    return top, len(lb)

def should_scan(data):
    stats = data.get("stats", {})
    last_scan_ts = int(stats.get("last_scan_ts") or 0)
    last_win_ts = int(stats.get("last_win_ts") or 0)

    now = int(time.time())
    interval = int(stats.get("interval_minutes") or INTERVAL_MINUTES)

    # "11 min based on last win" – we gate scans using max(last_scan,last_win)
    next_scan_at = max(last_scan_ts, last_win_ts) + interval * 60
    if now < next_scan_at:
        log(f"Skip scan. next_scan_at={utc_iso(next_scan_at)}")
        return False
    return True

def main():
    log("=== Tramplin scan start ===")
    data = read_json(OUT_FILE)

    # keep interval in file
    data.setdefault("stats", {})
    data["stats"]["interval_minutes"] = INTERVAL_MINUTES

    if not should_scan(data):
        return

    winners = data.get("winners", []) or []
    known_sigs = set(w.get("signature") for w in winners if w.get("signature"))
    last_win_ts = int(data["stats"].get("last_win_ts") or 0)

    new_wins = []
    before = None
    pages = 0
    stop = False

    while not stop:
        txns = fetch_page(before)
        if not txns:
            break

        pages += 1
        for tx in txns:
            sig = tx.get("signature", "")
            ts = int(tx.get("timestamp") or 0)

            # stop when reaching known territory
            if sig and sig in known_sigs:
                stop = True
                break

            # optional safety: if extremely behind last_win_ts, stop
            if last_win_ts and ts and ts < last_win_ts - 15 * 60:
                stop = True
                break

            w = extract_winner(tx)
            if w:
                new_wins.append(w)

        if stop:
            break

        before = txns[-1].get("signature")
        if pages >= MAX_PAGES:
            log("MAX_PAGES reached, stopping")
            break
        time.sleep(0.25)

    now = int(time.time())
    log(f"New wins found: {len(new_wins)}")

    # merge + dedupe by signature
    combined = new_wins + winners
    seen = set()
    unique = []
    for w in combined:
        sig = w.get("signature")
        if not sig or sig in seen:
            continue
        seen.add(sig)
        unique.append(w)

    unique.sort(key=lambda x: int(x.get("timestamp") or 0), reverse=True)

    leaderboard, unique_winners = build_leaderboard(unique)
    total_sol = round(sum(float(w["sol"]) for w in unique), 3)
    newest_ts = int(unique[0]["timestamp"]) if unique else 0

    data["winners"] = unique
    data["leaderboard"] = leaderboard
    data["stats"].update({
        "total_wins": len(unique),
        "total_sol_distributed": total_sol,
        "unique_winners": unique_winners,
        "last_updated": utc_iso(now),
        "last_scan_ts": now,
        "last_win_ts": max(last_win_ts, newest_ts),
    })

    write_json_atomic(OUT_FILE, data)
    log(f"Done. total_wins={len(unique)} total_sol={total_sol} unique_winners={unique_winners}")

if __name__ == "__main__":
    main()
