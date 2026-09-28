# Architecture

How this project's code is organized, and what each part is allowed to depend on.

The workflow that produced this file lives in `CLAUDE.md`. This file is about
the product, not the process.

---

## 1. What this system is

One question, answered with real chain data:

> For a given pool and tick range, what would that liquidity have earned
> historically — in fees, in inventory loss, and net?

Nothing else is in scope until that question has an answer someone looked at.
See `.prophet/NOW.md` for where the project actually is.

---

## 2. Layered model

Dependencies point downward only. An arrow `A → B` means A may import B.

```
                    ┌─────────────┐
                    │  cli / ui   │   presentation
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ application │   orchestration, commands
                    └──────┬──────┘
                           │
        ┌──────────┬───────┴───────┬──────────┐
        │          │               │          │
   ┌────▼───┐ ┌────▼───┐     ┌─────▼──┐ ┌────▼────┐
   │  risk  │ │strategy│     │ backtest│ │  rpc   │   domain
   └────┬───┘ └────┬───┘     └────┬───┘ └────┬────┘
        │          │              │          │
        └──────────┴───────┬──────┴──────────┘
                           │
                    ┌──────▼──────┐
                    │  protocol   │   types, constants, math
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   storage   │   parquet, append-only
                    └─────────────┘
```

| Layer | Owns | Never does |
|---|---|---|
| `cli` / `ui` | rendering, argument parsing | business rules |
| `application` | sequencing, wiring | arithmetic |
| domain (`risk`, `strategy`, `backtest`, `rpc`, `replay`, `features`) | the actual logic | persistence, I/O formatting |
| `protocol` | PoolKey, PoolId, ticks, keccak | network calls |
| `storage` | reading and writing bytes | knowing what a tick means |

**A module never imports from a layer above it.** The cycle check in CI
enforces this; it is not a convention.

---

## 3. Module contract

Every module exposes exactly one public surface: the names in its
`__init__.py`. Everything else is private.

```python
# protocol/__init__.py
from .pool_key import PoolKey, to_id
from .ticks import Tick, MIN_TICK, MAX_TICK

__all__ = ["PoolKey", "to_id", "Tick", "MIN_TICK", "MAX_TICK"]
```

Rules:

1. **Import across a module boundary goes through `__init__.py`.** A
   `from ..storage.parquet_writer import X` is a CI failure, not a style note.
2. **`__all__` is the contract.** If it is not there, another module does not
   get to use it. That is what makes a change here safe for callers.
3. **A module may be developed without reading another module's internals.**
   `INTERFACE.md` plus the type signatures is sufficient input. If it is not,
   the interface is underspecified — fix the interface, do not read the source.
4. **The dependency graph is acyclic.** A cycle between two modules is a
   design error: one of them is in the wrong layer.

### The 3.3 rule

> If building a module requires knowing how another one works internally, the
> boundary is in the wrong place.

V1 grew an `orchestrator/__init__.py` of 2548 lines while `presentation` had 8.
That asymmetry is what the rules above exist to prevent.

---

## 4. Public contracts

Anything another module (or another process, or a later version) depends on
gets three things together:

1. the type or protocol,
2. a docstring saying what it guarantees and what it does not,
3. a test that would fail if the guarantee were dropped.

An interface with no test is a comment.

---

## 5. Cross-cutting policies

- **Integer domain.** On-chain values (`sqrtPriceX96`, `liquidity`, `tick`,
  amounts) are `int`. Convert to `Decimal` only at display and at explicit
  statistical boundaries. Float cannot be aligned with Solidity semantics.
- **Append only.** Raw events and audit records are never overwritten or
  deleted. A gap stays a gap; it is not interpolated.
- **Event time, not wall clock.** Replay and backtest read block timestamps.
  A skewed local clock must not change a result.
- **No hidden fallback.** If a required value is unavailable, say
  `UNAVAILABLE`. A silent default is how a wrong number becomes a right answer.
- **Fail loudly on constants.** A wrong protocol constant returns an empty
  result, not an error. `python -m robinhood_lp_v2.probe` is the check.

---

## 6. MVP vs production

Two phases, same loop, different gates.

| | MVP | Production |
|---|---|---|
| Goal | answer the question once, with real data | the same answer, reliably, unattended |
| Gates | ruff, ruff-format, mypy --strict, pytest | the above + coverage floor, integration tests, boundary tests |
| Interfaces | the module contract above | contract + ADR per decision + runbook |
| Failure handling | a stack trace is fine | degrade or stop, never report a partial as complete |
| Entry condition | — | stated in `.prophet/NOW.md`, as an observation |

The MVP phase exists so that the production phase is not the first time the
system runs. Promoting to production is a decision with a stated threshold,
not a phase that arrives on a schedule.

---

## 7. State machines

If a component is a state machine, its reachability graph is generated from
the code, never drawn by hand, and CI fails on:

- a state that is unreachable from the initial one (dead code),
- a state with no outgoing edge that is not terminal (deadlock),
- a cycle in the module dependency graph.

A hand-drawn diagram is documentation. A generated one is a check. The value
is in the second: an implementation that disagrees with the picture is
exactly the bug a picture cannot catch.

---

## 8. Open questions

Recorded rather than guessed. Each one names what would resolve it.

- *(none yet)*
