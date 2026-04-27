"""
STEP 99 -- Decode a captured SignedOperation callData for debugging.

Paste the `callData` hex from a captured instant_open / instant_close
payload into the script (or pass as argv).

Usage:
    python 99_decode.py <hex-callData>           # auto-detects which function
    python 99_decode.py addmargin <hex>
    python 99_decode.py sendquote <hex>
    python 99_decode.py close     <hex>
"""
import sys
from decimal import Decimal
from eth_abi import decode as _decode
from _common import (SEL_ADD_MARGIN_TO_NEXT_VA, SEL_SEND_QUOTE_WITH_AFFILIATE_DATA,
                     SEL_REQUEST_TO_CLOSE_POSITION)

def w(x): return Decimal(x) / Decimal(10**18)

def decode_addmargin(d):
    sub, iso, sid, amt = _decode(["address","uint8","uint256","uint256"], d)
    return {"fn": "addMarginToNextVA", "subAccount": sub, "vaIsolation": iso,
            "symbolId": sid, "amount_wei": amt, "amount_dec": w(amt)}

def decode_sendquote(d):
    (partyBs, sid, pos, otype, price, qty, cva, lf, pa_mm, pb_mm,
     dl, aff, upnl, data) = _decode(
        ["address[]","uint256","uint8","uint8","uint256","uint256","uint256",
         "uint256","uint256","uint256","uint256","address",
         "(bytes,uint256,uint256,int256,bytes,(uint256,address,address))","bytes"], d)
    return {"fn": "sendQuoteWithAffiliateAndData",
            "partyBs": partyBs, "symbolId": sid,
            "positionType": pos, "orderType": otype,
            "price": w(price), "quantity": w(qty),
            "cva": w(cva), "lf": w(lf), "partyAmm": w(pa_mm), "partyBmm": w(pb_mm),
            "deadline": dl, "affiliate": aff,
            "notional": w(price) * w(qty),
            "data": data.decode("ascii", errors="replace").strip()}

def decode_close(d):
    qid, price, qty, otype, dl = _decode(
        ["uint256","uint256","uint256","uint8","uint256"], d)
    return {"fn": "requestToClosePosition", "quoteId": qid,
            "closePrice": w(price), "quantity": w(qty),
            "orderType": otype, "deadline": dl}

def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("usage: python 99_decode.py [addmargin|sendquote|close] <hex>")
    if args[0] in ("addmargin","sendquote","close"):
        kind, hx = args[0], args[1]
    else:
        kind, hx = "auto", args[0]

    data = bytes.fromhex(hx.removeprefix("0x"))
    sel, body = data[:4], data[4:]
    if kind == "auto":
        if sel == SEL_ADD_MARGIN_TO_NEXT_VA:          kind = "addmargin"
        elif sel == SEL_SEND_QUOTE_WITH_AFFILIATE_DATA: kind = "sendquote"
        elif sel == SEL_REQUEST_TO_CLOSE_POSITION:     kind = "close"
        else: raise SystemExit(f"unknown selector: 0x{sel.hex()}")
    out = {"addmargin": decode_addmargin,
           "sendquote": decode_sendquote,
           "close":     decode_close}[kind](body)
    for k, v in out.items():
        print(f"  {k:<14} {v}")

if __name__ == "__main__":
    main()
