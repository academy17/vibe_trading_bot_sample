"""
STEP 3 -- Generate a session key and grant delegations on the InstantLayer.

Two separate `grantDelegation` calls happen here (both signed by the user EOA):

  1. session key   -> trading selectors + COH close + session-key convention
  2. TPSL bot      -> COH close selector only

The second one is what the Conditional Orders Handler (COH) checks off-chain
before accepting a TP/SL order.  Without it you get:
  "parent subaccount has not delegated required access to COH for
   selectors=REQUEST_TO_CLOSE_POSITION"

Usage:
    python 03_grant_delegation.py  [hours]          # default 24

Writes `session_pk`, `session_address`, `delegation_expiry` to .state.json.
ONE key signs opens, closes, AND TP/SL.

NOTE: the session private key is stored in `.state.json` in plaintext so
later steps can sign with it; rotate daily and do not commit this file.
"""
import sys, time
from eth_account import Account
from _common import (USER_PRIVATE_KEY, TPSL_BOT_ADDRESS,
                     instant_layer, load_state, require,
                     save_state, send_tx,
                     SEL_ADD_MARGIN_TO_NEXT_VA,
                     SEL_SEND_QUOTE_WITH_AFFILIATE_DATA,
                     SEL_REQUEST_TO_CLOSE_POSITION,
                     SEL_COH_REQUEST_TO_CLOSE,
                     SEL_SESSION_KEY)

def main():
    assert USER_PRIVATE_KEY, "set USER_PRIVATE_KEY env var"
    st = load_state(); require(st, "sub_account")
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    sub   = st["sub_account"]

    session = Account.create()
    expiry  = int(time.time()) + hours * 3600

    # -------------------------------------------------------------------
    # 1) Grant the SESSION KEY everything it needs:
    #   a6d66852 - addMarginToNextVA           (AccountLayer, for opens)
    #   a7f3b34b - sendQuoteWithAffiliateAndData (Symmio core, for opens)
    #   501e891f - requestToClosePosition       (Symmio core, for direct closes)
    #   eaa31b19 - COH's opaque close selector  (for TPSL/CO handler auth)
    #   00000001 - session-key convention (services check isDelegationActive
    #              against this to authenticate API requests from session keys)
    # -------------------------------------------------------------------
    info_session = (
        (sub, False),                   # Account{ addr, isPartyB=false }
        session.address,                # delegatedSigner
        [SEL_ADD_MARGIN_TO_NEXT_VA,
         SEL_SEND_QUOTE_WITH_AFFILIATE_DATA,
         SEL_REQUEST_TO_CLOSE_POSITION,
         SEL_COH_REQUEST_TO_CLOSE,
         SEL_SESSION_KEY],
        expiry,
    )
    tx = instant_layer.functions.grantDelegation(info_session).build_transaction(
        {"gas": 300_000})
    send_tx(USER_PRIVATE_KEY, tx,
            label=f"grantDelegation(sessionKey={session.address})")

    # -------------------------------------------------------------------
    # 2) Grant the TPSL BOT the full close-selector set the COH validates.
    #    The COH's check isn't against just one selector -- it tries
    #    multiple variants, so grant all of them:
    #      501e891f - real requestToClosePosition (Symmio core)
    #      eaa31b19 - COH's opaque close identifier
    #      ee9ef781 - requestToClosePosition with upnlSig overload
    #      00000001 - session-key auth convention
    # -------------------------------------------------------------------
    info_tpsl = (
        (sub, False),
        TPSL_BOT_ADDRESS,
        [SEL_REQUEST_TO_CLOSE_POSITION,
         SEL_COH_REQUEST_TO_CLOSE,
         bytes.fromhex("ee9ef781"),
         SEL_SESSION_KEY],
        expiry,
    )
    tx = instant_layer.functions.grantDelegation(info_tpsl).build_transaction(
        {"gas": 300_000})
    send_tx(USER_PRIVATE_KEY, tx,
            label=f"grantDelegation(tpslBot={TPSL_BOT_ADDRESS})")

    save_state(session_pk=session.key.hex(),
               session_address=session.address,
               delegation_expiry=expiry)
    print(f"session key : {session.address}  (expires {time.ctime(expiry)})")
    print(f"tpsl bot    : {TPSL_BOT_ADDRESS}  (delegated eaa31b19)")

if __name__ == "__main__":
    main()
