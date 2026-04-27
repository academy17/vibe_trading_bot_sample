"""
STEP 2 -- Approve collateral + depositForAccount.

Usage:
    python 02_deposit.py  <amount_in_collateral_units>

    e.g. `python 02_deposit.py 20` deposits 20 USDC (in human-readable units;
    the bot reads `decimals()` from the collateral token at startup, so this
    works for both 6-decimal USDC and 18-decimal stablecoins).

Reads `sub_account` from .state.json.

Approves **Symmio Core** as the spender (not AccountLayer): the actual
ERC20.transferFrom inside `depositForAccount` is called from the Symmio
core diamond, so that's the contract that needs allowance.
"""
import sys
from decimal import Decimal
from _common import (USER_PRIVATE_KEY, ACCOUNT_LAYER, SYMMIO_CORE,
                     account_layer, collateral,
                     load_state, require, send_tx, to_wei, w3,
                     to_collateral_units, from_collateral_units,
                     COLLATERAL_DECIMALS)
from eth_account import Account

def main():
    assert USER_PRIVATE_KEY, "set USER_PRIVATE_KEY env var"
    st = load_state(); require(st, "sub_account")
    if len(sys.argv) < 2:
        raise SystemExit("usage: python 02_deposit.py <amount_in_collateral_units>")

    # depositForAccount expects amount in the TOKEN'S NATIVE DECIMALS (no
    # internal scaling on this deployment). 
    amount_native = to_collateral_units(Decimal(sys.argv[1]))
    user          = Account.from_key(USER_PRIVATE_KEY)
    sub           = st["sub_account"]

    raw_balance = collateral.functions.balanceOf(user.address).call()
    print(f"[balance] wallet = {from_collateral_units(raw_balance)} "
          f"(token decimals={COLLATERAL_DECIMALS})")

    # 2a) approve Symmio Core (the actual transferFrom spender) if needed.
    cur_allow = collateral.functions.allowance(user.address, SYMMIO_CORE).call()
    if cur_allow < amount_native:
        tx = collateral.functions.approve(SYMMIO_CORE, 2**256 - 1).build_transaction(
            {"from": user.address, "gas": 120_000})
        send_tx(USER_PRIVATE_KEY, tx, label="approve(collateral, SymmioCore)")

    # 2b) simulate first to catch revert reason before sending
    print(f"[debug] simulating depositForAccount({sub}, {amount_native}) "
          f"[= {from_collateral_units(amount_native)} in token-native units] ...")
    try:
        account_layer.functions.depositForAccount(sub, amount_native).call(
            {"from": user.address}
        )
        print("[debug] simulation OK — proceeding to send tx")
    except Exception as sim_err:
        raise SystemExit(f"[simulate] REVERT: {sim_err}")

    # 2c) deposit
    tx = account_layer.functions.depositForAccount(
        sub, amount_native).build_transaction({"from": user.address, "gas": 500_000})
    receipt = send_tx(USER_PRIVATE_KEY, tx,
                     label=f"depositForAccount({amount_native} raw -> {sub})")
    if receipt is not None:
        print(f"[debug] gasUsed={receipt['gasUsed']} / gasLimit=500000  "
              f"({'GAS EXHAUSTED' if receipt['gasUsed'] >= 499_000 else 'ok'})")

if __name__ == "__main__":
    main()
