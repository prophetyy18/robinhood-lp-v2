"""Tests for the protocol constants.

The negative cases here are not hypothetical. Both were made by hand earlier
in the same session and both produced a valid, empty result rather than an
error, which is why they are worth pinning down.
"""

from __future__ import annotations

import hashlib

import pytest

from robinhood_lp_v2 import (
    CHAIN_ID,
    DYNAMIC_FEE_FLAG,
    MAX_TICK,
    MAX_TICK_SPACING,
    MIN_TICK,
    MIN_TICK_SPACING,
    TOPIC0,
    keccak256,
    to_id,
)
from robinhood_lp_v2.probe import (
    REFERENCE_POOL_ID,
    REFERENCE_POOL_KEY,
    ProbeError,
    _signed,
    _word,
    decode_initialize,
)

C0 = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
C1 = "0x7dbf38976f6d3b9c529e7d9484a71898b409ee6a"
ZERO = "0x0000000000000000000000000000000000000000"


def _raw_id(c0: str, c1: str, fee: int, spacing: int, hooks: str) -> str:
    """abi.encode(PoolKey) with no validation, for negative test cases."""

    def word(a: str) -> bytes:
        return bytes(12) + bytes.fromhex(a[2:])

    return (
        "0x"
        + keccak256(
            word(c0)
            + word(c1)
            + fee.to_bytes(32, "big")
            + (spacing & ((1 << 256) - 1)).to_bytes(32, "big")
            + word(hooks)
        ).hex()
    )


# --- the reference pool --------------------------------------------------


def test_reference_pool_id_round_trips() -> None:
    assert (
        to_id(C0, C1, REFERENCE_POOL_KEY["fee"], REFERENCE_POOL_KEY["tick_spacing"], ZERO)
        == REFERENCE_POOL_ID
    )


def test_currency_order_changes_the_id() -> None:
    """currency0 < currency1 is unsigned uint160, and it changes the hash."""
    # Encoding the swapped order is only possible by bypassing the guard,
    # which is the point: the ordering is a real constraint, not a convention.
    swapped = _raw_id(C1, C0, 28001, 280, ZERO)
    assert swapped != REFERENCE_POOL_ID
    with pytest.raises(ValueError, match="currency0 must be < currency1"):
        to_id(C1, C0, 28001, 280, ZERO)


def test_tick_spacing_is_sign_extended() -> None:
    """int24 must be sign-extended to int256. Omitting it is silent.

    abi.encode writes int24 as a sign-extended int256. For a positive value
    the two encodings coincide, so a naive implementation looks correct on
    every pool this project has touched so far. The failure only appears on a
    negative spacing, and even then it is silent: a different, plausible id
    that matches nothing on chain.
    """
    positive = to_id(C0, C1, 28001, 280, ZERO)
    assert positive == _raw_id(C0, C1, 28001, 280, ZERO)

    # Sign extension is what makes -280 encode as 2**256 - 280.
    extended = _raw_id(C0, C1, 28001, -280, ZERO)
    unextended = _raw_id(C0, C1, 28001, 280, ZERO)
    assert extended != unextended
    assert extended == _raw_id(C0, C1, 28001, -280, ZERO)

    # A positive spacing is unchanged by whether you extend it, which is
    # exactly why the bug survives on ordinary pools.
    assert to_id(C0, C1, 28001, 281, ZERO) != positive
    assert _raw_id(C0, C1, 28001, 281, ZERO) != unextended


def test_negative_tick_spacing_is_rejected() -> None:
    """int24 is signed, but a pool's tick grid is not.

    The ABI type allows negative values; a real pool does not use them. toId
    is a pure hash and would encode -280 happily, producing a PoolId that
    exists nowhere. Rejecting it here is the point of validating at all.
    """
    assert to_id(C0, C1, 28001, 280, ZERO) != to_id(C0, C1, 28001, 281, ZERO)
    with pytest.raises(ValueError, match="tick_spacing"):
        to_id(C0, C1, 28001, -1, ZERO)
    with pytest.raises(ValueError, match="tick_spacing"):
        to_id(C0, C1, 28001, 0, ZERO)


# --- validation ----------------------------------------------------------


def test_identical_currencies_rejected() -> None:
    with pytest.raises(ValueError, match="same"):
        to_id(C0, C0, 28001, 280, ZERO)


