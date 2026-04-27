"""
STEP 8 -- Stream the notifications websocket for your sub-account.

Usage:
    python 08_watch.py                # watch forever
    python 08_watch.py 60              # watch for 60 seconds then exit

Prints every message with a timestamped `last_seen_action`.  Useful for:
  - resolving temp_quote_id -> quote_id + va_address after open
  - confirming fills, cancels, TP/SL triggers, liquidations
  - debugging why a trade didn't materialize
"""
import sys, json, time, asyncio
from _common import NOTIF_WS_URL, NOTIF_APP_NAME, load_state, require

def main():
    st = load_state(); require(st, "sub_account")
    sub     = st["sub_account"]
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 10**9

    import websockets

    async def _run():
        async with websockets.connect(NOTIF_WS_URL) as ws:
            await ws.send(json.dumps({"channel_patterns":[{
                "app_name": NOTIF_APP_NAME, "address": sub,
                "primary_identifier":"*", "secondary_identifier":"*"}]}))
            print(f"[ws] subscribed to {sub}")
            end = time.time() + timeout
            while time.time() < end:
                raw = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
                m = json.loads(raw)
                d = m.get("data") or {}
                print(f"{time.strftime('%H:%M:%S')}  "
                      f"{d.get('last_seen_action','?'):<25}  {d}")

    try: asyncio.run(_run())
    except KeyboardInterrupt: print("bye")

if __name__ == "__main__":
    main()
