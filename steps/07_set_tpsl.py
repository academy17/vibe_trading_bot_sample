"""
STEP 7 -- Set a Take-Profit / Stop-Loss on an open position.

What each flag means
--------------------
--tp       Take-profit trigger price (absolute, in QUOTE units).  Omit
           or pass "-" to leave the TP leg empty.
--sl       Stop-loss trigger price (absolute, in QUOTE units).  Omit
           or pass "-" to leave the SL leg empty.
--quote    quote_id to attach the order to.  If omitted, uses
           `last_quote_id` from state.

At least one of --tp / --sl must be supplied.  The "quantity" and
"price" fields on the signed message are filled in automatically from
the position record in .state.json and the current mark price.

Examples
--------
    python 07_set_tpsl.py --tp 0.02                       # TP only, last_quote_id
    python 07_set_tpsl.py --tp 0.02 --sl 0.01             # both legs
    python 07_set_tpsl.py --sl 0.01 --quote 4698          # SL only, specific quote

Exposes `set_tpsl()` as a reusable function.
"""
import argparse, json, secrets
from decimal import Decimal
from typing import Optional
import requests
from eth_account import Account
from web3 import Web3
from _common import (AFFILIATE, CHAIN_ID, INSTANT_LAYER, TPSL_BASE, TPSL_APP_NAME,
                     ORDER_MARKET, get_symbol, price_of,
                     load_state, require, get_position)

CONDITIONAL_ORDER_DOMAIN = {
    "name": "ConditionalOrder", "version": "1",
    "chainId": CHAIN_ID, "verifyingContract": INSTANT_LAYER}
CONDITIONAL_ORDER_TYPES = {
    "EIP712Domain":[{"name":"name","type":"string"},{"name":"version","type":"string"},
                    {"name":"chainId","type":"uint256"},{"name":"verifyingContract","type":"address"}],
    "ConditionalOrder":[{"name":"virtualAccount","type":"address"},
                        {"name":"subAccount","type":"address"},
                        {"name":"salt","type":"uint256"},
                        {"name":"quoteId","type":"int256"},
                        {"name":"symbolId","type":"uint256"},
                        {"name":"positionType","type":"uint8"},
                        {"name":"affiliate","type":"address"},
                        {"name":"takeProfit","type":"TakeProfit"},
                        {"name":"stopLoss","type":"StopLoss"},
                        {"name":"sendQuote","type":"SendQuote"}],
    "TakeProfit":[{"name":"quantity","type":"string"},{"name":"price","type":"string"},
                  {"name":"orderType","type":"uint8"},{"name":"conditionalPrice","type":"string"},
                  {"name":"conditionalPriceType","type":"string"}],
    "StopLoss":[{"name":"quantity","type":"string"},{"name":"price","type":"string"},
                {"name":"orderType","type":"uint8"},{"name":"conditionalPrice","type":"string"},
                {"name":"conditionalPriceType","type":"string"}],
    "SendQuote":[{"name":"quantity","type":"string"},{"name":"price","type":"string"},
                 {"name":"orderType","type":"uint8"},{"name":"conditionalPrice","type":"string"},
                 {"name":"conditionalPriceType","type":"string"},{"name":"leverage","type":"uint256"}]}
ZERO_LEG  = {"quantity":"0", "price":"0", "orderType":0,
             "conditionalPrice":"0", "conditionalPriceType":"market"}
ZERO_SEND = {**ZERO_LEG, "leverage":0}


def fetch_signing_spec() -> dict:
    r = requests.get(f"{TPSL_BASE}/api/v5/signing-spec",
                     headers={"App-Name": TPSL_APP_NAME}, timeout=15)
    return r.json()


