import requests
import time
import json
import base64
from datetime import datetime, timezone
from collections import defaultdict

# ============================================================
#  KONFIGURATION
# ============================================================
HELIUS_API_KEY = "DEIN_HELIUS_API_KEY"
GITHUB_TOKEN   = "DEIN_GITHUB_TOKEN"
GITHUB_USER    = "ztokk"
GITHUB_REPO    = "tramplin"
GITHUB_BRANCH  = "main"
# ============================================================

CONTRACT   = "3NJyzGWjSHP4hZvsqakodi7jAtbufwd52vn1ek6EzQ35"
MIN_SOL    = 0.05
MAX_PAGES  = 50
HELIUS_URL = "https://api.helius.xyz/v0/addresses/" + CONTRACT + "/transactions"
GITHUB_API = "https://api.github.com/repos/" + GITHUB_USER + "/" + GITHUB_REPO + "/contents/winners.json"
RAW_URL    = "https://raw.githubusercontent.com/" + GITHUB_USER + "/" + GITHUB_REPO + "/" + GITHUB_BRANCH + "/winners.json"
TREE_URL   = "https://api.github.com/repos/" + GITHUB_USER + "/" + GITHUB_REPO + "/git/trees/" + GITHUB_BRANCH + "?recursive=0"

def log(msg):
    t = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    print("[" + t + "] " + msg)

def get_sha_via_tree():
    """Holt SHA via Git Tree API - funktioniert auch fuer grosse Dateien"""
    headers = {"Authorization": "token " + GITHUB_TOKEN}
    try:
        r = requests.get(TREE_URL, headers=headers, timeout=15)
        r.raise_for_status()
        tree = r.json().get("tree", [])
        for item in tree:
            if item.get("path") == "winners.json":
                sha = item.get("sha")
                log("SHA via Tree API: " + sha[:8])
                return sha
        log("winners.json nicht im Tree gefunden")
        return None
    except Exception as e:
        log("Tree API Fehler: " + str(e))
        return None

def load_from_github():
    sha = get_sha_via_tree()
    if not sha:
        return None, None
    try:
        r2 = requests.get(RAW_URL + "?nocache=" + str(int(time.time())), timeout=30)
        r2.raise_for_status()
        content = r2.json()
        log("GitHub geladen: " + str(content["stats"]["total_wins"]) + " Wins, SHA=" + sha[:8])
        return content, sha
    except Exception as e:
        log("Raw URL Fehler: " + str(e))
        return None, None

def save_to_github(data, sha):
    headers = {"Authorization": "token " + GITHUB_TOKEN, "Accept": "application/vnd.github.v3+json"}
    content_b64 = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {
        "message": "Update: " + str(data["stats"]["total_wins"]) + " wins | " + data["stats"]["last_updated"],
        "content": content_b64,
        "branch":  GITHUB_BRANCH,
        "sha":     sha
    }
    try:
        r = requests.put(GITHUB_API, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        new_sha = r.json()["content"]["sha"]
        log("GitHub gespeichert! SHA=" + new_sha[:8])
        return new_sha
    except Exception as e:
        log("Upload Fehler: " + str(e))
        return sha

def fetch_page(before=None):
    params = {"api-key": HELIUS_API_KEY, "limit": 100}
    if before:
        params["before"] = before
    for attempt in range(5):
        try:
            r = requests.get(HELIUS_URL, params=params, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(3)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log("Helius Fehler: " + str(e))
            time.sleep(3)
    return []

def extract_winner(tx):
    sig       = tx.get("signature", "")
    timestamp = tx.get("timestamp", 0)
    time_str  = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if timestamp else "unknown"
    candidates = []
    for acc in tx.get("accountData", []):
        sol = acc.get("nativeBalanceChange", 0) / 1e9
        if sol >= MIN_SOL:
            candidates.append((acc.get("account", ""), sol))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    wallet, sol = candidates[0]
    if wallet and wallet != CONTRACT:
        return {"wallet": wallet, "sol": round(sol, 4), "timestamp": timestamp, "signature": sig, "time_str": time_str}
    return None

def build_leaderboard(wins):
    lb = defaultdict(lambda: {"total_sol": 0.0, "win_count": 0, "last_win": "", "first_win": ""})
    for w in sorted(wins, key=lambda x: x["timestamp"]):
        wallet = w["wallet"]
        lb[wallet]["total_sol"]  = round(lb[wallet]["total_sol"] + w["sol"], 4)
        lb[wallet]["win_count"] += 1
        lb[wallet]["last_win"]   = w["time_str"]
        if not lb[wallet]["first_win"]:
            lb[wallet]["first_win"] = w["time_str"]
    sorted_lb = sorted(lb.items(), key=lambda x: x[1]["total_sol"], reverse=True)
    return [{"rank": i+1, "wallet": wallet, "total_sol": round(data["total_sol"],4), "win_count": data["win_count"], "last_win": data["last_win"], "first_win": data["first_win"]} for i, (wallet, data) in enumerate(sorted_lb[:100])], len(lb)

def scan():
    log("=" * 50)
    log("Tramplin Scanner startet...")
    existing, sha = load_from_github()
    if not existing or not sha:
        log("Fehler: Kann GitHub nicht laden!")
        return
    all_wins       = existing.get("winners", [])
    known_sigs     = {w["signature"] for w in all_wins}
    last_timestamp = all_wins[0]["timestamp"] if all_wins else 0
    log("Bekannte Wins: " + str(len(all_wins)) + " | Letzter: " + (all_wins[0]["time_str"] if all_wins else "N/A"))
    new_wins = []
    before   = None
    page     = 0
    stop     = False
    while not stop and page < MAX_PAGES:
        txns = fetch_page(before)
        if not txns:
            break
        page += 1
        for tx in txns:
            sig = tx.get("signature", "")
            ts  = tx.get("timestamp", 0)
            if sig in known_sigs or (last_timestamp > 0 and ts < last_timestamp - 60):
                log("Bekannte TX -> Stop nach Seite " + str(page))
                stop = True
                break
            winner = extract_winner(tx)
            if winner:
                new_wins.append(winner)
        if not stop:
            before = txns[-1].get("signature")
            time.sleep(0.3)
    log("Neue Wins: " + str(len(new_wins)))
    if not new_wins:
        log("Keine neuen Wins -> kein Update")
        return
    combined = new_wins + all_wins
    seen = set()
    unique = []
    for w in combined:
        if w["signature"] not in seen:
            seen.add(w["signature"])
            unique.append(w)
    unique.sort(key=lambda x: x["timestamp"], reverse=True)
    leaderboard, unique_winners = build_leaderboard(unique)
    total_sol = round(sum(w["sol"] for w in unique), 3)
    output = {
        "stats": {"total_wins": len(unique), "total_sol_distributed": total_sol, "unique_winners": unique_winners, "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
        "winners": unique,
        "leaderboard": leaderboard
    }
    save_to_github(output, sha)
    log("Fertig! " + str(len(unique)) + " Wins | " + str(total_sol) + " SOL | " + str(unique_winners) + " Wallets")
    log("=" * 50)

if __name__ == "__main__":
    scan()
