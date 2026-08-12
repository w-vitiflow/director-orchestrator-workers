# Director → Orchestrator → kanban workers

A **non-blocking agent pipeline** for self-hosted [Hermes](https://hermes-agent.nousresearch.com) agents.

You keep a single interactive agent (**Director**) that stays responsive to you, while heavy or parallel work is handed off through an **Orchestrator (koor)** to isolated **kanban workers** — and the original intent is carried *verbatim* down the chain so workers don't drift from what you actually asked for.

## What it gives you

- **Ground-truth preservation** — the original goal + machine-checkable acceptance criteria are attached to the root card and inherited *verbatim* by every worker, verifier, and synthesizer. A verifier checks against the original intent, never a re-summarized version.
- **Cheap-inline tripwire** — a mechanical `route-assess` rule deciding whether a task should be run inline (do it now, no ceremony) or dispatched (fan out through the pipeline).
- **True non-blocking operation** — dispatch work to the board, keep chatting with your Director/gateway while workers grind in the background.

## Who this is for

- People running **self-hosted/local AI** with a **large token budget** (own cluster, inference hosts).
- People who want the **throughput of parallelism** that local models don't give directly — add work to the board, workers run it in parallel, main session never blocks.
- Operators who care about **intent fidelity** across multi-step multi-agent jobs, and want divergence caught by a review gate — not by the end user reacting to a wrong result.

## Who this is *not* a good fit for

- **Low/no token budget** — each worker is a fresh agent context, so this multiplies token consumption. If you're on a tight allowance, the ceremony costs more than it buys.
- **Cloud-first / fast-hosted** users — if your model is already fast and parallel and you have no local-resource incentive to offload, this adds complexity you likely don't need.
- **Trivial workloads only** — if everything is a one-shot answer, keep it inline; this exists for work that *warrants* isolation and parallelism.

## Install

```
git clone https://github.com/w-vitiflow/director-orchestrator-workers
```

Forward this repo to an agent, or read **`agents.md`** — it is written to be pointed at directly by another Hermes agent and contains the complete, self-contained install.

## Contents

```
README.md                                             this file
agents.md                                             point your agents here to install
ARCHITECTURE.md                                       architecture + process (Mermaid)
assets/architecture.svg  .png                         visualisation
kanban-ground-truth-orchestration/
  SKILL.md                                            the reusable skill
  framework-install/
    install.sh                                        idempotent installer (capability + skill)
    patch/                                           unified diff of the core capability
    reference/                                       full patched sources (drift-safe fallback)
```
