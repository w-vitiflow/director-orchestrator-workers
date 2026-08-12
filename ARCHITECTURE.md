# Architecture & process

> Diagrams are written in [Mermaid](https://mermaid.js.org/) — text that renders natively on GitHub and cannot garble labels. `assets/architecture.svg`/`.png` are the static visualisations.

## Architecture (logical layers)

```mermaid
flowchart TB
    subgraph L0["Layer 0 · Director (intent owner)"]
        DIR["Director
long-lived session
keeps your goals"]
    end
    subgraph L1["Layer 1 · Orchestrator (koor)"]
        ORC["Orchestrator (koor)
decompose → dispatch → consolidate
conductor, never the heavy lifter"]
    end
    subgraph L2["Layer 2 · Execution (kanban workers)"]
        W1["Worker · dev"]
        W2["Worker · media"]
        W3["Worker · ops"]
        VF["Verifier · review"]
    end
    subgraph L3["Shared durable board"]
        B["kanban.db
cards + acceptance criteria"]
    end
    DIR -- "1 · write intent (+ acceptance criteria)" --> B
    B -- "2 · read card / brief" --> ORC
    ORC -- "3 · spawn children (inherit acceptance verbatim)" --> B
    B -- "4 · claim & execute" --> W1
    B -- "4 · claim & execute" --> W2
    B -- "4 · claim & execute" --> W3
    W1 -. "5 · post result" .-> B
    W2 -. "5 · post result" .-> B
    W3 -. "5 · post result" .-> B
    B -- "6 · verify vs acceptance" --> VF
    VF -. "pass/fail vs ground truth" .-> B
    B -- "7 · consolidated deliverable" --> DIR
```

### Why these layers exist

- **Director** stays interactive. It owns your goals and never blocks inside a running job.
- **Orchestrator** buys parallelism and isolation: decomposes a goal, spawns specialist workers, monitors, consolidates.
- **Workers** are disposable, isolated, single-purpose executors that each claim one card.
- **Verifier** is split from execution so a deliverable is confirmed against ground truth, not the worker's self-report.
- The **board** is the durable handoff point so nothing depends on a live process being awake.

## The failure mode this prevents

A card's `body` is free for an orchestrator to rewrite; each rewrite is a chance for intent to drift. **Ground-truth acceptance propagation** changes this — the original `intent` + machine-checkable `checks` travel in an immutable `acceptance` field that children inherit **verbatim**. The verifier checks against that original, never a re-summarized version.

## Process (the intended flow)

```mermaid
sequenceDiagram
    autonumber
    participant D as Director
    participant R as route-assess
    participant O as Orchestrator (koor)
    participant W as kanban workers
    participant V as Verifier
    D->>R: route-assess(effort, parallel, external, verify...)
    R-->>D: verdict (inline | dispatch)
    alt verdict == inline
        D->>D: run it here, no card
    else verdict == dispatch
        D->>O: create root + acceptance {intent, checks}
        O->>O: decompose goal
        O->>W: spawn children (inherit acceptance verbatim)
        W-->>O: execute + post result
        O->>V: verify vs acceptance (ground truth)
        V-->>O: pass/fail per check
        O-->>D: consolidated deliverable
    end
```

## Decision rule (the cheap-inline tripwire)

| Signal | Consult flag | Hit → route as |
|--------|--------------|----------------|
| decomposes into >1 independent stream | `--parallel-splits N` | `dispatch` |
| external / slow dependency (GPU, render, download, API) | `--external-slow` | `dispatch` |
| needs independent review | `--needs-verification` | `dispatch` |
| needs isolated worktree / tenant / profile | `--requires-isolation` | `dispatch` |
| needs durable persistence / audit | `--needs-durability` | `dispatch` |
| effort over inline budget (default 5 min) | `--effort-minutes N` | `dispatch` |
| none of the above | — | `inline` (do it yourself) |

The tripwire is **conservative on unknown** for the dangerous cases (unknown external dependency or verification need defaults to `dispatch`). Only unknown *effort* defaults to inline. It is **advisory but never ignored silently** — overriding it is a deliberate, recorded choice.

## Acceptance contract

```json
{"intent": "the original goal, written once, verbatim", "checks": ["each machine-checkable criterion"]}
```

- `intent` **required** (non-empty) — the anti-drift anchor.
- `checks` explicit list an independent verifier could confirm.
- `source` auto-set (`director` on creation, parent id on inheritance); do not hand-set.
- Explicit child acceptance **overrides** inheritance; absent everywhere = no ground truth (never crashes).

See `kanban-ground-truth-orchestration/SKILL.md` for full CLI usage.
