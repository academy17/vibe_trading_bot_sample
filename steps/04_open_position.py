"""
STEP 4 -- Open a position AND wait for the real quote_id + va_address.

What each flag means
--------------------
--symbol-id    Numeric id from /api/contract-symbols (e.g. 1 for SYMM on production).
               Run `python 00_prices.py` to see what's tradable.
--quantity     Size of the position in BASE units (e.g. 364 SYMM tokens).
               Gets rounded to the symbol's `quantity_precision`.
--side         "long" (buy) or "short" (sell).  Determines positionType
               and which VA isolation bucket the trade goes into.
--leverage     Integer multiplier.  The margin you actually commit is
               (notional / leverage) + a tiny trading-fee buffer.
--slippage     Percent tolerance for entry price.  For a LONG, you accept
               up to (1 + slippage%) * mark.  For a SHORT, you accept
               down to (1 - slippage%) * mark.
--no-wait      Skip the notifications-WS wait after POSTing.  Use when
               you want fire-and-forget; resolve later with 05_find_va.py.

Example
-------
    python 04_open_position.py \\
        --symbol-id 1 \\
        --quantity  364 \\
        --side      long \\
        --leverage  1 \\
        --slippage  5

    -> opens a $5-ish SYMM long at up to +5% slip, waits ~5-20s for the
       solver's executeTemplate to land, writes positions[<real qid>] to
       state with va_address attached, and exits.

What the flow does
------------------
    1. Fetch mark price (price WS), locked params, and symbol metadata.
    2. Build + sign `addMarginToNextVA` and `sendQuoteWithAffiliateAndData`
       SignedOperations with the session key from state.
    3. POST {addMargin, sendQuote} to /api/instant_trade/instant_open.
    4. Solver returns {"temp_quote_id": -N, "partyBmm": "0"}.
    5. (Unless --no-wait) Subscribe to notifications WS, block until the
       SendQuoteTransaction report arrives with the real quote_id + va_address.
    6. Move positions[<temp_quote_id>] -> positions[<real quote_id>]
       and point last_quote_id at it.

Exposes `open_position()` as a reusable function.
"""
import argparse, sys, time, uuid, json, asyncio
from decimal import Decimal
import requests
from eth_abi import encode as abi_encode
from web3 import Web3
from _common import (ACCOUNT_LAYER, SYMMIO_CORE, AFFILIATE, HEDGER, SOLVER_BASE,
                     NOTIF_WS_URL, NOTIF_APP_NAME,
                     POSITION_LONG, POSITION_SHORT, ORDER_MARKET,
                     VA_ISO_MARKET_LONG, VA_ISO_MARKET_SHORT,
                     encode_add_margin_to_next_va, encode_send_quote,
                     sign_operation, fetch_locked_params, get_symbol,
                     price_of, to_wei,
                     load_state, require, upsert_position, move_position)


def _subscribe_post_and_wait(sub: str, payload: dict, timeout: float = 120.0) -> tuple[dict, dict]:
    """Subscribe to the notifications WS FIRST (matching the UI flow), then
    POST /instant_open, then block until SendQuoteTransaction lands.

    Returns (solver_resp_json, final_report_data).
    """
    import websockets

    async def _run():
        async with websockets.connect(NOTIF_WS_URL) as ws:
            await ws.send(json.dumps({"channel_patterns": [{
                "app_name": NOTIF_APP_NAME, "address": sub,
                "primary_identifier": "*", "secondary_identifier": "*"}]}))
            print(f"[ws] subscribed for {sub}; posting trade ...")

            # POST on an executor so we don't block the event loop while the
            # solver is working.  Any notifications it fires are already being
            # buffered on the open WS.
            loop = asyncio.get_running_loop()
            print(f"[POST] {SOLVER_BASE}/api/instant_trade/instant_open")
            r = await loop.run_in_executor(None, lambda: requests.post(
                f"{SOLVER_BASE}/api/instant_trade/instant_open",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30))
            print(f"[resp] {r.status_code}  {r.text}")
            r.raise_for_status()
            resp = r.json()
            temp = int(resp["temp_quote_id"])
            print(f"[ws] waiting for SendQuoteTransaction(temp={temp}) ...")

            end = time.time() + timeout
            while time.time() < end:
                raw = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
                msg = json.loads(raw)
                d   = msg.get("data") or {}
                print(f"[ws] {d.get('last_seen_action')}  {d}")
                if d.get("temp_quote_id") != temp:
                    continue
                if (d.get("last_seen_action") == "SendQuoteTransaction"
                        and d.get("action_status") == "success"):
                    return resp, d
                # Alerts / failed terminal reports: stop waiting; surface cause.
                if d.get("state_type") == "alert" or d.get("action_status") == "failed":
                    raise RuntimeError(
                        f"solver reported failure for temp={temp}: "
                        f"action={d.get('last_seen_action')} "
                        f"status={d.get('action_status')} "
                        f"error_code={d.get('error_code')} "
                        f"raw={d}")
            raise TimeoutError(f"WS timed out waiting for temp={temp}")

    return asyncio.run(_run())


