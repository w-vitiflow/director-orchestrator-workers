#!/usr/bin/env bash
#
# install-ground-truth.sh — apply the kanban ground-truth + cheap-inline capability
# to a local Hermes Agent install.
#
# Safe / idempotent / reversible:
#   * backs up every file it touches to $AGENT_DIR/.kanban-gt-backup-<ts>/
#   * prefers `git apply --3way` (won't clobber unrelated local edits); falls back
#     to full-file copy from reference/ only if the patch cannot apply cleanly
#   * re-running after a successful install is a no-op (idempotent guard)
#   * verifies the capability is actually live before declaring success
#
# Usage:
#   ./install-ground-truth.sh [AGENT_DIR]
#   AGENT_DIR is the hermes-agent source directory. Auto-detected if omitted.
#
set -euo pipefail

PKG_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ---- locate the target hermes-agent install ----------------------------------
AGENT_DIR="${1:-}"
if [ -z "$AGENT_DIR" ]; then
  for cand in \
    "$HOME/.hermes/hermes-agent" \
    "$HOME/Applications/hermes-agent" \
    /opt/hermes-agent \
    "$HOME/.local/share/hermes-agent"
  do
    if [ -f "$cand/hermes_cli/kanban_db.py" ]; then
      AGENT_DIR="$cand"; break
    fi
  done
fi
if [ -z "$AGENT_DIR" ] || [ ! -f "$AGENT_DIR/hermes_cli/kanban_db.py" ]; then
  echo "ERROR: could not locate hermes-agent (no hermes_cli/kanban_db.py found)." >&2
  echo "Pass the source dir explicitly: $0 /path/to/hermes-agent" >&2
  exit 2
fi
AGENT_DIR="$(cd -- "$AGENT_DIR" && pwd)"
echo "Target hermes-agent install: $AGENT_DIR"

# ---- idempotent guard ---------------------------------------------------------
if grep -q '"acceptance"' "$AGENT_DIR/hermes_cli/kanban_db.py" 2>/dev/null \
  && [ -f "$AGENT_DIR/hermes_cli/kanban_route.py" ]; then
  echo "Already installed (acceptance column + kanban_route.py present). Nothing to do."
  exit 0
fi

FILES=(
  hermes_cli/kanban.py
  hermes_cli/kanban_db.py
  hermes_cli/kanban_route.py
  hermes_cli/kanban_swarm.py
)

# ---- backup ------------------------------------------------------------------
TS="$(date +%Y%m%d-%H%M%S)"
BKUP="$AGENT_DIR/.kanban-gt-backup-$TS"
mkdir -p "$BKUP"
for f in "${FILES[@]}"; do
  if [ -f "$AGENT_DIR/$f" ]; then
    mkdir -p "$BKUP/$(dirname "$f")"
    cp -p "$AGENT_DIR/$f" "$BKUP/$f"
  fi
done
echo "Backed up current files to: $BKUP"

# ---- apply 1: git apply --3way (preferred, merge-safe) ------------------------
PATCH="$PKG_DIR/patch/kanban-ground-truth.patch"
APPLIED=0
if [ -d "$AGENT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
  if (cd "$AGENT_DIR" && git apply --3way --allow-overlap "$PATCH") 2>/dev/null; then
    APPLIED=1
    echo "Applied patch via git apply --3way."
  else
    echo "git apply --3way could not apply cleanly; trying fallback." >&2
  fi
fi

# ---- apply 2: full-file copy from reference/ (drift-safe fallback) -------------
if [ "$APPLIED" -ne 1 ]; then
  for f in "${FILES[@]}"; do
    if [ -f "$PKG_DIR/reference/$f" ]; then
      cp -p "$PKG_DIR/reference/$f" "$AGENT_DIR/$f"
      echo "Replaced $AGENT_DIR/$f from reference/."
    else
      echo "WARNING: no reference for $f — leaving it untouched." >&2
    fi
  done
  APPLIED=1
fi

# ---- install the skill (so the manual + workflow ship together) ---------------
# framework-install/ lives INSIDE the skill dir, so the skill root is $PKG_DIR/..
SKILL_SRC="$PKG_DIR/.."
if [ -d "$SKILL_SRC" ] && [ -f "$SKILL_SRC/SKILL.md" ]; then
  DEST_SKILL="$HOME/.hermes/skills/kanban-ground-truth-orchestration"
  mkdir -p "$DEST_SKILL"
  cp -r "$SKILL_SRC"/* "$DEST_SKILL"/ 2>/dev/null || cp "$SKILL_SRC/SKILL.md" "$DEST_SKILL/"/ 2>/dev/null || true
  echo "Installed skill to $DEST_SKILL"
else
  echo "Note: skill dir not found beside this installer; skipping skill install (capability code is installed)." >&2
fi

# ---- verify ------------------------------------------------------------------
VB="$AGENT_DIR/venv/bin/hermes"
[ -x "$VB" ] || VB="$(command -v hermes || true)"
FAIL=0
if [ -n "$VB" ]; then
  if "$VB" kanban route-assess --json >/dev/null 2>&1; then
    echo "OK: 'hermes kanban route-assess' is available."
    "$VB" kanban route-assess --parallel-splits 2 --json 2>/dev/null | grep -q '"mode": "dispatch"' \
      && echo "OK: route-assess tripwire works (returns dispatch on parallel split)." \
      || { echo "WARN: route-assess ran but tripwire check did not confirm." >&2; FAIL=1; }
  else
    echo "WARN: hermes binary found but route-assess did not respond — check the install." >&2
    FAIL=1
  fi
else
  echo "WARN: no hermes binary found to verify with; files were installed." >&2
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "DONE. Ground-truth orchestration capability installed."
  echo "Restart the target Hermes agent, then:  hermes kanban create/swarm --acceptance '<json>'"
else
  echo "DONE (with warnings). Inspect $AGENT_DIR and re-run to confirm."
  exit 1
fi
