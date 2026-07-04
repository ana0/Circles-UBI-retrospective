#!/usr/bin/env python3
"""
On-chain scan of the Circles UBI GnosisSafeProxyFactory on Gnosis Chain.

Reproduces:
  1. The factory creation block (binary search on eth_getCode).
  2. Every ProxyCreation event (= one signup/user) from launch to a cutoff,
     bucketed into a weekly signup histogram  -> results/signups_weekly.csv
  3. The modelled "accrued" circulating-supply curve, integrating continuous
     issuance (8/day, +7% per year) over each user's active time
                                                -> results/supply_over_time.csv

Method note (efficient log scan): the Gnosis public RPC caps eth_getLogs at
50,000 results and returns the largest fitting block range in its error `data`.
We walk forward exploiting that hint (up to 50k events per call).

IMPORTANT: a full run re-downloads ~2 years of logs (a few minutes). Outputs are
written to results/*.csv so you never need to re-scan to reuse the numbers.

Stdlib only (urllib). Run: python3 onchain_scan.py
"""
import json, urllib.request, os, csv, sys

RPC   = "https://rpc.gnosischain.com"
ADDR  = "0x8b4404DE0CaECE4b966a9959f134f0eFDa636156"          # the factory
TOPIC = "0xa38789425dbeee0239e16ff2d2567e31720127fbc6430758c1a4efc6aef29f80"  # ProxyCreation(address)
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# --- issuance model constants (all verified on-chain; see hub_constants.py) ---
PERIOD      = 31556952            # Circles inflation period = 365.2425 days (seconds)
WEEK        = 604800
R0          = 8.0 / 86400.0       # tokens/sec, year 1 (initialIssuance = 8 CRC/day)
R1          = R0 * 1.07           # tokens/sec, year 2 (after +7% step)
SIGNUP_BONUS = 50.0               # CRC minted once per signup (Hub `signupBonus` = 50e18 wei)

