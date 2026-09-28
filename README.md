# robinhood-lp-v2

Given a Uniswap V4 pool on Robinhood Chain and a tick range, work out what that
liquidity would have earned historically — in fees, in inventory loss, and net.

That is the whole question. Everything else is deferred until it has an answer
someone looked at.

## Status

Early. `python -m robinhood_lp_v2.probe` verifies the protocol constants
against both configured RPC endpoints and exits 0 only if the chain agrees.
That is a floor, not a feature — nothing here answers the question yet.

`.prophet/NOW.md` says where the project actually is, in observations rather
than phases.

## Running it

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -q -e ".[dev]"

cp .env.example .env      # optional: the public endpoint needs no key
set -a; . ./.env; set +a

.venv/bin/python -m robinhood_lp_v2.probe
.venv/bin/python -m pytest -q tests
```

The probe prints the pool it resolved, the round trip through the PoolId
encoding, and the bytecode hash of each contract. A wrong constant returns an
empty log query rather than an error, so this is the check that catches it.

## Endpoints

The official public endpoint is the primary. Alchemy is a backup, and its
capabilities differ: it will not serve an `eth_getLogs` wider than 10 blocks,
while the official endpoint will not serve `eth_call` state a million blocks
back. The probe uses each for what it can do.

`docs/chain-knowledge.md` has the measured numbers.

## Layout

```
src/robinhood_lp_v2/     protocol constants, RPC, probe
tests/                    18 tests
tools/prophet/            the slice-loop helper
tools/check_boundaries.py CI: cross-module imports and dependency cycles
docs/chain-knowledge.md   protocol facts, provider limits, LP metrics traps
docs/ARCHITECTURE.md      layers, module contract, cross-cutting policies
```

Modules expose exactly what their `__init__.py` exports. Cross-module imports
go through that surface; `tools/check_boundaries.py` fails the build otherwise.

## Development

Work happens in slices: one falsifiable hypothesis, one branch, one artifact
you open and judge. See `CLAUDE.md` and `.prophet/spec.md`.

The previous project (`robin-lp`) is read-only and lives outside this repo.
Its code must never be copied in — see `AGENTS.md`.
