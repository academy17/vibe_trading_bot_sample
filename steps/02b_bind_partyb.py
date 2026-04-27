"""
STEP 2b -- Bind the sub-account to a partyB (one-time setup).

Before the Instant Layer trade flow works, the sub-account must be bound to
a specific partyB (the hedger). Without a bind, Symmio core's `sendQuote`
runs full LibMuon signature validation, which rejects the solver's empty
upnlSig sentinel with "LibMuon: Expired signature".

Once bound, the sub-account trusts that partyB for subsequent trades and the
Muon validation is skipped on the instant path -- which is what the solver's
template flow expects.

Usage:
    python 02b_bind_partyb.py

Signs and sends `AccountLayer._call(sub_account, [bindToPartyB(HEDGER)])`
from the user EOA.
"""
from eth_abi import encode as abi_encode
from eth_account import Account
from _common import (USER_PRIVATE_KEY, HEDGER, account_layer, w3,
                     load_state, require, send_tx)


SEL_BIND_TO_PARTYB = bytes.fromhex("cf462cb2")  # bindToPartyB(address)


def main():
    assert USER_PRIVATE_KEY, "set USER_PRIVATE_KEY env var"
    st = load_state(); require(st, "sub_account")
    sub = st["sub_account"]
    user = Account.from_key(USER_PRIVATE_KEY)

    # Already bound? skip.
    from _common import SYMMIO_CORE
    import json
    symmio = w3.eth.contract(
        address=SYMMIO_CORE,
        abi=json.load(open(__file__.replace("02b_bind_partyb.py", "abi/symmio.json"))))
    bs = symmio.functions.getBindState(sub).call()
    if bs[0] == 1:
        print(f"[skip] already bound to {bs[1]} at ts={bs[2]}")
        return

    bind_cd = SEL_BIND_TO_PARTYB + abi_encode(["address"], [HEDGER])
    tx = account_layer.functions._call(sub, [bind_cd]).build_transaction(
        {"from": user.address, "gas": 600_000})
    send_tx(USER_PRIVATE_KEY, tx, label=f"_call(bindToPartyB({HEDGER}))")

    bs2 = symmio.functions.getBindState(sub).call()
    print(f"[done] bind state: status={bs2[0]}  partyB={bs2[1]}  ts={bs2[2]}")


if __name__ == "__main__":
    main()
