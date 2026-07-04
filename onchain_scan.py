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
import json, urllib.request, os, csv

RPC   = "https://rpc.gnosischain.com"
ADDR  = "0x8b4404DE0CaECE4b966a9959f134f0eFDa636156"          # the factory
TOPIC = "0xa38789425dbeee0239e16ff2d2567e31720127fbc6430758c1a4efc6aef29f80"  # ProxyCreation(address)
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# --- issuance model constants ---
T0_FALLBACK = 1602786380          # launch ts (Oct 15 2020 18:26:20 UTC), verified below
PERIOD      = 31556952            # Circles inflation period = 365.2425 days (seconds)
WEEK        = 604800
R0          = 8.0 / 86400.0       # tokens/sec, year 1
R1          = R0 * 1.07           # tokens/sec, year 2 (after +7% step)

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
    """Modelled accrued supply at time T from the weekly signup histogram.
    Each user assumed to sign up at their week midpoint; integrate the piecewise rate."""
    y1, y2 = t0 + PERIOD, t0 + 2 * PERIOD
    def overlap(a, b, lo, hi):
        return max(0.0, min(b, hi) - max(a, lo))
    total = 0.0
    for w, c in hist.items():
        s = t0 + (w + 0.5) * WEEK
        if s >= T:
            continue
        per_user = R0 * overlap(s, T, t0, y1) + R1 * overlap(s, T, y1, y2)
        total += c * per_user
    return total

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    tip = latest_block()
    print(f"Chain tip: {tip}")
    cblock = find_creation_block(tip)
    t0 = block_ts(cblock)
    print(f"Factory creation block: {cblock}  (ts {t0})")

    # scan window: launch -> end of year 2 (covers the paper's milestones)
    end_ts = t0 + 2 * PERIOD
    end_block = find_block_at_ts(end_ts, cblock, tip)
    print(f"Scanning to block {end_block} (end of year 2, ts {end_ts}) ...")
    hist, total = scan_signups(cblock, end_block, t0)
    print(f"Total signups scanned: {total}")

    # write weekly histogram
    with open(os.path.join(OUTDIR, "signups_weekly.csv"), "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(["week_index", "week_start_utc_ts", "signups"])
        for w in sorted(hist):
            wr.writerow([w, t0 + w * WEEK, hist[w]])

    # write supply curve at the paper's milestones
    milestones = [("Month %d (%dd)" % (m, m*30), t0 + m*2592000) for m in (1,2,3,4,5,6,12,13,18)]
    milestones += [("Year 1 (365.24d)", t0 + PERIOD), ("Year 2 (730.5d)", t0 + 2*PERIOD)]
    with open(os.path.join(OUTDIR, "supply_over_time.csv"), "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(["milestone", "target_utc_ts", "cumulative_users", "accrued_supply"])
        for label, T in milestones:
            users = sum(c for w, c in hist.items() if t0 + (w + 0.5) * WEEK < T)
            wr.writerow([label, T, users, round(supply_at(hist, t0, T))])
    print(f"Wrote CSVs to {OUTDIR}/")

if __name__ == "__main__":
    main()
