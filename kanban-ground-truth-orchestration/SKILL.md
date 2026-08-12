---
name: kanban-ground-truth-orchestration
description: "Use when orchestrating Hermes kanban work (Director->orchestrator->workers). Encode the original intent as machine-checkable acceptance criteria on the root card so it propagates verbatim to every child (ground-truth preservation), and use the cheap-inline route-assess tripwire to decide inline-vs-dispatch mechanically instead of on vibes. Prevents intent drift and free-riding on the orchestration ceremony."
version: 1.0.0
license: MIT
tags: [hermes, kanban, orchestration, acceptance, ground-truth, routing, director, koor, vitiflow]
---

# Ground-truth orchestration: acceptance propagation + cheap-inline routing

Use this whenever you (the **Director**) are about to hand work into the Hermes
kanban pipeline (Director → orchestrator/koor → workers → verifier). This skill
encodes two hard-won lessons from real incident reports:

1. **Intent drifts at every handoff** unless it is preserved verbatim. A card's
   `body` is free for an orchestrator to rewrite; ground truth must travel
   separately and immutably.
2. **Inline-vs-dispatch is a decision, not a vibe.** Running a parallelizable,
   long-running, or externally-dependent job inline throws away the entire
   point of the pipeline; running a 1-minute task through the full ceremony is
   pure tax.

This capability is implemented in the Hermes kanban core on branch
`feat/ground-truth-inline` (commits `0cc57b3` + `a88a5ff`). The full diff and
tests live there and in `tests/hermes_cli/test_kanban_ground_truth_inline.py`.

---

## When to use

- You are creating a task/card and want to guarantee the worker checks the
  ORIGINAL criteria, not a rewritten summary.
- You are running a koor/swarm (multi-worker fan-out) and the final deliverable
  must satisfy the original brief.
- You are deciding whether small work should be done inline rather than
  dispatched.
- A previously-dispatched job came back wrong because a worker or orchestrator
  did not honor the original intent. (This is the failure mode this skill
  exists to prevent.)

## Ground-truth preservation: encode acceptance on the root

Set the acceptance criteria at the **root** of the orchestration. Children
inherit it **verbatim** — the guarantee is that intent+checks are byte-for-byte
identical down the tree, never re-summarized.

### Single task

```bash
hermes kanban create "<title>" \
  --assignee <worker> \
  --acceptance '{"intent": "<original goal, verbatim>", "checks": ["<machine-checkable criterion 1>", "<criterion 2>"]}'
```

### Koor / swarm fan-out (every deployed tier inherits)

```bash
hermes kanban swarm "<goal>" \
  --worker "<profile>:<title>[:skill,skill]" \
  --worker "<profile2>:<title>" \
  --verifier <review-profile> \
  --synthesizer <writer-profile> \
  --acceptance '{"intent": "<original goal, verbatim>", "checks": ["<criterion 1>", "<criterion 2>"]}'
```

The root, every worker, the verifier, and the synthesizer **all** inherit the
same acceptance. The verifier's worker context renders it as ground truth it
must report pass/fail against — so the review gate judges the original brief,
not a self-summary.

### Acceptance contract (required schema)

```json
{
  "intent": "the original goal, written once, verbatim",
  "checks": ["each machine-checkable acceptance criterion"]
}
```

- `intent` is **required** (non-empty). It is the sentence the orchestrator and
  every worker must not lose or reword.
- `checks` is an explicit list of verifiable criteria. Put items here that an
  independent verifier could confirm. This is the anti-drift anchor.
- `source` is optional and auto-set (`director` on creation, parent id on
  inheritance). Do not hand-set it.
- An **explicit** acceptance on a child **overrides** inheritance (a deliberate,
  local refinement). No acceptance on a child inherits; no acceptance anywhere
  means the card has no ground truth (treated as absent, never crashes).

### Notes / pitfalls

