"""
STEP 6 -- Close an open position via the instant route.

What each flag means
--------------------
--quote        quote_id to close.  If omitted, uses `last_quote_id` from state.
--slippage     Worst-acceptable price tolerance in PERCENT (default: 5).
               LONG close:  closePrice = mark * (1 - slippage/100)   (sell lower)
               SHORT close: closePrice = mark * (1 + slippage/100)   (buy higher)
               Clamped to 99.999% so price never rounds to 0.
--list         Print a table of open positions and exit (no close).

Examples
--------
    python 06_close_position.py                           # close last_quote_id, 5% slip
    python 06_close_position.py --quote 4698              # specific quote
    python 06_close_position.py --quote 4698 --slippage 10
    python 06_close_position.py --list

Reads positions[<quote_id>] from .state.json:
    symbol_id, quantity, position_type, va_address.

signerAccount.addr = VIRTUAL ACCOUNT (not the sub-account).
Request body is a JSON ARRAY of one wrapped SignedOperation.

Exposes `close_quote()` as a reusable function.
"""
import argparse, time
from decimal import Decimal
import requests
from _common import (SYMMIO_CORE, SOLVER_BASE, POSITION_LONG,
                     encode_close, sign_operation, get_symbol, price_of,
                     to_wei, load_state, require, get_position, list_positions)


def close_quote(quote_id=None, slippage_pct: Decimal = Decimal("5")) -> dict:
    """Build + sign + POST the close SignedOperation.

    `slippage_pct` is in PERCENT (5 means 5%).  For a LONG close the worst
    acceptable price is mark*(1 - slippage_pct/100); for a SHORT close it's
    mark*(1 + slippage_pct/100)."""
    st = load_state(); require(st, "session_pk")
    session_pk = st["session_pk"]

    qid, pos = get_position(quote_id)
    for k in ("symbol_id", "quantity", "position_type", "va_address"):
        if k not in pos:
            raise SystemExit(f"positions[{qid}] missing '{k}'; run step 05.")

    symbol_id = int(pos["symbol_id"])
    qty_in    = Decimal(pos["quantity"])
    pos_type  = int(pos["position_type"])
    va        = pos["va_address"]

    slip = min(slippage_pct / 100, Decimal("0.99999"))
    sym  = get_symbol(symbol_id)
    price_prec, qty_prec = int(sym["price_precision"]), int(sym["quantity_precision"])

    mark = price_of(sym["name"])
    mult = (1 - slip) if pos_type == POSITION_LONG else (1 + slip)
    px   = (mark * mult).quantize(Decimal(10) ** -price_prec)
    qty  = qty_in.quantize(Decimal(10) ** -qty_prec)
    print(f"[close] qid={qid}  symbol={sym['name']}  "
          f"dir={'long' if pos_type == POSITION_LONG else 'short'}")
    print(f"        qty={qty}  mark={mark}  worst_closePrice={px}  "
          f"slip={slippage_pct}%  va={va}")

    deadline = int(time.time()) + 3600
    call     = encode_close(int(qid), to_wei(px), to_wei(qty), deadline)
    op       = sign_operation(session_pk, SYMMIO_CORE, call, account_addr=va,
                              deadline=deadline)

    print(f"[POST] {SOLVER_BASE}/api/instant_trade/instant_close")
    r = requests.post(f"{SOLVER_BASE}/api/instant_trade/instant_close",
                      json=[op], headers={"Content-Type": "application/json"},
                      timeout=30)
    print(f"[resp] {r.status_code}  {r.text}")
    return r.json() if r.ok else {}


def _list():
    ps = list_positions()
    if not ps:
        print("no positions in state")
        return
    for qid, p in ps.items():
        dir_ = "long" if p.get("position_type") == 0 else "short"
        print(f"  {qid:>6}  {p.get('symbol_name','?'):<26}  {dir_:<5}  "
              f"qty={p.get('quantity')}  va={p.get('va_address','-')}")


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    p.add_argument("--quote",    type=int, default=None,
                   help="quote_id to close (default: last_quote_id in state)")
    p.add_argument("--slippage", type=Decimal, default=Decimal("5"),
                   help="Worst-acceptable price tolerance in PERCENT (default: 5)")
    p.add_argument("--list",     action="store_true",
                   help="List open positions and exit")
    a = p.parse_args()
    if a.list:
        _list()
        return
    close_quote(a.quote, slippage_pct=a.slippage)


if __name__ == "__main__":
    main()
