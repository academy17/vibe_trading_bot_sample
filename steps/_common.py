"""
Shared config, ABIs, helpers, and a tiny JSON state file used by every
step script in this folder.

Configuration is loaded from a `.env` file in this folder (see .env.example).
Each step reads what it needs from `.state.json`, does its thing, and
writes what the next step will need.  Delete `.state.json` to start over.
"""

import os, json, time, secrets
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from web3 import Web3

# ============================================================================
# Load .env (this folder) so every script just has to `from _common import ...`
# ============================================================================
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    raise SystemExit("pip install python-dotenv  (or: pip install -r requirements.txt)")

# ============================================================================
# Addresses / endpoints  (HyperEVM production; override via env)
# ============================================================================
def _required(name: str) -> str:
    """Read an env var that has no safe default to commit to source."""
    v = os.getenv(name)
    if not v:
        raise SystemExit(
            f"required env var {name!r} is not set; add it to your local .env "
            f"(see .env.example for the full list)")
    return v


# Network: public Hyperliquid RPC + chain id.  Safe to default; not
# deployment-specific.
RPC_URL        = os.getenv("RPC_URL", "https://rpc.hyperliquid.xyz/evm")
CHAIN_ID       = int(os.getenv("CHAIN_ID", "999"))

# All on-chain addresses + off-chain service URLs are deployment-specific
# and come from .env.  No defaults are committed to source -- the bot
# refuses to start until the local .env is filled in.
ACCOUNT_LAYER    = Web3.to_checksum_address(_required("ACCOUNT_LAYER"))
SYMMIO_CORE      = Web3.to_checksum_address(_required("SYMMIO_CORE"))
INSTANT_LAYER    = Web3.to_checksum_address(_required("INSTANT_LAYER"))
AFFILIATE        = Web3.to_checksum_address(_required("AFFILIATE"))
HEDGER           = Web3.to_checksum_address(_required("HEDGER"))
TPSL_BOT_ADDRESS = Web3.to_checksum_address(_required("TPSL_BOT_ADDRESS"))
COLLATERAL_TOKEN = Web3.to_checksum_address(_required("COLLATERAL_TOKEN"))

SYMMIO_API     = _required("SYMMIO_API")
SOLVER_BASE    = _required("SOLVER_BASE")
# Symbols endpoint -- full URL because the path differs across deployments
# (staging uses /bsapi/contract-symbols, prod uses /api/contract-symbols).
SYMBOLS_URL    = _required("SYMBOLS_URL")
PRICE_WS_URL   = _required("PRICE_WS_URL")
TPSL_BASE      = _required("TPSL_BASE")
TPSL_APP_NAME  = _required("TPSL_APP_NAME")
NOTIF_WS_URL   = _required("NOTIF_WS_URL")
NOTIF_APP_NAME = _required("NOTIF_APP_NAME")

USER_PRIVATE_KEY = os.getenv("USER_PRIVATE_KEY", "")

# ============================================================================
# Enums & selectors
# ============================================================================
SUB_ISO_POSITION, SUB_ISO_MARKET, SUB_ISO_MARKET_DIRECTION, SUB_ISO_CUSTOM = 0, 1, 2, 3
VA_ISO_POSITION, VA_ISO_MARKET, VA_ISO_MARKET_LONG, VA_ISO_MARKET_SHORT   = 0, 1, 2, 3
POSITION_LONG, POSITION_SHORT = 0, 1
ORDER_LIMIT, ORDER_MARKET     = 0, 1

SEL_ADD_MARGIN_TO_NEXT_VA          = bytes.fromhex("a6d66852")
SEL_SEND_QUOTE_WITH_AFFILIATE_DATA = bytes.fromhex("a7f3b34b")
SEL_REQUEST_TO_CLOSE_POSITION      = bytes.fromhex("501e891f")
# Opaque identifiers used by the TPSL/COH service for its delegation lookup.
# They are NOT actual function selectors on the Symmio core; they must be
# granted in addition to the real selectors so services like the Conditional
# Orders Handler authenticate the session key correctly.  See
# docs/instant-layer-service-integration.md.
SEL_COH_REQUEST_TO_CLOSE           = bytes.fromhex("eaa31b19")
SEL_SESSION_KEY                    = bytes.fromhex("00000001")