def rpc(method, params):
    req = urllib.request.Request(
        RPC, data=json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode(),
        headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def get_code(block):
    return rpc("eth_getCode", [ADDR, hex(block)]).get("result", "0x")

def block_ts(block):
    return int(rpc("eth_getBlockByNumber", [hex(block), False])["result"]["timestamp"], 16)

def latest_block():
    return int(rpc("eth_blockNumber", [])["result"], 16)

def find_creation_block(hi):
    """Binary search: first block where the contract has code."""
    lo = 1
    while lo < hi:
        mid = (lo + hi) // 2
        code = get_code(mid)
        if code in ("0x", "", None):
            lo = mid + 1
        else:
            hi = mid
    return lo

def find_block_at_ts(target, lo, hi):
    """First block with timestamp >= target."""
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo

def get_logs(frm, to):
    return rpc("eth_getLogs", [{"address": ADDR, "topics": [TOPIC],
                                "fromBlock": hex(frm), "toBlock": hex(to)}])

def scan_signups(start_block, end_block, t0):
    """Walk [start,end], return {week_index: signup_count}. Uses the 50k-hint trick."""
    hist, frm, total = {}, start_block, 0
    while frm <= end_block:
        to = min(frm + 300_000, end_block)          # bounded window avoids server timeouts
        resp = get_logs(frm, to)
        if "error" in resp:
            # RPC hint: "...block range [0xLO, 0xHI]" -> take HI
            hexes = [w for w in resp["error"].get("data", "").replace("[", " ").replace("]", " ").replace(",", " ").split() if w.startswith("0x")]
            sug = int(hexes[1], 16) if len(hexes) >= 2 else 0
            to = sug if frm < sug < to else frm + 60_000
            resp = get_logs(frm, to)
        for lg in resp.get("result", []):
            ts = int(lg["blockTimestamp"], 16)
            w = (ts - t0) // WEEK
            hist[w] = hist.get(w, 0) + 1
            total += 1
        print(f"  ...through block {to}  (cum {total})")
        frm = to + 1
    return hist, total

def supply_at(hist, t0, T):
    """Modelled supply at time T from the weekly signup histogram. Returns
    (issuance_only, signup_bonus, cumulative_users). Each user is assumed to sign
    up at their week midpoint; issuance integrates the piecewise rate, and each
    signup contributes a one-time SIGNUP_BONUS the moment they join."""
    y1, y2 = t0 + PERIOD, t0 + 2 * PERIOD
    def overlap(a, b, lo, hi):
        return max(0.0, min(b, hi) - max(a, lo))
    issuance = 0.0
    users = 0
    for w, c in hist.items():
        s = t0 + (w + 0.5) * WEEK
        if s >= T:
            continue
        users += c
        issuance += c * (R0 * overlap(s, T, t0, y1) + R1 * overlap(s, T, y1, y2))
    return issuance, users * SIGNUP_BONUS, users


def load_hist_from_csv(path):
    """Reload the weekly histogram (and t0) from a prior scan's CSV, so the supply
    model can be recomputed instantly without re-downloading ~2 years of logs.
    week 0's start timestamp is the launch time t0."""
    hist, t0 = {}, None
    with open(path) as f:
        rd = csv.DictReader(f)
        for row in rd:
            w = int(row["week_index"]); hist[w] = int(row["signups"])
            if w == 0:
                t0 = int(row["week_start_utc_ts"])
    return hist, t0

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    hist_csv = os.path.join(OUTDIR, "signups_weekly.csv")
    rescan = "--rescan" in sys.argv

    # Reuse the saved histogram if present (recompute the supply model instantly);
    # otherwise scan the chain from scratch. Pass --rescan to force a fresh scan.
    if os.path.exists(hist_csv) and not rescan:
        hist, t0 = load_hist_from_csv(hist_csv)
        print(f"Loaded weekly histogram from {hist_csv} (t0={t0}, {sum(hist.values())} signups). "
              f"Use --rescan to re-download from chain.")
    else:
        tip = latest_block()
        print(f"Chain tip: {tip}")
        cblock = find_creation_block(tip)
        t0 = block_ts(cblock)
        print(f"Factory creation block: {cblock}  (ts {t0})")
        end_block = find_block_at_ts(t0 + 2 * PERIOD, cblock, tip)
        print(f"Scanning to block {end_block} (end of year 2) ...")
        hist, total = scan_signups(cblock, end_block, t0)
        print(f"Total signups scanned: {total}")
        with open(hist_csv, "w", newline="") as f:
            wr = csv.writer(f); wr.writerow(["week_index", "week_start_utc_ts", "signups"])
            for w in sorted(hist):
                wr.writerow([w, t0 + w * WEEK, hist[w]])

    # supply curve at the paper's milestones: issuance alone vs. incl. signup bonus
    milestones = [("Month %d (%dd)" % (m, m*30), t0 + m*2592000) for m in (1,2,3,4,5,6,12,13,18)]
    milestones += [("Year 1 (365.24d)", t0 + PERIOD), ("Year 2 (730.5d)", t0 + 2*PERIOD)]
    rows = []
    for label, T in milestones:
        issuance, bonus, users = supply_at(hist, t0, T)
        rows.append((label, T, users, round(issuance), round(bonus), round(issuance + bonus)))

    with open(os.path.join(OUTDIR, "supply_over_time.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["milestone", "target_utc_ts", "cumulative_users",
                     "issuance_only", "signup_bonus_50crc", "total_with_bonus"])
        for r in rows:
            wr.writerow(r)

    # human-readable summary
    print(f"\nSignup bonus = {SIGNUP_BONUS:g} CRC/user (Hub `signupBonus`, on-chain verified)\n")
    print(f"{'Milestone':<18} {'Users':>9} {'Issuance only':>16} {'+ Bonus':>14} {'Total':>16} {'bonus%':>7}")
    print("-" * 84)
    for label, T, users, iss, bon, tot in rows:
        pct = bon / iss * 100 if iss else 0.0
        print(f"{label:<18} {users:>9,} {iss:>16,} {bon:>14,} {tot:>16,} {pct:>6.1f}%")
    print(f"\nWrote CSVs to {OUTDIR}/")

if __name__ == "__main__":
    main()
