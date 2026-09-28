"""Protocol constants for Uniswap V4 on Robinhood Chain.

Every value here was measured, not copied from prose. The module exists
because the previous project kept these as documentation, and deriving them
by hand failed twice in one session in ways that returned valid empty results
instead of errors.

Two mistakes that both fail silently:

* ``hashlib.sha3_256`` is SHA3, not keccak256. Uniswap uses keccak256. Same
  length, both succeed, different value. Use :func:`keccak256` below.
* ``Initialize`` takes ``PoolId`` (bytes32) as its first indexed argument, not
  an address. Getting this wrong yields an empty log result, not a revert.

The first is avoided by never calling hashlib for keccak. The second is
avoided by :mod:`robinhood_lp_v2.probe`, which requires a round trip.
"""

from __future__ import annotations

from typing import Final

from Crypto.Hash import keccak

# --- chain ---------------------------------------------------------------

CHAIN_ID: Final[int] = 4663

POOL_MANAGER: Final[str] = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
STATE_VIEW: Final[str] = "0xf3334192d15450cdd385c8b70e03f9a6bd9e673b"

# Measured 2026-09-28 against both the official endpoint and Alchemy Free.
# The same CREATE2 address carries different bytecode on mainnet and testnet,
# so an address alone does not identify a deployment.
POOL_MANAGER_CODE_SIZE: Final[int] = 24009
POOL_MANAGER_CODE_HASH: Final[str] = (
    "bd3881180b547f5fe817545743cfb4343e96b1bc6640dcd70c106b0066e95626"
)
STATE_VIEW_CODE_SIZE: Final[int] = 3531
STATE_VIEW_CODE_HASH: Final[str] = (
    "7d9c591e0956fd89d98feb4ffcfe8bf1f7a62bd485edd979fa21d104b49878a6"
)

# --- Uniswap V4 limits ---------------------------------------------------

MIN_TICK: Final[int] = -887272
MAX_TICK: Final[int] = 887272
MIN_TICK_SPACING: Final[int] = 1
MAX_TICK_SPACING: Final[int] = 32767

MAX_LP_FEE: Final[int] = 1_000_000
DYNAMIC_FEE_FLAG: Final[int] = 0x800000
OVERRIDE_FEE_FLAG: Final[int] = 0x400000
ALL_HOOK_MASK: Final[int] = (1 << 14) - 1

#: abi.encode(PoolKey) is five 32-byte words.
WORD_SIZE: Final[int] = 32
ADDRESS_SIZE: Final[int] = 20
POOL_KEY_ENCODED_SIZE: Final[int] = 5 * WORD_SIZE

#: A topic0 is a 32-byte hash, 0x-prefixed.
TOPIC0_LENGTH: Final[int] = 66


# --- hashing -------------------------------------------------------------


def keccak256(data: bytes) -> bytes:
    """Ethereum keccak256. Not SHA3-256, despite both being 256-bit."""
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def event_topic0(signature: str) -> str:
    """topic0 for a solidity event signature, e.g. ``Swap(bytes32,...)``."""
    return "0x" + keccak256(signature.encode()).hex()


# --- PoolKey encoding ----------------------------------------------------


def _address_word(address: str) -> bytes:
    """abi.encode of an address: 12 zero bytes then the 20 address bytes."""
    raw = bytes.fromhex(address[2:])
    if len(raw) != ADDRESS_SIZE:
        raise ValueError(f"not an address: {address}")
    return bytes(WORD_SIZE - ADDRESS_SIZE) + raw


def to_id(
    currency0: str,
    currency1: str,
    fee: int,
    tick_spacing: int,
    hooks: str,
) -> str:
    """PoolId = keccak256(abi.encode(PoolKey)).

    ``tick_spacing`` is int24 in the ABI and must be sign-extended to int256
    before encoding. Omitting the extension produces a different hash that
    looks entirely normal.

    The validation below is this module's policy, not v4-core's: ``toId`` in
    v4-core is a pure hash with no checks. It is here so a bad PoolKey fails
    loudly instead of yielding a plausible id that matches nothing on chain.
    """
    if currency0.lower() == currency1.lower():
        raise ValueError("currency0 and currency1 are the same")
    # v4-core does not enforce this in toId, but a canonical pool has
    # currency0 < currency1 as unsigned uint160.
    if int(currency0, 16) >= int(currency1, 16):
        raise ValueError("currency0 must be < currency1 (unsigned uint160)")
    # MIN/MAX_TICK_SPACING are int24 bounds used by TickMath. Pools initialize
    # with a positive spacing; a negative or zero one has no usable tick grid.
    if not MIN_TICK_SPACING <= tick_spacing <= MAX_TICK_SPACING:
        raise ValueError(f"tick_spacing out of range: {tick_spacing}")
    if not 0 <= fee <= MAX_LP_FEE:
        raise ValueError(f"fee out of range: {fee}")

    encoded = (
        _address_word(currency0)
        + _address_word(currency1)
        + fee.to_bytes(32, "big")  # uint24, left-padded
        + (tick_spacing & ((1 << 256) - 1)).to_bytes(32, "big")  # int24 -> int256
        + _address_word(hooks)
    )
    if len(encoded) != POOL_KEY_ENCODED_SIZE:
        raise AssertionError(
            f"abi.encode(PoolKey) is {POOL_KEY_ENCODED_SIZE} bytes, got {len(encoded)}"
        )
    return "0x" + keccak256(encoded).hex()


# --- V4 event signatures -------------------------------------------------
# The indexed arguments are what matter for topic filtering. Initialize's
# first indexed argument is the PoolId (bytes32), not an address.

SIGNATURES: Final[dict[str, str]] = {
    "Initialize": "Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)",
    "ModifyLiquidity": ("ModifyLiquidity(bytes32,address,int24,int24,int256,int256,bytes32)"),
    "Swap": "Swap(bytes32,address,address,int256,int256,uint160,uint128,int24)",
    "Donate": "Donate(bytes32,address,uint256,uint256)",
    "ProtocolFeeUpdated": "ProtocolFeeUpdated(bytes32,uint24,uint24)",
}

TOPIC0: Final[dict[str, str]] = {name: event_topic0(sig) for name, sig in SIGNATURES.items()}

#: The five events a pool-filtered query must cover.
POOL_EVENTS: Final[tuple[str, ...]] = tuple(TOPIC0)
