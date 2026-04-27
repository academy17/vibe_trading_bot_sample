"""
STEP 9 (debug helper) -- List positions currently tracked in .state.json.

Usage:
    python 09_positions.py

Prints each `positions[quote_id]` record along with what action you'd
pass to steps 06 / 07.  Use this when you have several open trades
and want to pick a specific one to close or set TP/SL on.
"""
from _common import list_positions, load_state

def main():
    st = load_state()
    last = st.get("last_quote_id")
    ps   = list_positions()
    if not ps:
        print("no positions tracked.  run 04_open_position.py + 05_find_va.py.")
        return
    print(f"{'QID':>8}  {'SYMBOL':<26}  {'DIR':<5}  {'QTY':<14}  VA / temp")
    for qid, p in ps.items():
        dir_ = "long" if p.get("position_type") == 0 else "short"
        marker = " <- last" if qid == last else ""
        va_or_temp = p.get("va_address") or f"temp={p.get('temp_quote_id')}"
        print(f"{qid:>8}  {p.get('symbol_name','?'):<26}  {dir_:<5}  "
              f"{str(p.get('quantity','')):<14}  {va_or_temp}{marker}")

if __name__ == "__main__":
    main()
