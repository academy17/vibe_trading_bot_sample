"""
STEP 1 -- Create a SubAccount on the AccountLayer.

Usage:
    python 01_create_subaccount.py  [name]  [isolation_type]

    name            default "bot-demo"
    isolation_type  default 2 (MARKET_DIRECTION).
                    0=POSITION, 1=MARKET, 2=MARKET_DIRECTION, 3=CUSTOM

`singleVAMode=True` is REQUIRED for the TPSL / Conditional Orders Handler
flow to work: the COH validates that the position's VA matches
`predictNextVirtualAccountAddress(sub, iso, symbol)`.  With singleVAMode
off, each quote creates a fresh VA address and the "next predicted" VA
will never equal the VA your already-open position lives on.

Writes `sub_account` to .state.json.
"""
import sys
from _common import (USER_PRIVATE_KEY, AFFILIATE, SYMMIO_CORE,
                     account_layer, send_tx, save_state,
                     SUB_ISO_MARKET_DIRECTION)
from eth_account import Account

def main():
    assert USER_PRIVATE_KEY, "set USER_PRIVATE_KEY env var"
    name           = sys.argv[1] if len(sys.argv) > 1 else "bot-demo"
    isolation_type = int(sys.argv[2]) if len(sys.argv) > 2 else SUB_ISO_MARKET_DIRECTION

    user = Account.from_key(USER_PRIVATE_KEY)
    creation = {
        "name": name, "metadata": b"", "symmioCore": SYMMIO_CORE,
        "isolationType": isolation_type, "singleVAMode": True,
    }
    tx = account_layer.functions.createSubAccounts(
        AFFILIATE, [creation]).build_transaction({"from": user.address})
    send_tx(USER_PRIVATE_KEY, tx, label=f"createSubAccounts({name})")

    subs = account_layer.functions.getUserSubAccountsAddresses(
        user.address, 0, 200).call()
    print(f"sub-accounts for {user.address}: {subs}")
    save_state(sub_account=subs[-1], isolation_type=isolation_type,
               owner=user.address)
    print(f"NEW sub-account: {subs[-1]}")

if __name__ == "__main__":
    main()