- **Do not paraphrase `intent`** when creating children. If you give a child its
  own acceptance, make sure you are deliberately refining, not accidentally
  drifting.
- Malformed acceptance (bad JSON, missing `intent`) degrades to **no ground
  truth** rather than crashing context build — but that means the protection is
  off, and the worker is back to trusting a summary. Always validate with
  `--json` output before dispatch.

## Cheap-inline routing: consult, don't guess

Before creating a card, ask the mechanical tripwire whether the work even
belongs in the pipeline:

```bash
hermes kanban route-assess \
  [--effort-minutes N] \
  [--parallel-splits N] \
  [--external-slow] \
  [--needs-verification] \
  [--requires-isolation] \
  [--needs-durability]
```

Returns `inline` or `dispatch` with the reason. Use `--json` for machine
parsing. Exit code is 0 in both cases (the verdict is the output).

### Tripwires (any hit → dispatch)

| Signal | Flag | Dispatch reason |
|--------|------|-----------------|
| >1 parallel stream | `--parallel-splits N` | fan-out is the point |
| external/slow dep (GPU, render, download, API) | `--external-slow` | don't hold it inline |
| needs independent review | `--needs-verification` | dispatch with a verifier |
| needs isolated worktree/tenant/profile | `--requires-isolation` | dispatch |
| needs durable persistence/audit | `--needs-durability` | dispatch |
| effort > inline budget (default 5 min) | `--effort-minutes N` | exceeds budget |

**Conservative on unknown.** An unknown external dependency or verification
need defaults to `dispatch` (a missed dispatch wastes a little money; a missed
inline blocks the Director on something it shouldn't). Only unknown *effort*
defaults to inline.

**The rule is advisory but never ignored silently.** The verdict never blocks
the caller, but if you override it you are making a deliberate, recorded choice.
If work is small and none of the tripwires hit → **run it inline** (do it
yourself, no card). If any tripwire hits → **dispatch** with acceptance set at
the root.

## Combined pattern (the intended use)

1. `hermes kanban route-assess ...` → if **inline**, do the work yourself now
   and report; stop.
2. If **dispatch**, create the root **with acceptance** (`--acceptance`),
   either as a single task or a swarm.
3. Every tier inherits the acceptance verbatim; the verifier checks it.
4. Trust the pipeline to fan out and gate, because the original intent is now
   durably attached to every card.

## Install onto a Hermes host

> **The framework installer is the supported path** — it applies the real capability
> (patch/reference) AND installs this skill, then verifies it worked. A bare HRB skill copy
> is only useful if the kanban core already has the capability.

### Option A — framework installer (recommended, self-contained)

This skill ships with `framework-install/` containing the capability patch, full
reference sources, and an idempotent installer. On a fresh Hermes host:

```bash
# 1) get the package
mkdir -p /tmp/vf && cd /tmp/vf
git clone https://github.com/w-vitiflow/director-orchestrator-workers

# 2) run the installer (auto-detects or takes the hermes-agent source dir)
cd agents/skills/kanban-ground-truth-orchestration/framework-install
./install-ground-truth.sh            # auto-detect
./install-ground-truth.sh /path/to/hermes-agent   # or explicit
```

The installer: backs up every touched file, applies the change with
`git apply --3way` (fallback: full-file copy from `reference/`), installs this
skill, verifies `hermes kanban route-assess` works, and is idempotent
(re-running is a no-op). Restart the target Hermes agent afterwards.

### Option B — manual (capability already present)

```bash
mkdir -p ~/.hermes/skills/kanban-ground-truth-orchestration
cp SKILL.md ~/.hermes/skills/kanban-ground-truth-orchestration/SKILL.md
```

Requires the kanban core already patched (present if `git log --oneline` on the
hermes-agent repo shows `0cc57b3`, or if `hermes kanban route-assess --help`
exists).

## Related

- See `agents.md` and `ARCHITECTURE.md` at the repo root for install + design context.
