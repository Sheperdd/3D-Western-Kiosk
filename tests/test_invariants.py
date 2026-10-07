"""Sweep reachable state/context examples as well as stale and contradictory inputs.

Scenario tests establish the product behavior. These checks enforce properties
across the transitions; they do not prove physical same-card assurance or backend policy.
"""

from typing import get_args

import pytest

from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOffline,
    BackendOnline,
    BackendOp,
    BackendResult,
    BadScan,
    CancelSession,
    CardRead,
    Effect,
    Event,
    FailureKind,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderFault,
    ReaderReady,
    RegisterAndActivate,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle

UID = "0001ABCD"
IDENTITY = IdentityConfirmed(1, UID, "000000001")
SUCCESS = {
    Outcome.ACTIVATED,
    Outcome.ALREADY_ACTIVE,
    Outcome.REGISTERED_AND_ACTIVE,
    Outcome.REPLACED_AND_ACTIVE,
}
EVENTS: list[Event] = [
    BackendOnline(),
    BackendOffline(),
    *(
        event
        for session in (0, 1, 2)
        for event in (
            CardRead(session, UID, "000000001"),
            CardRead(session, "0002ABCD", "000000001"),
            IdentityConfirmed(session, UID, "000000001"),
            IdentityConfirmed(session, "0002ABCD", "000000002"),
            BadScan(session, "ambiguous"),
            CancelSession(session),
            ReaderReady(session),
            ReaderFault(session, "field timeout"),
            *(Timeout(session, name) for name in TimeoutName),
            *(BackendResult(session, op, outcome) for op in BackendOp for outcome in Outcome),
            *(BackendError(session, op, kind) for op in BackendOp for kind in FailureKind),
        )
    ),
]

# Reach each context through handle(), including simultaneous health and write uncertainty.
SCENARIOS: list[tuple[KioskState, Context]] = [(KioskState.OFFLINE, Context())]
for trace in (
    [],
    [CardRead(1, UID, "000000001")],
    [CardRead(1, UID, "000000001"), IDENTITY],
    [CardRead(1, UID, "000000001"), BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED)],
    [
        CardRead(1, UID, "000000001"),
        IDENTITY,
        BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED),
    ],
    [CardRead(1, UID, "000000001"), BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.ACTIVATED)],
    [
        CardRead(1, UID, "000000001"),
        BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.MISSING_INDUCTION),
    ],
    [BackendOffline()],
    [ReaderFault(0, "unavailable")],
    [CardRead(1, UID, "000000001"), CancelSession(1)],
    [CardRead(1, UID, "000000001"), ReaderFault(1, "field timeout"), BackendOffline()],
    [
        CardRead(1, UID, "000000001"),
        IDENTITY,
        BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED),
        Timeout(1, TimeoutName.SESSION),
    ],
):
    state, ctx = KioskState.IDLE, Context(backend_online=True, reader_ready=True)
    for event in trace:
        state, ctx, _ = handle(state, ctx, event)
    SCENARIOS.append((state, ctx))


def test_sweep_covers_every_state_and_event_type() -> None:
    assert {state for state, _ in SCENARIOS} == set(KioskState)
    assert {type(event) for event in EVENTS} == set(get_args(Event))


@pytest.mark.parametrize(("state", "ctx"), SCENARIOS)
@pytest.mark.parametrize("event", EVENTS)
def test_transition_invariants(state: KioskState, ctx: Context, event: Event) -> None:
    original = ctx
    new_state, new_ctx, effects = handle(state, ctx, event)
    assert isinstance(new_state, KioskState)
    assert isinstance(new_ctx, Context)
    assert isinstance(effects, list)
    assert all(isinstance(effect, Effect) for effect in effects)
    assert ctx == original
    assert handle(state, ctx, event) == (new_state, new_ctx, effects)

    writes = [
        effect for effect in effects if isinstance(effect, (ActivateUid, RegisterAndActivate))
    ]
    if state in {KioskState.OFFLINE, KioskState.READER_ERROR, KioskState.OUTCOME_UNKNOWN}:
        assert writes == []
    if new_state not in {
        KioskState.ACTIVATING,
        KioskState.AWAITING_IDENTITY,
        KioskState.REGISTERING,
    }:
        assert new_ctx.uid is new_ctx.observed_student_number is new_ctx.student_number is None
    if new_state == KioskState.IDLE:
        assert new_ctx.backend_online and new_ctx.reader_ready
        assert new_ctx.pending_op is None
    if new_state == KioskState.OUTCOME_UNKNOWN:
        assert new_ctx.pending_op is not None
        assert new_ctx.outcome is None

    if state != KioskState.RESULT and new_state == KioskState.RESULT and new_ctx.outcome in SUCCESS:
        assert isinstance(event, BackendResult)
        assert event.session_id == ctx.session_id
        assert event.op == ctx.pending_op
        assert state in {KioskState.ACTIVATING, KioskState.REGISTERING}
        assert new_ctx.outcome == event.outcome

    for effect in writes:
        assert ctx.backend_online and ctx.reader_ready
        assert effect.session_id == new_ctx.session_id
        if isinstance(effect, ActivateUid):
            assert isinstance(event, CardRead)
            assert new_ctx.observed_student_number == event.student_number
            assert len(event.student_number) == 9
        if isinstance(effect, RegisterAndActivate):
            assert effect.uid == new_ctx.uid
            assert effect.student_number == new_ctx.student_number
            assert (
                isinstance(event, IdentityConfirmed) and state == KioskState.AWAITING_IDENTITY
            ) or (
                isinstance(event, BackendResult)
                and event.outcome == Outcome.UNREGISTERED
                and ctx.student_number is not None
            )
        # Replaying an accepted event cannot send the operation twice.
        _, _, repeated = handle(new_state, new_ctx, event)
        assert not any(isinstance(item, (ActivateUid, RegisterAndActivate)) for item in repeated)

    if not isinstance(event, (BackendOnline, BackendOffline)) and event.session_id < ctx.session_id:
        assert (new_state, new_ctx, effects) == (state, ctx, [])
