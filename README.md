# Step-by-step scripts

Each file runs independently.  Setup-once steps (01, 02b) stay valid
forever; session steps (03) last until the key expires (typically 24 h);
trading steps (04-07) can be re-run as often as you like.  Multiple open
positions are fine — every trading action is keyed by `quote_id`.

```
_common.py                 shared config / ABIs / helpers / state I/O
00_prices.py               one-shot snapshot from the price websocket (debug)
01_create_subaccount.py    on-chain: createSubAccounts  (singleVAMode=True)
02_deposit.py              on-chain: approve + depositForAccount
02b_bind_partyb.py         on-chain: _call(bindToPartyB)  (one-time; skips LibMuon)
03_grant_delegation.py     on-chain: grantDelegation × 2 (session key + TPSL bot)
04_open_position.py        open a position; WAITS for real quote_id + va_address
05_find_va.py              recovery tool: resolve quote_id if step 04 lost the WS
06_close_position.py       POST /api/instant_trade/instant_close (by quote_id)
07_set_tpsl.py             POST /api/v5/ ConditionalOrder (by quote_id)
08_watch.py                live stream of the notifications websocket
09_positions.py            list all positions currently tracked in state
99_decode.py               decode a captured callData for debugging
```

---

## Setup (once)

```bash
cd steps

pip install -r requirements.txt

cp .env.example .env
# edit .env and paste your wallet's private key into USER_PRIVATE_KEY
# obtain solver specific endpoints from "How to build a Trading Bot on Vibe" documentation
```

`.env` is loaded automatically by `_common.py` - no shell `export`s
needed.  `.env` and `.state.json` are both ignored by git.

---

## How `.state.json` works

Every script in this folder both **reads** the config it needs and
**writes** anything the next step will need into a single file:
`steps/.state.json`.  You don't need to pass addresses, session keys,
or quote ids between scripts — they're carried automatically.

You don't have to run the steps in the same terminal session, or even
the same day.  The file is plain JSON, so you can also edit it by hand
if anything goes wrong.

### What each step puts in there

| Step | Writes / Rewrites                                                                 |
|------|-----------------------------------------------------------------------------------|
| 01   | `sub_account`, `owner`, `isolation_type`  (sub-account has `singleVAMode=True`)   |
| 02   | nothing (on-chain side effect only)                                               |
| 02b  | nothing (on-chain side effect only: sub-account bound to hedger partyB)           |
| 03   | `session_pk`, `session_address`, `delegation_expiry` (sends **two** grantDelegation txs: one to the session key, one to the TPSL bot) |
| 04   | Writes stub `positions[<temp_quote_id>]` immediately after the POST succeeds, THEN waits on the notifications WS and moves the record to `positions[<real quote_id>]` with `quote_id` + `va_address` attached and `last_quote_id` updated.  One step, end-to-end. |
| 05   | **Recovery only.**  If step 04 lost the WS mid-open, this moves `positions[<temp_quote_id>]` -> `positions[<real quote_id>]` and attaches `quote_id` + `va_address`. |
| 06   | nothing (close is fire-and-forget)                                                |
| 07   | nothing (TP/SL is fire-and-forget)                                                |

### Example after a full run

```json
{
  "sub_account":      "0xA4dC48D26D20d758Afa2bC23F96D768287436189",
  "owner":            "0x66ddbC60868cdC3dFb66398d7F452B18F3695b9a",
  "isolation_type":   2,
  "session_pk":       "0x...64-hex...",
  "session_address":  "0x633A69CD4CfE7aA9A5d00A4544c2aa31613cB5F2",
  "delegation_expiry": 1777030592,

  "positions": {
    "5544": {
      "symbol_id":     1,
      "symbol_name":   "SYMM::80..5f_SFLOW",
      "quantity":      "364.000000",
      "position_type": 0,
      "va_iso":        2,
      "va_address":    "0x348ECAD961d2369393a2E3657B40b8D061B5E460",
      "quote_id":      5544,
      "opened_at":     1776945120,
      "temp_quote_id": -6188
    }
  },
  "last_quote_id": "5544"
}
```

Delete `.state.json` to start completely fresh.

