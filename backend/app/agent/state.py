"""Inspection state machine.

The legal transitions live in one table so the agent cannot invent a state, and
so the state diagram in ``docs/diagrams/inspection-state-machine.svg`` has a
single source of truth to stay in step with.

    CREATED ─▶ OBSERVING ─▶ ANALYZING ─▶ REASONING
                                           │
        ┌──────────────────────────────────┼──────────────────────────┐
        ▼                                  ▼                          ▼
  NEEDS_MORE_EVIDENCE              ACTION_PROPOSED                DIAGNOSING
        │                                  │                          │
        ▼                                  ▼                          ▼
  WAITING_FOR_USER                AWAITING_APPROVAL             (COMPLETED)
        │                                  │                          │
        ▼                                  ▼                          │
   REOBSERVING ─▶ ANALYZING          COMPLETED ◀──────────────────────┘
                                            │
                                            └─▶ REASONING (re-opened)

Three edges point back to ``REASONING``. ``DIAGNOSING ─▶ REASONING`` and
``ACTION_PROPOSED ─▶ REASONING`` exist because a recorded diagnosis is not
necessarily the end of the investigation: an abnormal measurement still has to
become an incident and an approval request. ``COMPLETED ─▶ REASONING`` re-opens
a finished inspection when the user reports the problem is still present,
because "it is still not working" is new evidence rather than a new case.

``FAILED`` is reachable from any active state and is itself recoverable
(``FAILED ─▶ OBSERVING``), so it is a *faulted* state rather than a terminal
one; only ``COMPLETED`` and ``CANCELLED`` end an inspection.
"""

from __future__ import annotations

from app.models.schemas import InspectionState as S

ACTIVE_STATES = {
    S.CREATED,
    S.OBSERVING,
    S.ANALYZING,
    S.REASONING,
    S.NEEDS_MORE_EVIDENCE,
    S.WAITING_FOR_USER,
    S.REOBSERVING,
    S.DIAGNOSING,
    S.ACTION_PROPOSED,
    S.AWAITING_APPROVAL,
}

#: States an inspection cannot leave. ``FAILED`` is deliberately excluded: it
#: records that a run faulted, and the loop can retry it from ``OBSERVING``.
TERMINAL_STATES = {S.COMPLETED, S.CANCELLED}

#: state -> states reachable from it.
TRANSITIONS: dict[S, set[S]] = {
    S.CREATED: {S.OBSERVING, S.FAILED, S.CANCELLED},
    S.OBSERVING: {S.ANALYZING, S.FAILED, S.CANCELLED},
    S.ANALYZING: {S.REASONING, S.FAILED, S.CANCELLED},
    S.REASONING: {
        S.NEEDS_MORE_EVIDENCE,
        S.REOBSERVING,
        S.DIAGNOSING,
        S.ACTION_PROPOSED,
        S.WAITING_FOR_USER,
        S.FAILED,
        S.CANCELLED,
    },
    S.NEEDS_MORE_EVIDENCE: {S.WAITING_FOR_USER, S.REOBSERVING, S.FAILED, S.CANCELLED},
    S.WAITING_FOR_USER: {S.REOBSERVING, S.REASONING, S.DIAGNOSING, S.FAILED, S.CANCELLED},
    S.REOBSERVING: {S.ANALYZING, S.FAILED, S.CANCELLED},
    # DIAGNOSING and ACTION_PROPOSED both return to REASONING. A recorded
    # diagnosis is not necessarily the end of the investigation: an abnormal
    # measurement still has to be turned into an incident and an approval
    # request, and a new observation or a user message can reopen a diagnosis.
    # Without these two edges the loop could record a diagnosis and then have no
    # legal way to act on it.
    S.DIAGNOSING: {S.REASONING, S.COMPLETED, S.ACTION_PROPOSED, S.FAILED, S.CANCELLED},
    S.ACTION_PROPOSED: {S.REASONING, S.AWAITING_APPROVAL, S.COMPLETED, S.FAILED, S.CANCELLED},
    S.AWAITING_APPROVAL: {S.COMPLETED, S.FAILED, S.CANCELLED},
    # Re-opened: the user reports the problem is still present after a completed
    # investigation, which warrants another look rather than a new session.
    S.COMPLETED: {S.REASONING},
    S.FAILED: {S.OBSERVING},
    S.CANCELLED: set(),
}


class IllegalTransition(RuntimeError):
    def __init__(self, current: S, target: S) -> None:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[current])) or "none"
        super().__init__(
            f"cannot move an inspection from {current.value} to {target.value}; "
            f"allowed from {current.value}: {allowed}"
        )
        self.current = current
        self.target = target


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS.get(current, set())


def transition(current: S, target: S) -> S:
    """Validate and return the target state, or raise :class:`IllegalTransition`."""
    if not can_transition(current, target):
        raise IllegalTransition(current, target)
    return target


def is_active(state: S) -> bool:
    return state in ACTIVE_STATES
