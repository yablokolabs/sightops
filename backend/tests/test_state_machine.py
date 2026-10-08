"""The inspection state machine.

The transition table is the single source of truth the agent loop routes
through, so it is checked directly rather than only through the loop.
"""

from __future__ import annotations

import inspect

import pytest

from app.agent import state as state_module
from app.agent.state import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalTransition,
    can_transition,
    is_active,
    transition,
)
from app.models.schemas import InspectionState as S


def test_every_declared_transition_is_accepted():
    for source, targets in TRANSITIONS.items():
        for target in targets:
            assert can_transition(source, target) is True
            assert transition(source, target) is target


def test_every_state_appears_in_the_table():
    assert set(TRANSITIONS) == set(S)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.COMPLETED, S.OBSERVING),
        (S.COMPLETED, S.AWAITING_APPROVAL),
        (S.CANCELLED, S.OBSERVING),
        (S.CANCELLED, S.REASONING),
        (S.CREATED, S.REASONING),
        (S.ANALYZING, S.COMPLETED),
        (S.OBSERVING, S.REASONING),
    ],
)
def test_illegal_transitions_are_rejected(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(IllegalTransition) as excinfo:
        transition(current, target)

    assert excinfo.value.current is current
    assert excinfo.value.target is target
    assert current.value in str(excinfo.value)


def test_cancelled_is_the_only_edge_free_state():
    """``CANCELLED`` ends an inspection for good; ``COMPLETED`` can be re-opened.

    ``COMPLETED → REASONING`` exists so a user who reports "it is still not
    working" after a finished investigation gets another look rather than being
    told to start over. That is why ``COMPLETED`` is terminal for reporting but
    not edge-free.
    """
    assert TRANSITIONS[S.CANCELLED] == set()
    assert TRANSITIONS[S.COMPLETED] == {S.REASONING}


def test_failed_is_recoverable_so_it_is_not_terminal():
    """``FAILED`` records a faulted run, not an ended one.

    Because the loop can retry it from ``OBSERVING``, ``FAILED`` must not sit in
    ``TERMINAL_STATES`` — a state with an outgoing edge is not terminal, and the
    report the API builds from that set would otherwise be wrong. An earlier
    version of the table had both, which this test now pins in the fixed
    direction.
    """
    assert S.FAILED not in TERMINAL_STATES
    assert is_active(S.FAILED) is False
    assert TRANSITIONS[S.FAILED] == {S.OBSERVING}


def test_the_two_return_edges_are_reachable_and_justified():
    """A recorded diagnosis or proposal is not necessarily the end.

    Without these edges the loop can record a diagnosis and then have no legal
    way to raise the resulting incident and approval request.
    """
    assert can_transition(S.DIAGNOSING, S.REASONING)
    assert can_transition(S.ACTION_PROPOSED, S.REASONING)
    assert can_transition(S.COMPLETED, S.REASONING)
    # The module docstring is the human-readable statement of the same table, so
    # it is asserted here too: the two drifting apart is exactly how a state
    # diagram ends up disagreeing with the code.
    assert "edges point back to ``REASONING``" in state_module.__doc__
    assert "``COMPLETED ─▶ REASONING``" in state_module.__doc__
    assert "``FAILED`` is reachable from any active state" in state_module.__doc__


def test_terminal_states_are_not_reported_as_active():
    for terminal in TERMINAL_STATES:
        assert is_active(terminal) is False
    for active in ACTIVE_STATES:
        assert is_active(active) is True


def test_every_active_state_can_reach_a_terminal_state():
    """No state may be a dead end: escalation must always be possible."""
    terminal = {S.COMPLETED, S.FAILED, S.CANCELLED}

    for start in ACTIVE_STATES:
        seen = {start}
        queue = [start]
        reached = False
        while queue:
            current = queue.pop(0)
            if current in terminal:
                reached = True
                break
            for nxt in TRANSITIONS[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        assert reached, f"{start.value} cannot reach COMPLETED, FAILED or CANCELLED"


def test_approval_gate_is_the_only_route_from_a_proposal():
    assert TRANSITIONS[S.AWAITING_APPROVAL] == {S.COMPLETED, S.FAILED, S.CANCELLED}


def test_diagnosing_and_action_proposed_can_return_to_reasoning():
    """A recorded diagnosis must not end the investigation.

    An abnormal measurement still has to become an incident and an approval
    request, so both states return to REASONING.
    """
    assert S.REASONING in TRANSITIONS[S.DIAGNOSING]
    assert S.REASONING in TRANSITIONS[S.ACTION_PROPOSED]
    assert transition(S.DIAGNOSING, S.REASONING) is S.REASONING
    assert transition(S.ACTION_PROPOSED, S.REASONING) is S.REASONING


def test_the_return_edges_are_documented_in_the_module():
    """The transitions above are explained where they are declared."""
    source = inspect.getsource(state_module)
    assert "return to REASONING" in source
    assert "DIAGNOSING" in source and "ACTION_PROPOSED" in source
