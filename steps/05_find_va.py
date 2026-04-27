"""
STEP 5 (recovery helper) -- Resolve the real quote_id + Virtual Account AFTER the fact.

The normal path is `04_open_position.py` itself, which now waits on the
notifications WS and writes the real quote_id + va_address into state
before it exits.  You only need this script when:

  * You ran `04_open_position.py --no-wait` and chose to resolve later.
  * The WS timed out or your machine dropped the connection mid-open and
    you have a stub `positions[<temp_quote_id>]` record stuck in state.
  * You want to confirm an open from on-chain views directly, bypassing
    the notifications service entirely.

Usage:

  python 05_find_va.py ws [temp_quote_id]
      Subscribe to the notifications WS and block until SendQuoteTransaction
      arrives.  If temp_quote_id is omitted, uses `last_quote_id` from state.

  python 05_find_va.py onchain [temp_quote_id]
      Scan AccountLayer views: getActiveVAByKey + getVirtualAccountQuoteIds.

Rewrites state.json so the position previously under
`positions[<temp_quote_id>]` is moved to `positions[<real quote_id>]`
with `va_address` attached, and `last_quote_id` points at the real one.
"""
import sys, json, time, asyncio
from _common import (account_layer, NOTIF_WS_URL, NOTIF_APP_NAME,
                     load_state, require, move_position, get_position)
from web3 import Web3


def _temp_id_from_argv_or_state() -> int:
    if len(sys.argv) > 2:
        return int(sys.argv[2])
    last = load_state().get("last_quote_id")
    if last is None or not str(last).lstrip("-").isdigit():
        raise SystemExit("no temp_quote_id given and none in state")
    return int(last)


def via_ws():
    import websockets
    st = load_state(); require(st, "sub_account")
    sub  = st["sub_account"]
    temp = _temp_id_from_argv_or_state()

    async def _run():
        async with websockets.connect(NOTIF_WS_URL) as ws:
            await ws.send(json.dumps({"channel_patterns": [{
                "app_name": NOTIF_APP_NAME, "address": sub,
                "primary_identifier": "*", "secondary_identifier": "*"}]}))
            print(f"[ws] subscribed; waiting for SendQuoteTransaction(temp={temp}) ...")
            end = time.time() + 120
            while time.time() < end:
                raw = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
                msg = json.loads(raw)
                d = msg.get("data") or {}
                print(f"[ws] {d.get('last_seen_action')}  {d}")
                if (d.get("temp_quote_id") == temp
                        and d.get("last_seen_action") == "SendQuoteTransaction"
                        and d.get("action_status") == "success"):
                    return d
        raise TimeoutError("WS timed out")

    d  = asyncio.run(_run())
    qid = int(d["quote_id"])
    va  = Web3.to_checksum_address(d["va_address"])
    move_position(temp, qid, extra={"quote_id": qid, "va_address": va})
    print(f"quote_id={qid}  va={va}  (state.last_quote_id={qid})")


def via_onchain():
    st = load_state(); require(st, "sub_account")
    temp   = _temp_id_from_argv_or_state()
    _, pos = get_position(temp)
    sub    = st["sub_account"]
    iso    = int(pos["va_iso"])
    sid    = int(pos["symbol_id"])

    active = account_layer.functions.getActiveVAByKey(sub, iso, sid).call()
    print(f"[view] getActiveVAByKey({sub}, iso={iso}, sid={sid}) = {active}")
    if active == "0x" + "00" * 20:
        raise SystemExit("no active VA for this key yet; try `ws` mode instead.")

    qids = account_layer.functions.getVirtualAccountQuoteIds(active, 0, 500).call()
    print(f"[view] quoteIds on {active}: {qids}")
    if not qids:
        raise SystemExit("VA has no quote ids yet; template may not have landed.")
    qid = max(qids)
    move_position(temp, qid, extra={"quote_id": qid, "va_address": active})
    print(f"quote_id={qid}  va={active}  (state.last_quote_id={qid})")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ws"
    if mode == "ws":        via_ws()
    elif mode == "onchain": via_onchain()
    else: raise SystemExit("mode must be 'ws' or 'onchain'")


if __name__ == "__main__":
    main()
