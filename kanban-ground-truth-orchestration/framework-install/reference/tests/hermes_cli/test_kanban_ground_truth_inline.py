"""Ground-truth preservation + cheap-inline routing.

Covers two capabilities added together:

1. Ground-truth preservation across orchestration hops: an ``acceptance``
   field on a task carries the original intent + machine-checkable criteria
   forward. A child task that doesn't supply its own acceptance inherits its
   parent's acceptance VERBATIM (never re-summarized), and ``build_worker_context``
   renders it as authoritative ground truth the worker must verify.
2. Cheap-inline routing (``kanban_route.assess_routing``): an explicit,
   mechanical tripwire deciding whether the Director should run work inline or
   dispatch it, instead of deciding on vibes.
"""

from __future__ import annotations

import json

from hermes_cli import kanban_db
from hermes_cli import kanban_route as kr
from hermes_cli import kanban_swarm


def _fresh_conn(tmp_path, monkeypatch):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    conn = kanban_db.connect()
    return conn


# ---------------------------------------------------------------------------
# Ground-truth preservation
# ---------------------------------------------------------------------------

def test_acceptance_stored_and_readable(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"intent": "Render blonde crawl-closer", "checks": ["reveal visible", "identity preserved"]}
        tid = kanban_db.create_task(conn, title="render", acceptance=acc)
        task = kanban_db.get_task(conn, tid)
        assert task.acceptance is not None
        parsed = json.loads(task.acceptance)  # type: ignore[arg-type]
        assert parsed["intent"] == "Render blonde crawl-closer"
        assert parsed["checks"] == ["reveal visible", "identity preserved"]
    finally:
        conn.close()


def test_child_inherits_parent_acceptance_verbatim(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"intent": "original ground truth", "checks": ["a", "b", "c"]}
        parent = kanban_db.create_task(conn, title="parent", acceptance=acc)
        child = kanban_db.create_task(conn, title="child", parents=[parent])
        child_parsed = json.loads(kanban_db.get_task(conn, child).acceptance)  # type: ignore[arg-type]
        # Ground truth (intent + checks) carried VERBATIM across the hop — this
        # is the whole point: the worker checks the ORIGINAL criteria, never a
        # rewritten summary. `source` is provenance metadata (the parent id) and
        # may differ; intent/checks must not.
        assert child_parsed["intent"] == "original ground truth"
        assert child_parsed["checks"] == ["a", "b", "c"]
        # Provenance recorded so the chain is auditable.
        assert "source" in child_parsed
    finally:
        conn.close()