# ============================================================================
# Web3 + ABIs (minimal)
# ============================================================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))

ACCOUNT_LAYER_ABI = [
    {"type":"function","name":"_call","stateMutability":"nonpayable",
     "inputs":[{"name":"account","type":"address"},
               {"name":"callDatas","type":"bytes[]"}],
     "outputs":[{"type":"bytes[]"}]},
    {"type":"function","name":"createSubAccounts","stateMutability":"nonpayable",
     "inputs":[{"name":"affiliate","type":"address"},
               {"name":"accountsData","type":"tuple[]","components":[
                   {"name":"name","type":"string"},
                   {"name":"metadata","type":"bytes"},
                   {"name":"symmioCore","type":"address"},
                   {"name":"isolationType","type":"uint8"},
                   {"name":"singleVAMode","type":"bool"}]}],
     "outputs":[{"type":"address[]"}]},
    {"type":"function","name":"depositAndAllocateForAccount","stateMutability":"nonpayable",
     "inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[]},
    {"type":"function","name":"depositForAccount","stateMutability":"nonpayable",
     "inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[]},
    {"type":"function","name":"depositAndAllocateForAccountWithExpressRate","stateMutability":"nonpayable",
     "inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[]},
    {"type":"function","name":"depositForAccountWithExpressRate","stateMutability":"nonpayable",
     "inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[]},
    {"type":"function","name":"getUserSubAccountsAddresses","stateMutability":"view",
     "inputs":[{"name":"owner","type":"address"},{"name":"offset","type":"uint256"},
               {"name":"limit","type":"uint256"}],"outputs":[{"type":"address[]"}]},
    {"type":"function","name":"predictNextVirtualAccountAddress","stateMutability":"view",
     "inputs":[{"name":"subAccount","type":"address"},{"name":"isolationType","type":"uint8"},
               {"name":"symbolId","type":"uint256"}],"outputs":[{"type":"address"}]},
    {"type":"function","name":"getVirtualAccountsAddressesOfSubAccount","stateMutability":"view",
     "inputs":[{"name":"subAccount","type":"address"},{"name":"offset","type":"uint256"},
               {"name":"limit","type":"uint256"}],"outputs":[{"type":"address[]"}]},
    {"type":"function","name":"getVirtualAccountQuoteIds","stateMutability":"view",
     "inputs":[{"name":"account","type":"address"},{"name":"offset","type":"uint256"},
               {"name":"limit","type":"uint256"}],"outputs":[{"type":"uint256[]"}]},
    {"type":"function","name":"getActiveVAByKey","stateMutability":"view",
     "inputs":[{"name":"subAccount","type":"address"},{"name":"isolationType","type":"uint8"},
               {"name":"symbolId","type":"uint256"}],"outputs":[{"type":"address"}]},
]
INSTANT_LAYER_ABI = [
    {"type":"function","name":"grantDelegation","stateMutability":"nonpayable",
     "inputs":[{"name":"info","type":"tuple","components":[
         {"name":"account","type":"tuple","components":[
             {"name":"addr","type":"address"},{"name":"isPartyB","type":"bool"}]},
         {"name":"delegatedSigner","type":"address"},
         {"name":"selectors","type":"bytes4[]"},
         {"name":"expiryTimestamp","type":"uint256"}]}],"outputs":[]}]
ERC20_ABI = [
    {"type":"function","name":"approve","stateMutability":"nonpayable",
     "inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[{"type":"bool"}]},
    {"type":"function","name":"allowance","stateMutability":"view",
     "inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "outputs":[{"type":"uint256"}]},
    {"type":"function","name":"balanceOf","stateMutability":"view",
     "inputs":[{"name":"owner","type":"address"}],"outputs":[{"type":"uint256"}]},
    {"type":"function","name":"decimals","stateMutability":"view",
     "inputs":[],"outputs":[{"type":"uint8"}]}]

account_layer = w3.eth.contract(address=ACCOUNT_LAYER, abi=ACCOUNT_LAYER_ABI)
instant_layer = w3.eth.contract(address=INSTANT_LAYER, abi=INSTANT_LAYER_ABI)
collateral    = w3.eth.contract(address=COLLATERAL_TOKEN, abi=ERC20_ABI)

# Read collateral token decimals once at startup.  Symmio uses 18-decimal
# fixed-point internally, but the actual ERC20 transfer happens in the
# token's native units -- so we need both scales available.
COLLATERAL_DECIMALS = collateral.functions.decimals().call()


def to_collateral_units(x) -> int:
    """Convert a human-readable amount to the collateral token's native units."""
    return int((Decimal(x) * Decimal(10) ** COLLATERAL_DECIMALS).to_integral_value())


def from_collateral_units(raw: int) -> Decimal:
    """Inverse of to_collateral_units, for human-readable display."""
    return Decimal(raw) / Decimal(10) ** COLLATERAL_DECIMALS

# ============================================================================
# State persistence
# ----------------------------------------------------------------------------
# Every step reads from and writes to `.state.json` in this folder.  Shape:
#
#   {
#     "sub_account":      "0x...",     # written by step 01
#     "owner":            "0x...",     # written by step 01
#     "isolation_type":   2,           # written by step 01
#     "session_pk":       "0x...",     # written by step 03
#     "session_address":  "0x...",     # written by step 03
#     "delegation_expiry": 1776461300, # written by step 03
#
#     # Opened positions.  Step 04 writes a stub keyed by temp_quote_id
#     # (negative), step 05 moves it to the real quote_id.  Steps 06 + 07
#     # look positions up by quote_id.
#     "positions": {
#       "4698": {
#           "symbol_id":     1,
#           "symbol_name":   "SYMM::80..5f_SFLOW",
#           "quantity":      "364.113020",
#           "position_type": 0,
#           "va_iso":        2,
#           "va_address":    "0x9481...",
#           "opened_at":     1776459729,
#           "temp_quote_id": -5319
#       },
#       ...
#     },
#     "last_quote_id": "4698"          # pointer for convenience
#   }
#
# Commands that act on a position default to `last_quote_id` if you do not
# pass one explicitly, so the fast path for single-position flows is
# `python 06_close_position.py 99` with no quote_id.
# ============================================================================
STATE_FILE = Path(__file__).parent / ".state.json"

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(**kwargs) -> dict:
    st = load_state()
    st.update(kwargs)
    STATE_FILE.write_text(json.dumps(st, indent=2, default=str))
    print(f"[state] wrote: {list(kwargs.keys())}")
    return st

def require(st: dict, *keys):
    missing = [k for k in keys if k not in st or st[k] in (None, "")]
    if missing:
        raise SystemExit(f"[state] missing keys in {STATE_FILE}: {missing}\n"
                         f"Run the earlier step(s) first.")

# ---- position helpers ------------------------------------------------------

def upsert_position(quote_id, pos: dict) -> dict:
    """Insert/merge a position record under `positions[str(quote_id)]` and
    bump `last_quote_id` to this one."""
    st = load_state()
    positions = st.setdefault("positions", {})
    key = str(quote_id)
    positions[key] = {**positions.get(key, {}), **pos}
    st["last_quote_id"] = key
    STATE_FILE.write_text(json.dumps(st, indent=2, default=str))
    print(f"[state] positions[{key}] <- {list(pos.keys())}")
    return positions[key]

def move_position(from_id, to_id, extra: dict | None = None) -> dict:
    """Rename the key from temp_quote_id to the real quote_id once resolved."""
    st = load_state()
    positions = st.setdefault("positions", {})
    src = positions.pop(str(from_id), {})
    if extra: src.update(extra)
    positions[str(to_id)] = src
    st["last_quote_id"] = str(to_id)
    STATE_FILE.write_text(json.dumps(st, indent=2, default=str))
    print(f"[state] positions[{from_id}] -> positions[{to_id}]")
    return src

def get_position(quote_id=None) -> tuple[str, dict]:
    """Return (quote_id_str, position_dict).  If quote_id is None, uses
    last_quote_id.  Raises SystemExit if not found."""
    st = load_state()
    qid = str(quote_id) if quote_id is not None else st.get("last_quote_id")
    if not qid:
        raise SystemExit("no quote_id given and no last_quote_id in state; "
                         "run 04_open_position.py + 05_find_va.py first.")
    pos = (st.get("positions") or {}).get(qid)
    if not pos:
        avail = list((st.get("positions") or {}).keys())
        raise SystemExit(f"positions[{qid}] not found; have: {avail}")
    return qid, pos

def list_positions() -> dict:
    return (load_state().get("positions") or {})

# ============================================================================
# Tx helper
# ============================================================================
def send_tx(user_pk: str, tx: dict, label: str = "") -> dict:
    user = Account.from_key(user_pk)
    tx.setdefault("from",     user.address)
    tx.setdefault("nonce",    w3.eth.get_transaction_count(user.address))
    tx.setdefault("chainId",  CHAIN_ID)
    tx.setdefault("gas",      2_500_000)
    signed = user.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rc = w3.eth.wait_for_transaction_receipt(h)
    print(f"[tx] {label} hash={h.hex()}  status={rc.status}  block={rc.blockNumber}")
    if rc.status != 1:
        raise SystemExit(f"tx reverted: {label}")
    return rc

# ============================================================================
# SignedOperation EIP-712
# ============================================================================
def _so_typed(op: dict) -> dict:
    return {
        "types": {
            "EIP712Domain":[{"name":"name","type":"string"},{"name":"version","type":"string"},
                            {"name":"chainId","type":"uint256"},{"name":"verifyingContract","type":"address"}],
            "Account":[{"name":"addr","type":"address"},{"name":"isPartyB","type":"bool"}],
            "FlexField":[{"name":"offset","type":"uint256"},{"name":"length","type":"uint256"},
                         {"name":"authorizedFlexFiller","type":"address"}],
            "ReplayAttackHeader":[{"name":"nonce","type":"uint256"},{"name":"deadline","type":"uint256"},
                                  {"name":"salt","type":"bytes32"}],
            "SignedOperation":[{"name":"signer","type":"address"},{"name":"target","type":"address"},
                               {"name":"callData","type":"bytes"},
                               {"name":"signerAccount","type":"Account"},
                               {"name":"flexFields","type":"FlexField[]"},
                               {"name":"maxUses","type":"uint256"},
                               {"name":"replayAttackHeader","type":"ReplayAttackHeader"}]},
        "primaryType":"SignedOperation",
        "domain":{"name":"SymmioInstantLayer","version":"1",
                  "chainId":CHAIN_ID,"verifyingContract":INSTANT_LAYER},
        "message":op,
    }

def sign_operation(session_pk: str, target: str, call_data: bytes,
                   account_addr: str, deadline: Optional[int] = None) -> dict:
    """signerAccount.addr = sub-account on open, VIRTUAL ACCOUNT on close."""
    sk       = Account.from_key(session_pk)
    acc      = Web3.to_checksum_address(account_addr)
    deadline = deadline or (int(time.time()) + 3600)
    # eth_account's EIP-712 encoder expects hex strings for bytes/bytes32 fields
    call_hex = "0x" + call_data.hex()
    salt_hex = "0x" + secrets.token_bytes(32).hex()
    op = {
        "signer": sk.address,
        "target": Web3.to_checksum_address(target),
        "callData": call_hex,
        "signerAccount": {"addr": acc, "isPartyB": False},
        "flexFields": [],
        "maxUses": 1,
        "replayAttackHeader": {
            "nonce": 0,
            "deadline": deadline,
            "salt": salt_hex,
        },
    }
    signed = sk.sign_typed_data(full_message=_so_typed(op))
    sig = signed.signature.hex()
    if not sig.startswith("0x"): sig = "0x" + sig
    return {
        "signedOperation": {
            "signer": sk.address,
            "target": op["target"],
            "callData": call_hex,
            "signerAccount": {"addr": acc, "isPartyB": False},
            "flexFields": [],
            "maxUses": "1",
            "replayAttackHeader": {
                "nonce": "0",
                "deadline": str(deadline),
                "salt": salt_hex,
            },
        },
        "signature": sig,
    }

# ============================================================================
# CallData encoders
# ============================================================================
def encode_add_margin_to_next_va(sub_account, va_iso, symbol_id, amount_wei) -> bytes:
    return SEL_ADD_MARGIN_TO_NEXT_VA + abi_encode(
        ["address","uint8","uint256","uint256"],
        [Web3.to_checksum_address(sub_account), va_iso, symbol_id, amount_wei])

def encode_send_quote(symbol_id, position_type, order_type, price_wei, quantity_wei,
                     cva, lf, pa_mm, pb_mm, deadline, affiliate, hedger, data_bytes=b"") -> bytes:
    # Empty SingleUpnlAndPriceSig sentinel; solver injects the real Muon sig.
    # Tuple layout per symmio.json ABI: (bytes, uint256, int256, uint256, bytes, (uint256, address, address))
    empty_sig = (b"", 0, 0, 0, b"", (0, "0x"+"00"*20, "0x"+"00"*20))
    return SEL_SEND_QUOTE_WITH_AFFILIATE_DATA + abi_encode(
        ["address[]","uint256","uint8","uint8","uint256","uint256",
         "uint256","uint256","uint256","uint256","uint256","address",
         "(bytes,uint256,int256,uint256,bytes,(uint256,address,address))","bytes"],
        [[Web3.to_checksum_address(hedger)], symbol_id, position_type, order_type,
         price_wei, quantity_wei, cva, lf, pa_mm, pb_mm, deadline,
         Web3.to_checksum_address(affiliate), empty_sig, data_bytes])

def encode_close(quote_id, close_price_wei, qty_wei, deadline) -> bytes:
    return SEL_REQUEST_TO_CLOSE_POSITION + abi_encode(
        ["uint256","uint256","uint256","uint8","uint256"],
        [quote_id, close_price_wei, qty_wei, ORDER_MARKET, deadline])

# ============================================================================
# HTTP helpers
# ============================================================================
def fetch_symbols() -> list[dict]:
    r = requests.get(SYMBOLS_URL, timeout=15).json()
    return r["symbols"] if isinstance(r, dict) and "symbols" in r else r

def get_symbol(symbol_id: int) -> dict:
    for s in fetch_symbols():
        if s.get("symbol_id") == symbol_id:
            return s
    raise KeyError(symbol_id)

def fetch_locked_params(symbol_name: str, leverage: int) -> dict:
    return requests.get(f"{SOLVER_BASE}/api/get_locked_params/{symbol_name}",
                        params={"leverage": leverage}, timeout=15).json()

def fetch_prices(timeout: float = 5.0) -> dict[str, Decimal]:
    """Connect to the price websocket, read ONE snapshot, return a dict of
    { symbol_name -> markPrice (Decimal) }.

    The server pushes a full snapshot for every connected client every tick
    so a single `recv()` is enough.  Keys are e.g. "SYMM::80..5f_SFLOW"
    (same string as `symbol.name` from /bsapi/contract-symbols).
    """
    import asyncio, websockets

    async def _once():
        async with websockets.connect(PRICE_WS_URL, open_timeout=timeout) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            rows = json.loads(raw)
            return {r["name"]: Decimal(str(r["markPrice"])) for r in rows}

    return asyncio.run(_once())

def price_of(symbol_name: str) -> Decimal:
    """One-shot lookup: fetches the snapshot and returns the named symbol."""
    prices = fetch_prices()
    if symbol_name not in prices:
        raise KeyError(f"{symbol_name} not found in price snapshot; "
                       f"available: {sorted(prices)[:5]}...")
    return prices[symbol_name]

def to_wei(x) -> int:
    return int((Decimal(x) * Decimal(10**18)).to_integral_value())
