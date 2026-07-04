#!/usr/bin/env python3
"""
Circles UBI issuance-inflation model: early-adopter advantage erosion.

Regenerates the Alice/Bob balance tables used in the paper.

Model (Circles v1):
  - Base issuance: 8 tokens/day = 240/month. One base-rate year = 12 * 240 = 2880 tokens.
  - Issuance rate steps up 7% at each yearly boundary (the Circles `period`).
  - Balances are purely ADDITIVE: v1 has no demurrage, so balances only grow.
  - The issuance rate is GLOBAL (a function of system time, not signup time):
    in any given year, every active user mints the same amount.

Key consequence:
  Alice (joins year 1) and Bob (joins year 2) mint identically in every shared
  year. Alice's only permanent edge is her first year (2880 tokens), so the
  ABSOLUTE gap is frozen at 2880 forever, while both balances grow ~geometrically
  -> the RELATIVE gap decays as z(N) = 1 / (sum_{n=1..N} 1.07^(n-1) - 1).

Run: python3 inflation.py
"""

BASE = 2880.0      # one year of issuance at the base rate (12 months * 240)
INFL = 1.07        # +7% per year

def year_issuance(n):
    """Tokens minted during year n by a continuously-active user (n = 1,2,...)."""
    return BASE * INFL ** (n - 1)

def balance(join_year, end_year):
    """Balance at end of `end_year` for a user active from the start of `join_year`."""
    return sum(year_issuance(n) for n in range(join_year, end_year + 1))

def rel_gap(end_year):
    """Alice-vs-Bob relative gap (Alice has this fraction MORE than Bob).
    Closed form: 1 / (sum_{n=1..N} 1.07^(n-1) - 1)."""
    denom = sum(INFL ** (n - 1) for n in range(1, end_year + 1)) - 1.0
    return float('nan') if denom <= 0 else 1.0 / denom

def main():
    years = [1, 2, 3, 5, 10, 20]
    print(f"Base year issuance = {BASE:,.0f} tokens; inflation = {(INFL-1)*100:.0f}%/yr\n")
    hdr = f"{'End yr':>6} | {'Alice(joins y1)':>15} | {'Bob(joins y2)':>13} | {'abs gap':>8} | {'z (Alice>Bob)':>13}"
    print(hdr); print("-" * len(hdr))
    for N in years:
        a = balance(1, N)
        b = balance(2, N) if N >= 2 else 0.0
        z = rel_gap(N) * 100 if N >= 2 else float('nan')
        gap = a - b
        zs = "     -    " if N < 2 else f"{z:11.1f}%"
        print(f"{N:>6} | {a:>15,.0f} | {b:>13,.0f} | {gap:>8,.0f} | {zs:>13}")
    print("\nNote: absolute gap is constant (= Alice's frozen first-year issuance).")
    print("Relative gap decays geometrically toward zero as inflation grows the base.")

if __name__ == "__main__":
    main()