def set_tpsl(quote_id=None,
             tp_price: Optional[Decimal] = None,
             sl_price: Optional[Decimal] = None) -> dict:
    if tp_price is None and sl_price is None:
        raise ValueError("at least one of tp_price / sl_price must be set")
    st = load_state(); require(st, "sub_account", "session_pk")
    sub, session_pk = st["sub_account"], st["session_pk"]

    qid, pos = get_position(quote_id)
    for k in ("symbol_id", "quantity", "position_type", "va_address"):
        if k not in pos:
            raise SystemExit(f"positions[{qid}] missing '{k}'; run step 05.")
    symbol_id = int(pos["symbol_id"])
    qty       = Decimal(pos["quantity"])
    pos_type  = int(pos["position_type"])
    va        = pos["va_address"]

    sym  = get_symbol(symbol_id)
    mark = price_of(sym["name"])
    # Quantize to the symbol's precisions; the COH rejects unbounded decimals
    # with error 407 "provided values do not meet the required precision".
    price_prec = int(sym["price_precision"])
    qty_prec   = int(sym["quantity_precision"])
    mark_q = mark.quantize(Decimal(10) ** -price_prec)
    qty_q  = qty.quantize(Decimal(10) ** -qty_prec)
    def _qp(x):
        if x is None: return None
        return Decimal(x).quantize(Decimal(10) ** -price_prec)
    tp_q = _qp(tp_price)
    sl_q = _qp(sl_price)
    print(f"[tpsl] qid={qid}  symbol={sym['name']}  mark={mark_q}  qty={qty_q}  "
          f"TP={tp_q}  SL={sl_q}")

    def leg(trig):
        if trig is None: return ZERO_LEG
        return {"quantity": str(qty_q), "price": str(mark_q),
                "orderType": ORDER_MARKET,
                "conditionalPrice": str(_qp(trig)),
                "conditionalPriceType": "last_close"}

    salt_int = secrets.randbits(256)
    message = {
        "virtualAccount": Web3.to_checksum_address(va),
        "subAccount":     Web3.to_checksum_address(sub),
        "salt":           salt_int,
        "quoteId":        int(qid),
        "symbolId":       symbol_id,
        "positionType":   pos_type,
        "affiliate":      AFFILIATE,
        "takeProfit":     leg(tp_price),
        "stopLoss":       leg(sl_price),
        "sendQuote":      ZERO_SEND,
    }
    typed = {"domain": CONDITIONAL_ORDER_DOMAIN, "types": CONDITIONAL_ORDER_TYPES,
             "primaryType": "ConditionalOrder", "message": message}

    sk  = Account.from_key(session_pk)
    sig = sk.sign_typed_data(full_message=typed).signature.hex()
    if not sig.startswith("0x"): sig = "0x" + sig

    # salt is a decimal STRING.
    wire_typed = json.loads(json.dumps(typed, default=str))
    wire_typed["message"]["salt"] = str(salt_int)

    print(f"[POST] {TPSL_BASE}/api/v5/")
    r = requests.post(f"{TPSL_BASE}/api/v5/",
        json={"typedData": wire_typed, "signer": sk.address, "signature": sig},
        headers={"App-Name": TPSL_APP_NAME, "Content-Type": "application/json"},
        timeout=15)
    print(f"[resp] {r.status_code}  {r.text}")
    return r.json() if r.ok else {}


def _parse_price(s: Optional[str]) -> Optional[Decimal]:
    if s is None or s in ("-", "none", "None", ""):
        return None
    return Decimal(s)


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    p.add_argument("--tp",    type=str, default=None,
                   help="Take-profit trigger price (or '-' to omit)")
    p.add_argument("--sl",    type=str, default=None,
                   help="Stop-loss trigger price (or '-' to omit)")
    p.add_argument("--quote", type=int, default=None,
                   help="quote_id to attach (default: last_quote_id in state)")
    a = p.parse_args()
    tp, sl = _parse_price(a.tp), _parse_price(a.sl)
    if tp is None and sl is None:
        p.error("at least one of --tp / --sl must be supplied")
    set_tpsl(a.quote, tp, sl)


if __name__ == "__main__":
    main()
