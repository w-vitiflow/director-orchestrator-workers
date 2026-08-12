"""Cheap-inline routing for the kanban Director.

A Director should NOT silently decide "this is small enough, do it inline" on a
whim — that is exactly the kind of undocumented judgment that later looks like
an inconsistency. This module makes that decision explicit, mechanical, and
testable: given structured signals about an upcoming piece of work, it returns
a verdict of ``inline`` (do it here, skip the orchestrator/worker ceremony) or
``dispatch`` (create a card and let the pipeline run it), with a human-readable
list of *why*.

Design intent
-------------
The orchestrator->worker ceremony exists to buy parallelism, isolation, and
durable handoff. Each of those has a cost (dispatch latency, a fresh context,
a second summary hop, a review gate). The tripwires below invert the question:
"what would make the ceremony WORTH its cost?" If none of the tripwires is
hit, the work is cheap to do inline and the ceremony is pure overhead. The
converse is also true and equally important: whenever any tripwire IS hit, the
Director must dispatch rather than run inline — running a parallelizable,
long-running, or externally-dependent job inline is how the pipeline's benefits
are thrown away.

The verdict is advisory + auditable: it never blocks the caller, but a caller
that ignores it is making a deliberate, recorded choice to override the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Magic-free, conservative constants so the rule is legible and tunable.
# A job whose *estimated* effort is at or below this is candidate-inline.
DEFAULT_INLINE_EFFORT_MINUTES = 5
# If the job naturally splits into more than this many parallel streams, the
# orchestration fan-out is the whole point -> dispatch.
DEFAULT_PARALLEL_SPLIT_TRIPWIRE = 1


@dataclass
class RoutingSignals:
    """Structured, Director-supplied facts about a piece of work.

    All fields are optional and default to ``None`` = "unknown / assume the
    conservative (dispatch) answer where it matters." The evaluator biases
    toward dispatch on unknown because dispatching a small job wastes a little
    money, but running a big job inline wastes a lot and blocks the Director.
    """

    # Estimated wall-clock effort if run inline (minutes).
    effort_minutes: Optional[int] = None
    # Does the work decompose into independent parallel units?
    # (e.g. render 3 clips on 2 nodes, translate into 4 languages).
    parallel_splits: Optional[int] = None
    # Does it depend on a long-running or external resource the Director
    # shouldn't hold open / wait on (GPU render, model download, remote API
    # with slow latency, a build that takes minutes)?
    external_or_slow_dependency: Optional[bool] = None
    # Does it need a second, independent pair of eyes (verification/review)?
    needs_verification: Optional[bool] = None
    # Would it be harmful/impossible to do from the current session (e.g.
    # it must run in a specific repo worktree/tenant/profile/board)?
    requires_isolation: Optional[bool] = None
    # Does it need durable persistence beyond this session (survive a
    # crash / be audited / be re-run later)?
    needs_durability: Optional[bool] = None


@dataclass
class RoutingVerdict:
    mode: str  # 'inline' | 'dispatch'
    reasons: list = field(default_factory=list)
    signals: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "reasons": list(self.reasons),
            "signals": self.signals or {},
        }


# Named tripwire labels (stable identifiers, not prose) so callers/tests can
# match on them without fragile string equality.
T_INLINE_OK = "inline.no_tripwire_hit"
R_PARALLEL = "dispatch.parallel_split_gt_one"
R_EXTERNAL = "dispatch.external_or_slow_dependency"
R_VERIFY = "dispatch.needs_verification"
R_ISOLATION = "dispatch.requires_isolation"
R_DURABILITY = "dispatch.needs_durability"
R_EFFORT = "dispatch.effort_exceeds_inline_budget"


def assess_routing(signals: RoutingSignals) -> RoutingVerdict:
    """Return the routing verdict for the given signals.

    Any tripwire hit => ``dispatch`` (with reasons). No tripwire hit =>
    ``inline``. Conservative on unknown: an unknown external/slow dependency,
    isolation, durability, or verification requirement dispatches (a missed
    dispatch wastes a little; a missed inline blocks the Director on something
    it shouldn't). Only *effort* biased differently: unknown effort is assumed
    small (inline), because most work the Director self-qualifies as "cheap"
    genuinely is, and the other conservative tripwires already catch the
    dangerous cases.
    """
    reasons: list[str] = []

    if signals.parallel_splits is not None and signals.parallel_splits > DEFAULT_PARALLEL_SPLIT_TRIPWIRE:
        reasons.append(R_PARALLEL)
    # Conservative: unknown external dependency dispatches.
    if signals.external_or_slow_dependency is not False:
        reasons.append(R_EXTERNAL)
    # Conservative: unknown verification dispatches. Only an explicit,
    # positive "no verification needed" allows inline.
    if signals.needs_verification is True:
        reasons.append(R_VERIFY)
    if signals.requires_isolation is True:
        reasons.append(R_ISOLATION)
    if signals.needs_durability is True:
        reasons.append(R_DURABILITY)
    eff = signals.effort_minutes
    if eff is not None and eff > DEFAULT_INLINE_EFFORT_MINUTES:
        reasons.append(R_EFFORT)

    if reasons:
        return RoutingVerdict(
            mode="dispatch",
            reasons=reasons,
            signals=_signals_to_dict(signals),
        )
    return RoutingVerdict(
        mode="inline",
        reasons=[T_INLINE_OK],
        signals=_signals_to_dict(signals),
    )


def _signals_to_dict(signals: RoutingSignals) -> dict:
    return {
        "effort_minutes": signals.effort_minutes,
        "parallel_splits": signals.parallel_splits,
        "external_or_slow_dependency": signals.external_or_slow_dependency,
        "needs_verification": signals.needs_verification,
        "requires_isolation": signals.requires_isolation,
        "needs_durability": signals.needs_durability,
    }