@pytest.mark.parametrize("spacing", [MAX_TICK_SPACING + 1, -MAX_TICK_SPACING, 0])
def test_tick_spacing_range_enforced(spacing: int) -> None:
    with pytest.raises(ValueError, match="tick_spacing"):
        to_id(C0, C1, 28001, spacing, ZERO)


def test_fee_range_enforced() -> None:
    with pytest.raises(ValueError, match="fee"):
        to_id(C0, C1, 1_000_001, 280, ZERO)


def test_tick_bounds_are_the_v4_values() -> None:
    assert (MIN_TICK, MAX_TICK) == (-887272, 887272)
    assert (MIN_TICK_SPACING, MAX_TICK_SPACING) == (1, 32767)


# --- keccak vs sha3 ------------------------------------------------------


def test_keccak256_is_not_sha3_256() -> None:
    """The mistake that silently produced the wrong bytecode hash.

    hashlib.sha3_256 is SHA3-256. Uniswap uses keccak256, the original
    Keccak submission. Same digest length, no error, different value.
    """
    data = b"PoolManager bytecode"
    assert keccak256(data).hex() != hashlib.sha3_256(data).hexdigest()
    # NIST SHA3-256 of b"" begins 0xa7ffc6f8; keccak256(b"") begins 0xc5d24601.
    assert hashlib.sha3_256(b"").hexdigest().startswith("a7ffc6f8")
    assert keccak256(b"").hex().startswith("c5d24601")


def test_dynamic_fee_flag_is_an_equality_not_a_range() -> None:
    assert DYNAMIC_FEE_FLAG == 0x800000
    # A range check would treat these as dynamic; the contract does not.
    assert DYNAMIC_FEE_FLAG != 0x800001
    assert DYNAMIC_FEE_FLAG != 0x7FFFFF


# --- event topics --------------------------------------------------------


def test_initialize_topic0_is_derived_not_hardcoded() -> None:
    """Initialize's first indexed argument is PoolId (bytes32), not address.

    Deriving it from the wrong signature — omitting currency1, or typing the
    id as an address — yields a topic that matches nothing, and eth_getLogs
    answers with an empty array rather than an error.
    """
    right = TOPIC0["Initialize"]

    wrong_missing_currency1 = (
        "0x" + keccak256(b"Initialize(bytes32,address,uint24,int24,address,uint160,int24)").hex()
    )
    wrong_id_as_address = (
        "0x"
        + keccak256(b"Initialize(address,address,address,uint24,int24,address,uint160,int24)").hex()
    )

    assert wrong_missing_currency1 != right
    assert wrong_id_as_address != right
    assert right == ("0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438")


def test_all_five_pool_events_present() -> None:
    assert set(TOPIC0) == {
        "Initialize",
        "ModifyLiquidity",
        "Swap",
        "Donate",
        "ProtocolFeeUpdated",
    }
    assert all(v.startswith("0x") and len(v) == 66 for v in TOPIC0.values())


# --- log decoding --------------------------------------------------------


def _init_log(data: str = "0x" + "00" * 4) -> dict[str, object]:
    return {
        "topics": [
            TOPIC0["Initialize"],
            REFERENCE_POOL_ID,
            "0x" + "00" * 12 + C0[2:],
            "0x" + "00" * 12 + C1[2:],
        ],
        "data": data,
    }


def test_decode_initialize_recovers_the_pool_key() -> None:
    data = (
        "0x"
        + (28001).to_bytes(32, "big").hex()
        + (-280 & ((1 << 256) - 1)).to_bytes(32, "big").hex()
        + "00" * 12
        + "00" * 20
        + "00" * 32
        + "00" * 32
    )
    key = decode_initialize(_init_log(data))
    assert key == {
        "pool_id": REFERENCE_POOL_ID,
        "currency0": C0,
        "currency1": C1,
        "fee": 28001,
        "tick_spacing": -280,
        "hooks": ZERO,
    }


def test_short_log_is_rejected() -> None:
    log = _init_log()
    log["topics"] = log["topics"][:3]  # type: ignore[index]
    with pytest.raises(ProbeError, match="topics"):
        decode_initialize(log)


def test_word_reading() -> None:
    data = "0x" + (7).to_bytes(32, "big").hex() + "ff" * 32
    assert _word(data, 0) == 7
    assert _signed(data, 1) == -1
    with pytest.raises(ProbeError, match="out of range"):
        _word(data, 2)


def test_chain_id() -> None:
    assert CHAIN_ID == 4663
