"""Sweep reachable state/context examples as well as stale and contradictory inputs.

Scenario tests establish the product behavior. These checks enforce properties
across the transitions; they do not prove physical same-card assurance or gatekeeper policy.
"""

from typing import get_args

import pytest

from kiosk.events import (
    BadScan,
    CancelSession,
    CancelTimeout,
    CardRead,
    Effect,
    Event,
    FailureKind,
    GatekeeperError,
    GatekeeperOffline,
    GatekeeperOnline,
    GatekeeperResult,
    KioskState,
    ReaderFault,
    ReaderReady,
    Result,
    Tap,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle

UID = "0001ABCD"
SUCCESS = {Result.CHECKED_IN, Result.CHECKED_OUT}
EVENTS: list[Event] = [
    GatekeeperOnline(),
    GatekeeperOffline(),
    *(
        event
        for tap in (0, 1, 2)
        for event in (
            CardRead(tap, UID, "000000001"),
            CardRead(tap, "0002ABCD", "bad"),
            BadScan(tap, "ambiguous"),
            CancelSession(tap),
            ReaderReady(tap),
            ReaderFault(tap, "field timeout"),
            *(Timeout(tap, name) for name in TimeoutName),
            *(GatekeeperResult(tap, result, "CODE", "Message.") for result in Result),
            *(GatekeeperError(tap, kind) for kind in FailureKind),
        )
    ),
]

# Reach each context through handle(), including simultaneous health loss.
SCENARIOS: list[tuple[KioskState, Context]] = [(KioskState.OFFLINE, Context())]
for trace in (
    [],
    [CardRead(1, UID, "000000001")],
    [CardRead(1, UID, "000000001"), GatekeeperResult(1, Result.CHECKED_IN, message="Hi.")],
    [CardRead(1, UID, "bad")],
    [GatekeeperOffline()],
    [ReaderFault(0, "unavailable")],
    [CardRead(1, UID, "000000001"), CancelSession(1)],
    [CardRead(1, UID, "000000001"), ReaderFault(1, "field timeout"), GatekeeperOffline()],
):
    state, ctx = KioskState.IDLE, Context(gatekeeper_online=True, reader_ready=True)
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

    taps = [effect for effect in effects if isinstance(effect, Tap)]
    if new_state != KioskState.RESULT:
        assert new_ctx.result is new_ctx.reason is new_ctx.message is new_ctx.first_name is None
        assert new_ctx.notices == ()
    if new_state == KioskState.IDLE:
        assert new_ctx.gatekeeper_online and new_ctx.reader_ready

    # Leaving a timed state always cancels its timer.
    if state == KioskState.CHECKING and new_state != KioskState.CHECKING:
        assert CancelTimeout(ctx.tap_id, TimeoutName.TAP) in effects
    if state == KioskState.RESULT and new_state != KioskState.RESULT:
        assert CancelTimeout(ctx.tap_id, TimeoutName.RESULT) in effects

    # Only the gatekeeper's answer to the current tap can show success.
    if state != KioskState.RESULT and new_ctx.result in SUCCESS:
        assert isinstance(event, GatekeeperResult)
        assert event.tap_id == ctx.tap_id
        assert state == KioskState.CHECKING

    for effect in taps:
        assert state == KioskState.IDLE and isinstance(event, CardRead)
        assert ctx.gatekeeper_online and ctx.reader_ready
        assert effect.tap_id == new_ctx.tap_id == event.tap_id
        assert len(event.student_number) == 9
        # Replaying an accepted read cannot send the tap twice.
        _, _, repeated = handle(new_state, new_ctx, event)
        assert not any(isinstance(item, Tap) for item in repeated)

    if not isinstance(event, (GatekeeperOnline, GatekeeperOffline)) and event.tap_id < ctx.tap_id:
        assert (new_state, new_ctx, effects) == (state, ctx, [])
