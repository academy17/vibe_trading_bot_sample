"""
STEP 00 (debug) -- One-shot snapshot from the price websocket.

Usage:
    python 00_prices.py                     # print all symbols
    python 00_prices.py SYMM                # filter by substring
    python 00_prices.py SYMM::80..5f_SFLOW  # exact name

The price service pushes a FULL snapshot on every tick, so one recv is enough. 
"""
import sys
from _common import fetch_prices

def main():
    filt = sys.argv[1] if len(sys.argv) > 1 else ""
    prices = fetch_prices()
    if filt:
        prices = {k: v for k, v in prices.items() if filt in k}
    if not prices:
        raise SystemExit(f"no symbols matched '{filt}'")
    width = max(len(k) for k in prices)
    for name in sorted(prices):
        print(f"  {name:<{width}}  {prices[name]}")

if __name__ == "__main__":
    main()