> The session private key is stored plaintext in this file so later
> steps can sign with it automatically.  Rotate daily (re-run step 03
> — it generates a new key and sends two fresh grant txs) and don't
> commit `.state.json` (it's in `.gitignore`).

---

## Typical run (one position)

```bash
# --- one-time per sub-account ---
python 01_create_subaccount.py  my-strategy  2   # 2 = MARKET_DIRECTION, singleVAMode=True
python 02_deposit.py 50                           # 50 USDC in
python 02b_bind_partyb.py                         # bind to hedger partyB (skip LibMuon)

# --- per session (typically daily) ---
python 03_grant_delegation.py 24                  # 24-hour session key + TPSL bot delegation

# --- per trade ---
python 00_prices.py SYMM                          # sanity-check the mark price
python 04_open_position.py --symbol-id 1 --quantity 364 --side long --leverage 1 --slippage 5
python 07_set_tpsl.py --tp 0.022 --sl 0.011       # TP+SL (quantized automatically)

# when done:
python 06_close_position.py                       # closes last_quote_id at 5% slip
```

Flag reference (all trading commands support `--help`):

```
04_open_position.py
    --symbol-id   numeric id from /bsapi/contract-symbols
    --quantity    size in base units (e.g. 364 SYMM)
    --side        long | short
    --leverage    integer multiplier
    --slippage    PERCENT, default 5
    --no-wait     skip the notifications-WS wait after POST

06_close_position.py
    --quote       quote_id (default: last_quote_id)
    --slippage    PERCENT, default 5 (clamped to 99.999%)
    --list        print open positions and exit

07_set_tpsl.py
    --tp          take-profit trigger price (or "-" to omit)
    --sl          stop-loss trigger price   (or "-" to omit)
    --quote       quote_id (default: last_quote_id)
```

`04_open_position.py` signs both operations, subscribes to the
notifications WS **first** (avoiding the race where notifications fire
before we're listening), POSTs to the solver inside that same WS
session, then blocks until the on-chain `SendQuoteTransaction` arrives
(~5-20 s) — at which point it records the real `quote_id` and
`va_address` into state and exits.  You get a ready-to-use position
out of a single command.

If you're scripting or don't want to block, pass `--no-wait` and use
`05_find_va.py` later to resolve.

## Multiple positions (same sub-account)

With `singleVAMode=True` (the default set by step 01), **all trades on
the same `(symbol, direction)` key reuse the same VA**.  A second long
on symbol 1 lands on the same VA as the first; a short on symbol 1
creates a new VA (different direction).  Margin added for the second
quote accumulates on the same VA, and both quotes are tracked under it.

```bash
python 04_open_position.py --symbol-id 1 --quantity 364 --side long  --leverage 1 --slippage 5
python 04_open_position.py --symbol-id 1 --quantity 200 --side long  --leverage 1 --slippage 5
# both quotes land on the same VA (MARKET_LONG, symbol 1)

python 04_open_position.py --symbol-id 1 --quantity 200 --side short --leverage 1 --slippage 5
# this one creates a new VA (MARKET_SHORT, symbol 1)

python 09_positions.py
#    QID  SYMBOL                      DIR    QTY             VA / temp
#   5544  SYMM::80..5f_SFLOW          long   364.000000      0x348E...E460
#   5660  SYMM::80..5f_SFLOW          long   200.000000      0x348E...E460   <- same VA
#   5662  SYMM::80..5f_SFLOW          short  200.000000      0xabcd...       <- different VA

python 07_set_tpsl.py --tp 0.022 --sl 0.011 --quote 5544
python 06_close_position.py --quote 5660                     # close one long at 5% slip
python 06_close_position.py --quote 5662 --slippage 10       # close the short at 10% slip
```

Each `quote_id` is an independent position within its VA.  TP/SL and
close commands take a `--quote` flag to target a specific one.  If you
omit `--quote`, they use `last_quote_id` from state.

## Using the open / close / TP helpers 

`open_position()`, `close_quote()`, and `set_tpsl()` are exported from
the step files:

```python
from decimal import Decimal
from importlib import import_module
from _common import POSITION_LONG, POSITION_SHORT

open_p      = import_module("04_open_position").open_position
close_quote = import_module("06_close_position").close_quote
set_tpsl    = import_module("07_set_tpsl").set_tpsl

# Open and wait for the real qid + va_address:
result = open_p(symbol_id=1, quantity=Decimal("364"),
                side="long", leverage=1,
                slippage_pct=Decimal("5"))    # slippage in PERCENT
qid    = result["quote_id"]                   # resolved via WS
va     = result["va_address"]

set_tpsl(quote_id=qid, tp_price=Decimal("0.022"), sl_price=Decimal("0.011"))
close_quote(quote_id=qid, slippage_pct=Decimal("10"))
```

---