def test_child_with_explicit_acceptance_overrides_inheritance(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        parent = kanban_db.create_task(
            conn, title="parent", acceptance={"intent": "parent intent", "checks": ["x"]}
        )
        own = {"intent": "child intent", "checks": ["y"]}
        child = kanban_db.create_task(conn, title="child", parents=[parent], acceptance=own)
        parsed = json.loads(kanban_db.get_task(conn, child).acceptance)  # type: ignore[arg-type]
        assert parsed["intent"] == "child intent"
    finally:
        conn.close()


def test_worker_context_renders_ground_truth(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"intent": "verify the reveal", "checks": ["frame shows topless", "no side panels"]}
        tid = kanban_db.create_task(conn, title="render", acceptance=acc)
        ctx = kanban_db.build_worker_context(conn, tid)
        assert "Acceptance criteria (GROUND TRUTH" in ctx
        assert "verify the reveal" in ctx
        assert "frame shows topless" in ctx
        assert "no side panels" in ctx
    finally:
        conn.close()


def test_no_acceptance_renders_no_block(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        tid = kanban_db.create_task(conn, title="plain")
        ctx = kanban_db.build_worker_context(conn, tid)
        assert "Acceptance criteria (GROUND TRUTH" not in ctx
    finally:
        conn.close()


def test_malformed_acceptance_degrades_to_none(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"checks": ["no intent key"]}
        tid = kanban_db.create_task(conn, title="bad", acceptance=acc)
        ctx = kanban_db.build_worker_context(conn, tid)
        assert "Acceptance criteria (GROUND TRUTH" not in ctx
        # It still stored (as a dict with no usable intent), but context treats
        # it as absent rather than crashing.
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cheap-inline routing
# ---------------------------------------------------------------------------

def test_route_inline_when_no_tripwire():
    v = kr.assess_routing(
        kr.RoutingSignals(
            effort_minutes=2,
            parallel_splits=1,
            external_or_slow_dependency=False,
            needs_verification=False,
        )
    )
    assert v.mode == "inline"
    assert kr.T_INLINE_OK in v.reasons


def test_route_dispatch_on_parallel_split():
    v = kr.assess_routing(kr.RoutingSignals(parallel_splits=3))
    assert v.mode == "dispatch"
    assert kr.R_PARALLEL in v.reasons


def test_route_dispatch_on_external_dependency():
    v = kr.assess_routing(kr.RoutingSignals(external_or_slow_dependency=True))
    assert v.mode == "dispatch"
    assert kr.R_EXTERNAL in v.reasons


def test_route_dispatch_on_unknown_external_conservative():
    # Unknown external dependency (None) must dispatch conservatively.
    v = kr.assess_routing(kr.RoutingSignals(external_or_slow_dependency=None))
    assert v.mode == "dispatch"
    assert kr.R_EXTERNAL in v.reasons


def test_route_dispatch_on_verification():
    v = kr.assess_routing(kr.RoutingSignals(needs_verification=True))
    assert v.mode == "dispatch"
    assert kr.R_VERIFY in v.reasons


def test_route_dispatch_on_isolation_and_durability():
    v = kr.assess_routing(
        kr.RoutingSignals(requires_isolation=True, needs_durability=True)
    )
    assert v.mode == "dispatch"
    assert kr.R_ISOLATION in v.reasons
    assert kr.R_DURABILITY in v.reasons


def test_route_dispatch_on_high_effort():
    v = kr.assess_routing(kr.RoutingSignals(effort_minutes=60))
    assert v.mode == "dispatch"
    assert kr.R_EFFORT in v.reasons


def test_route_inline_despite_unknown_effort():
    # Unknown effort defaults to inline (assumed small); the conservative
    # tripwires catch the dangerous cases instead.
    v = kr.assess_routing(kr.RoutingSignals(external_or_slow_dependency=False))
    assert v.mode == "inline"


def test_route_verdict_serializable():
    v = kr.assess_routing(kr.RoutingSignals(parallel_splits=3))
    d = v.as_dict()
    assert d["mode"] == "dispatch"
    assert kr.R_PARALLEL in d["reasons"]
    assert "signals" in d


# ---------------------------------------------------------------------------
# Orchestration fan-out (swarm / koor-style) acceptance propagation
# ---------------------------------------------------------------------------

def _swarm_spec(profile, title):
    return kanban_swarm.SwarmWorkerSpec(profile=profile, title=title, body=title)


def test_swarm_propagates_acceptance_to_every_tier(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"intent": "make the clip match the brief", "checks": ["reveal visible", "single shot"]}
        created = kanban_swarm.create_swarm(
            conn,
            goal="render the clip",
            workers=[_swarm_spec("media-worker", "render clip")],
            verifier_assignee="review-worker",
            synthesizer_assignee="ops-worker",
            acceptance=acc,
        )
        root = kanban_db.get_task(conn, created.root_id)
        assert json.loads(root.acceptance)["intent"] == "make the clip match the brief"  # type: ignore[arg-type]
        # Every deployed tier inherits VERBATIM ground truth.
        for wid in created.worker_ids:
            w = json.loads(kanban_db.get_task(conn, wid).acceptance)  # type: ignore[arg-type]
            assert w["intent"] == "make the clip match the brief"
            assert w["checks"] == ["reveal visible", "single shot"]
        v = json.loads(kanban_db.get_task(conn, created.verifier_id).acceptance)  # type: ignore[arg-type]
        assert v["intent"] == "make the clip match the brief"
        s = json.loads(kanban_db.get_task(conn, created.synthesizer_id).acceptance)  # type: ignore[arg-type]
        assert s["intent"] == "make the clip match the brief"
    finally:
        conn.close()


def test_swarm_verifier_context_carries_ground_truth(tmp_path, monkeypatch):
    conn = _fresh_conn(tmp_path, monkeypatch)
    try:
        acc = {"intent": "gate on evidence", "checks": ["evidence sufficient"]}
        created = kanban_swarm.create_swarm(
            conn,
            goal="build feature",
            workers=[_swarm_spec("dev-worker", "implement")],
            verifier_assignee="review-worker",
            synthesizer_assignee="ops-worker",
            acceptance=acc,
        )
        ctx = kanban_db.build_worker_context(conn, created.verifier_id)
        assert "Acceptance criteria (GROUND TRUTH" in ctx
        assert "gate on evidence" in ctx
        assert "evidence sufficient" in ctx
    finally:
        conn.close()