def open_position(symbol_id: int, quantity: Decimal, side: str, leverage: int,
                  slippage_pct: Decimal = Decimal("5"), wait: bool = True) -> dict:
    """Open a position.  `slippage_pct` is in PERCENT (5 means 5%).

    Entry price:
        LONG:   price = mark * (1 + slippage_pct / 100)   -- accept higher
        SHORT:  price = mark * (1 - slippage_pct / 100)   -- accept lower

    When `wait=True`, blocks until the real quote_id is known and returns
    {"quote_id", "va_address", "temp_quote_id"}.  When `wait=False`,
    returns the raw solver response with `temp_quote_id`.
    """
    st = load_state(); require(st, "sub_account", "session_pk")
    sub, session_pk = st["sub_account"], st["session_pk"]

    side_l       = side.lower()
    if side_l not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")
    position_type = POSITION_LONG if side_l == "long" else POSITION_SHORT
    va_iso        = VA_ISO_MARKET_LONG if position_type == POSITION_LONG else VA_ISO_MARKET_SHORT
    slippage      = slippage_pct / 100

    sym = get_symbol(symbol_id)
    print(f"[symbol] {sym['name']}  price_prec={sym['price_precision']}  "
          f"qty_prec={sym['quantity_precision']}  trading_fee={sym['trading_fee']}")
    price_prec  = int(sym["price_precision"])
    qty_prec    = int(sym["quantity_precision"])
    trading_fee = Decimal(str(sym["trading_fee"]))

    mark = price_of(sym["name"])
    print(f"[price] {sym['name']} mark = {mark}  (price WS)")

    s_mult    = (1 + slippage) if position_type == POSITION_LONG else (1 - slippage)
    req_price = (mark * s_mult).quantize(Decimal(10) ** -price_prec)
    qty       = quantity.quantize(Decimal(10) ** -qty_prec)
    notional  = req_price * qty
    print(f"[trade] side={side_l}  lev={leverage}  slip={slippage_pct}%  "
          f"worst_price={req_price}  qty={qty}  notional={notional}")

    lp = fetch_locked_params(sym["name"], leverage)
    print(f"[locked_params] {lp}")
    # cva / lf / partyAmm / partyBmm use NOTIONAL AT WORST PRICE.  This is the
    # `price` field in the on-chain calldata and what Symmio core's lockQuote
    # uses to validate the locked-on-quote portion.
    cva   = to_wei(notional * Decimal(lp["cva"])      / (100 * leverage))
    lf    = to_wei(notional * Decimal(lp["lf"])       / (100 * leverage))
    pa_mm = to_wei(notional * Decimal(lp["partyAmm"]) / (100 * leverage))
    pb_mm = to_wei(notional * Decimal(lp.get("partyBmm", 0)) / 100)

    # addMargin sizing matches the production UI's empirical formula:
    #
    #   LONG:  addMargin = worst * qty / leverage * (1 + 2*fee)
    #          where worst = mark * (1 + slip).  worst is already the upper
    #          bound on fill price, so locked margin sized at it covers any
    #          worst-case fill; only the 2*fee open+close buffer sits on top.
    #
    #   SHORT: addMargin = mark * SHORT_BUFFER * qty / leverage * (1 + 2*fee)
    #          where SHORT_BUFFER = 1.10  (a hardcoded UI policy of +10%
    #          above mark, applied uniformly across all slippages and
    #          leverages).  The contract's strict minimum is just
    #          mark*qty/leverage; the +10% is over-collateralization the
    #          UI bakes in to handle upward drift between
    #          signing and fill, since a short's margin requirement scales
    #          with mark.  
    SHORT_BUFFER = Decimal("1.10")
    if position_type == POSITION_LONG:
        upper_margin_price = req_price                          # = mark*(1+slip)
    else:
        upper_margin_price = mark * SHORT_BUFFER
    upper_margin_notional = upper_margin_price * qty
    base_margin = upper_margin_notional / Decimal(leverage)
    margin_wei = to_wei(base_margin * (Decimal(1) + 2 * trading_fee))
    print(f"[margin] worst={req_price}  upper_margin_price={upper_margin_price}  "
          f"base={base_margin}  fee_buffer={trading_fee*2*100:.4f}%  "
          f"addMargin_wei={margin_wei}  (={Decimal(margin_wei)/Decimal(10**18)} USDC)")

    deadline = int(time.time()) + 3600
    add_call = encode_add_margin_to_next_va(sub, va_iso, symbol_id, margin_wei)
    add_op   = sign_operation(session_pk, ACCOUNT_LAYER, add_call,
                              account_addr=sub, deadline=deadline)
    send_call = encode_send_quote(
        symbol_id=symbol_id, position_type=position_type, order_type=ORDER_MARKET,
        price_wei=to_wei(req_price), quantity_wei=to_wei(qty),
        cva=cva, lf=lf, pa_mm=pa_mm, pb_mm=pb_mm, deadline=deadline,
        affiliate=AFFILIATE, hedger=HEDGER,
        data_bytes=abi_encode(["(string)"], [(str(uuid.uuid4()),)]))
    send_op = sign_operation(session_pk, SYMMIO_CORE, send_call,
                             account_addr=sub, deadline=deadline)

    payload = {"addMargin": add_op, "sendQuote": send_op}

    def _record(tqid):
        upsert_position(tqid, {
            "symbol_id":     symbol_id,
            "symbol_name":   sym["name"],
            "quantity":      str(qty),
            "position_type": position_type,
            "va_iso":        va_iso,
            "opened_at":     int(time.time()),
            "temp_quote_id": tqid,
        })

    if not wait:
        print(f"[POST] {SOLVER_BASE}/api/instant_trade/instant_open")
        r = requests.post(f"{SOLVER_BASE}/api/instant_trade/instant_open",
                          json=payload, headers={"Content-Type": "application/json"},
                          timeout=30)
        print(f"[resp] {r.status_code}  {r.text}")
        r.raise_for_status()
        resp = r.json()
        tqid = int(resp["temp_quote_id"])
        _record(tqid)
        print(f"[skip-wait] temp_quote_id={tqid}; run 05_find_va.py to resolve.")
        return resp

    # wait=True: subscribe first, POST inside the same WS session, then listen.
    try:
        resp, d = _subscribe_post_and_wait(sub, payload)
    except requests.HTTPError:
        raise
    except Exception as e:
        # POST may already have succeeded; try to recover temp_quote_id if we
        # got that far by re-reading state (not the cleanest, but keeps the old
        # safety net where state is left with a stub for 05_find_va.py).
        print(f"[wait] failed: {e}  -- run 05_find_va.py to recover.")
        raise

    tqid = int(resp["temp_quote_id"])
    _record(tqid)
    qid  = int(d["quote_id"])
    va   = Web3.to_checksum_address(d["va_address"])
    # Persist both the real quote_id (so downstream steps don't need to
    # re-derive it) and the va_address under the new key.  move_position
    # already bumps last_quote_id.
    move_position(tqid, qid, extra={"quote_id": qid, "va_address": va})
    print(f"[done] quote_id={qid}  va={va}  (state.last_quote_id={qid})")
    return {"temp_quote_id": tqid, "quote_id": qid, "va_address": va}


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    p.add_argument("--symbol-id", type=int, required=True,
                   help="Numeric id from /bsapi/contract-symbols")
    p.add_argument("--quantity",  type=Decimal, required=True,
                   help="Size in BASE units (e.g. 364 for 364 SYMM)")
    p.add_argument("--side",      choices=["long", "short"], required=True,
                   help="Direction of the trade")
    p.add_argument("--leverage",  type=int, required=True,
                   help="Integer leverage multiplier (>=1)")
    p.add_argument("--slippage",  type=Decimal, default=Decimal("5"),
                   help="Entry price slippage in PERCENT (default: 5)")
    p.add_argument("--no-wait",   action="store_true",
                   help="Don't block on the notifications WS after POST")
    a = p.parse_args()
    open_position(a.symbol_id, a.quantity, a.side, a.leverage,
                  slippage_pct=a.slippage, wait=not a.no_wait)


if __name__ == "__main__":
    main()
