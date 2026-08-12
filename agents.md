# agents.md — install this capability onto a Hermes agent

> This file is meant to be **pointed at directly by another agent**. If you are an agent (or a person instructing an agent), read this file and follow the steps. Everything is self-contained in this repository.

## What this installs

A non-blocking **Director → Orchestrator (koor) → kanban workers** pipeline for Hermes, with ground-truth acceptance propagation and a cheap-inline routing tripwire. Concretely, it adds to the target Hermes install:

1. An **`acceptance` field** on kanban cards (JSON: original `intent` + machine-checkable `checks`).
2. **Verbatim inheritance** — a child card created under a parent inherits the parent's acceptance byte-for-byte, so intent never degrades across orchestration hops.
3. **Ground-truth rendering in worker context** — `build_worker_context` shows a worker/verifier the original acceptance criteria to check pass/fail against.
4. **`hermes kanban create --acceptance ...`** and **`hermes kanban swarm --acceptance ...`** flags.
5. **`hermes kanban route-assess`** — a mechanical inline-vs-dispatch tripwire.

## Steps (do this on the target host)

### 1. Clone this repo

```bash
git clone https://github.com/w-vitiflow/director-orchestrator-workers
cd director-orchestrator-workers
```

### 2. Run the self-contained installer

```bash
# From the package's framework-install directory:
cd kanban-ground-truth-orchestration/framework-install
./install.sh                      # auto-detects the hermes-agent source dir, or:
./install.sh /path/to/hermes-agent
```

The installer:
- **backs up** every file it touches to `.kanban-gt-backup-<timestamp>/`,
- **applies the capability** with `git apply --3way` (falls back to full-file copy from `reference/`),
- **installs the skill** into `~/.hermes/skills/kanban-ground-truth-orchestration/`,
- **verifies** `hermes kanban route-assess` exists and its tripwire responds, before reporting success.
- is **idempotent** — running it again is a no-op.

### 3. Restart the target Hermes agent

A running agent will not pick up patched core code until restarted.

### 4. Confirm

```bash
hermes kanban route-assess --help          # it exists (only after the patch)
hermes kanban route-assess --json          # prints inline/dispatch verdict
# create a task with ground truth:
hermes kanban create "my task" --acceptance '{"intent":"do the thing verbatim","checks":["check one"]}'
```

## If the installer reports success but route-assess is missing

- The target host's `hermes` binary may be elsewhere than the detected install dir — pass it explicitly:
  `./install.sh /actual/path/to/hermes-agent`.
- Confirm the agent was restarted after install.
- The `reference/` files are full, correct sources — if the patch base drifted badly and the fallback didn't run, copy the four `reference/hermes_cli/*` files over the install first, then re-run.

## Required base version

The capability sits on top of the standard Hermes kanban core. It does **not** require any upstream merge — this package supplies everything.
