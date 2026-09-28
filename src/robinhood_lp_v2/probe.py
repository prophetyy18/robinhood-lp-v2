"""Probe: prove the protocol constants are right, or exit non-zero.

The point of this command is to fail loudly. A wrong constant here produces
an empty log query, which reads as "this pool does not exist" rather than
"this code is wrong". So the probe does not trust a single direction:

1. fetch the known pool's Initialize event from chain
2. decode the PoolKey out of the log data
3. recompute the PoolId from that PoolKey
4. require the recomputed id to equal the one the log was fetched with

Step 4 is what makes the round trip meaningful. Without it, a wrong topic0
would report success with an empty result set.

Usage:
    python -m robinhood_lp_v2.probe
    python -m robinhood_lp_v2.probe --pool-id 0x...
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Final

from . import (
    CHAIN_ID,
    POOL_MANAGER,
    POOL_MANAGER_CODE_HASH,
    POOL_MANAGER_CODE_SIZE,
    STATE_VIEW,
    STATE_VIEW_CODE_HASH,
    STATE_VIEW_CODE_SIZE,
    TOPIC0,
    keccak256,
    to_id,
)
from .rpc import Rpc, RpcError, endpoints

#: The reference pool carried over from the previous project.
REFERENCE_POOL_ID: Final[str] = "0x6c614c38c65fea492f4cb2b90fd664f924a7b828c7384620662217e2e2df43ed"
REFERENCE_POOL_KEY: Final[dict[str, Any]] = {
    "currency0": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",
    "currency1": "0x7dbf38976f6d3b9c529e7d9484a71898b409ee6a",
    "fee": 28001,
    "tick_spacing": 280,
    "hooks": "0x0000000000000000000000000000000000000000",
}

#: Read from the Initialize log, not from the decoded PoolKey.
REFERENCE_INITIALIZE_BLOCK: Final[int] = 54946237

ZERO_TOPIC: Final[str] = "0x" + "0" * 64

#: Initialize has three indexed arguments, so four topics counting topic0.
INITIALIZE_TOPIC_COUNT: Final[int] = 4


class ProbeError(RuntimeError):
    pass


def _word(data: str, index: int) -> int:
    """Read ABI word ``index`` from a hex data blob."""
    raw = bytes.fromhex(data[2:])
    start = index * 32
    if start + 32 > len(raw):
        raise ProbeError(f"data word {index} out of range (len={len(raw)})")
    return int.from_bytes(raw[start : start + 32], "big")


def _address(data: str, index: int) -> str:
    return "0x" + data[2:][index * 64 + 24 : index * 64 + 64]


def _signed(data: str, index: int) -> int:
    value = _word(data, index)
    return value - (1 << 256) if value >= (1 << 255) else value


def decode_initialize(log: dict[str, Any]) -> dict[str, Any]:
    """Recover a PoolKey from a V4 Initialize log.

    Initialize(bytes32 indexed id, address indexed currency0, address indexed
    currency1, uint24 fee, int24 tickSpacing, address hooks, uint160
    sqrtPriceX96, int24 tickCurrent)
    """
    topics = log["topics"]
    if len(topics) < INITIALIZE_TOPIC_COUNT:
        raise ProbeError(
            f"Initialize log has {len(topics)} topics, expected >= {INITIALIZE_TOPIC_COUNT}"
        )
    return {
        "pool_id": topics[1],
        "currency0": _address("0x" + topics[2][2:], 0),
        "currency1": _address("0x" + topics[3][2:], 0),
        "fee": _word(log["data"], 0),
        "tick_spacing": _signed(log["data"], 1),
        "hooks": _address(log["data"], 2),
    }


def check_code(rpc: Rpc, address: str, size: int, code_hash: str) -> str:
    code = rpc.get_code(address)
    if not code or code == "0x":
        raise ProbeError(f"no bytecode at {address}")
    raw = bytes.fromhex(code[2:])
    if len(raw) != size:
        raise ProbeError(f"{address} is {len(raw)} bytes, expected {size}")
    actual = keccak256(raw).hex()
    if actual != code_hash:
        raise ProbeError(f"{address} keccak {actual}, expected {code_hash}")
    return f"{len(raw):>6} bytes  keccak {actual[:16]}…  ok"


def locate_initialize(rpc: Rpc, pool_id: str, hint_block: int | None) -> dict[str, Any]:
    """Find a pool's Initialize event.

    The two endpoints need different queries. The official one serves a
    whole-chain range; Alchemy Free rejects any ``eth_getLogs`` wider than
    10 blocks with HTTP 400 and a message naming the range it would accept.
    Given a known block, the narrow query is enough to cross-check.
    """
    query: tuple[str, str, str] = (
        (POOL_MANAGER, hex(hint_block), hex(hint_block))
        if hint_block is not None
        else (POOL_MANAGER, "0x0", "latest")
    )
    logs = rpc.get_logs(query[0], [TOPIC0["Initialize"], pool_id], query[1], query[2])
    if not logs:
        where = f"at block {hint_block}" if hint_block is not None else "on the whole chain"
        raise ProbeError(
            f"no Initialize for {pool_id} {where} — either the pool does not "
            f"exist or topic0 {TOPIC0['Initialize']} is wrong"
        )
    if len(logs) > 1:
        raise ProbeError(f"{len(logs)} Initialize events for one pool id")
    log = logs[0]
    log["blockNumber"] = int(log["blockNumber"], 16)
    return log


def run(pool_id: str, verify_reference: bool) -> int:
    known_block: int | None = None

    for rpc in endpoints():
        print(f"── {rpc.label}")

        chain = rpc.chain_id()
        if chain != CHAIN_ID:
            raise ProbeError(f"chain_id {chain}, expected {CHAIN_ID}")
        print(f"   chain_id          {chain}  ok")

        for name, address, size, code_hash in (
            ("PoolManager", POOL_MANAGER, POOL_MANAGER_CODE_SIZE, POOL_MANAGER_CODE_HASH),
            ("StateView", STATE_VIEW, STATE_VIEW_CODE_SIZE, STATE_VIEW_CODE_HASH),
        ):
            detail = check_code(rpc, address, size, code_hash)
            print(f"   {name:<17} {detail}")

        # The first endpoint does the whole-chain search. Later ones reuse the
        # block it found, because Alchemy Free cannot afford a wide range.
        scope = "whole chain" if known_block is None else f"block {known_block}"
        log = locate_initialize(rpc, pool_id, known_block)
        key = decode_initialize(log)
        block = int(log["blockNumber"])
        print(f"   Initialize        {block}  ({scope})  ok")
        known_block = block

        print(f"   currency0         {key['currency0']}")
        print(f"   currency1         {key['currency1']}")
        print(f"   fee               {key['fee']}")
        print(f"   tick_spacing      {key['tick_spacing']}")
        print(f"   hooks             {key['hooks']}")

        # The round trip. A wrong topic0 yields an empty result, not a
        # mismatch, so this is what actually proves the encoding.
        recomputed = to_id(
            key["currency0"],
            key["currency1"],
            key["fee"],
            key["tick_spacing"],
            key["hooks"],
        )
        if recomputed != key["pool_id"]:
            raise ProbeError(f"round trip failed: log id {key['pool_id']}, recomputed {recomputed}")
        if recomputed != pool_id.lower():
            raise ProbeError(f"recomputed {recomputed}, queried {pool_id}")
        print(f"   round trip        {recomputed[:10]}…  ok")

        if verify_reference:
            # The initialize block is on the log, not in the decoded PoolKey,
            # so the two are checked separately.
            for field, expected in REFERENCE_POOL_KEY.items():
                if key[field] != expected:
                    raise ProbeError(f"{field}: got {key[field]}, expected {expected}")
            if block != REFERENCE_INITIALIZE_BLOCK:
                raise ProbeError(f"initialize block {block}, expected {REFERENCE_INITIALIZE_BLOCK}")
            print("   matches V1 record  ok")

        print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe", description=__doc__)
    parser.add_argument("--pool-id", default=REFERENCE_POOL_ID)
    parser.add_argument(
        "--no-reference-check",
        action="store_true",
        help="skip comparison against the V1 reference values",
    )
    args = parser.parse_args(argv)

    try:
        return run(args.pool_id.lower(), not args.no_reference_check)
    except (ProbeError, RpcError) as exc:
        print(f"\nPROBE FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
