# robinhood-lp-v2

An LP research tool for Uniswap V4 on Robinhood Chain. You are working inside a
**slice loop**, not a task queue. There is no phase, no backlog, no config file
describing what comes next.

## The loop

```
SHAPE → BUILD → SHOW → CRITIC → DECIDE → SHAPE
```

Every step below is a role. Each one is a separate agent with a separate
context window. Do not collapse them.

| Step | Agent | Writes | May not |
|---|---|---|---|
| SHAPE | `shaper` | `.prophet/spec.md` | implement anything |
| BUILD | `builder` | code, tests, on its branch | edit `.prophet/`, merge |
| SHOW | `builder` | a runnable artifact | — |
| CRITIC | `critic` | nothing | edit anything, issue a verdict |
| DECIDE | **human** | `.prophet/LOG.md` | — |

## State lives in git, not in a file

- Current hypothesis: `.prophet/spec.md` (rewritten every round)
- What happened: `.prophet/LOG.md` (one entry per round, ~5 lines)
- Settled choices: `.prophet/DECISIONS.md` (one line each)
- Where the project is: `.prophet/NOW.md` (low frequency, but write it)
- The work: the branch itself

If you find yourself wanting to update a status field, a task state, or a
progress percentage — stop. That is the V1 failure this project replaced.

`.prophet/NOW.md` is not a roadmap. It holds three things: what is currently
true, what is still an experiment, and the **observable threshold** that would
justify the next step. "Finish phase 2" is not a threshold. "A full pool's
events arrive in under 3 minutes and the count matches the official endpoint"
is.

## MVP and production are different jobs

The loop is the same in both. The gates are not.

| | MVP | Production |
|---|---|---|
| Goal | answer the question once, with real data | the same answer, reliably, unattended |
| Gates | ruff, ruff-format, mypy --strict, pytest | the above + coverage floor, integration and boundary tests |
| Interfaces | module contract | contract + ADR per decision + runbook |
| Failure | a stack trace is acceptable | degrade or stop; never report partial as complete |

The MVP phase exists so production is not the first time this runs.
Promotion is a decision against a stated threshold, not a phase on a schedule.
See `docs/ARCHITECTURE.md` §6.

## Module boundaries are the point

Each module exposes exactly the names in its `__init__.py`. Cross-module
imports go through that surface, never through an inner module.

**When building a module, do not read another module's implementation.**
`docs/ARCHITECTURE.md` plus the type signatures is the intended input. If that
is not enough, the interface is underspecified — report that, do not read
further. The whole value of the boundary is that a change inside one module
cannot silently break another, and that only holds if nobody was coupling to
the inside.

A wrong protocol constant returns an empty result, not an error, so probe after
touching `protocol/`.

## Commands

```bash
python3 -m tools.prophet status     # current hypothesis + round count
python3 -m tools.prophet check      # is the hypothesis actually falsifiable
python3 -m tools.prophet new <slug> # worktree + branch for a slice
python3 -m tools.prophet gates      # run gates, compare to baseline
python3 -m tools.prophet baseline   # record current findings as the baseline
```

`check` is not optional. A slice whose spec does not pass it is not ready to
build — you would be producing something the human cannot judge.

## Running the code

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"
.venv/bin/python -m robinhood_lp_v2.probe   # verify constants against chain
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q --cov          # MVP: no floor, just the number
```

`probe` exits 0 only if the chain agrees with our constants. It is the cheapest
way to tell whether a change broke the ground floor.

`filterwarnings = ["error"]` is on. A new warning fails the gate rather than
scrolling past; fix the cause or add a narrow, commented filter.

## Where things came from

`docs/chain-knowledge.md` — protocol facts, provider limits, LP metrics traps.
Measured, not copied. Read it instead of searching the web for V4 semantics.

`docs/ARCHITECTURE.md` — layers, module contract, cross-cutting policies.

The previous project (`robin-lp`) is **read-only** and lives outside this repo.
Its code must never be copied in. See `AGENTS.md`. Its *tooling configuration*
was worth copying and has been — see `pyproject.toml` and `.github/workflows/`.

## What this project is

An MVP: given a pool and a tick range, say what that liquidity would have earned
historically. Everything else is deferred until that one question is answered
with real data.

The first round exists. `python3 -m robinhood_lp_v2.probe` proves the
constants. It is a floor, not a feature — nothing a user can see yet.
