from dataclasses import replace

import pytest

from kiosk.events import (
    BadScan,
    CancelSession,
    CancelTimeout,
    CardRead,
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
    StartTimeout,
    Tap,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle

# Synthetic identifiers only. Leading zeros belong to the identifiers.
UID = "0001ABCD"
STUDENT = "000000001"
READY = Context(gatekeeper_online=True, reader_ready=True)


def start():
    return handle(KioskState.IDLE, READY, CardRead(1, UID, STUDENT))


@pytest.mark.parametrize("gatekeeper_first", [True, False])
def test_startup_requires_both_gatekeeper_and_reader_readiness(gatekeeper_first: bool) -> None:
    state, ctx = KioskState.OFFLINE, Context()
    events = [GatekeeperOnline(), ReaderReady(0)]
    if not gatekeeper_first:
        events.reverse()
    for event in events:
        assert handle(state, ctx, CardRead(1, UID, STUDENT)) == (state, ctx, [])
        state, ctx, effects = handle(state, ctx, event)
        assert effects == []
    assert (state, ctx) == (KioskState.IDLE, READY)


def test_complete_pair_sends_one_tap() -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, CardRead(1, UID.lower(), STUDENT))
    assert state == KioskState.CHECKING
    assert ctx.tap_id == 1
    assert effects == [StartTimeout(1, TimeoutName.TAP), Tap(1, UID, STUDENT)]


@pytest.mark.parametrize("student", ["", "123", "1234567890", "123?56789", "１２３４５６７８９"])
def test_invalid_student_number_never_reaches_gatekeeper(student: str) -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, CardRead(1, UID, student))
    assert state == KioskState.RESULT
    assert ctx.result == Result.READ_AGAIN
    assert effects == [StartTimeout(1, TimeoutName.RESULT)]


@pytest.mark.parametrize("uid", ["", "123", "GG00", "00 01", "０１", "00\n"])
def test_invalid_uid_never_reaches_gatekeeper(uid: str) -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, CardRead(1, uid, STUDENT))
    assert state == KioskState.RESULT
    assert ctx.result == Result.READ_AGAIN
    assert not any(isinstance(effect, Tap) for effect in effects)


@pytest.mark.parametrize(
    "result",
    [Result.CHECKED_IN, Result.CHECKED_OUT, Result.DENIED, Result.IGNORED_DUPLICATE],
)
def test_gatekeeper_answer_is_shown_as_given(result: Result) -> None:
    state, ctx, _ = start()
    answer = GatekeeperResult(1, result, "SOME_CODE", "Welcome, Sam.", ("Refresher due.",), "Sam")
    state, ctx, effects = handle(state, ctx, answer)
    assert state == KioskState.RESULT
    assert (ctx.result, ctx.reason, ctx.message, ctx.notices, ctx.first_name) == (
        result,
        "SOME_CODE",
        "Welcome, Sam.",
        ("Refresher due.",),
        "Sam",
    )
    assert effects == [CancelTimeout(1, TimeoutName.TAP), StartTimeout(1, TimeoutName.RESULT)]


def test_unknown_reason_code_does_not_crash() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, GatekeeperResult(1, Result.DENIED, "BRAND_NEW_CODE"))
    assert (state, ctx.reason) == (KioskState.RESULT, "BRAND_NEW_CODE")


@pytest.mark.parametrize(
    ("kind", "shown"),
    [
        (FailureKind.UNREACHABLE, Result.UNREACHABLE),
        (FailureKind.BAD_REQUEST, Result.READ_AGAIN),
        (FailureKind.BAD_KEY, Result.NOT_SET_UP),
    ],
)
def test_gatekeeper_error_shows_local_feedback(kind: FailureKind, shown: Result) -> None:
    state, ctx, _ = start()
    state, ctx, effects = handle(state, ctx, GatekeeperError(1, kind))
    assert state == KioskState.RESULT
    assert ctx.result == shown
    assert ctx.gatekeeper_online  # Health polling, not one failed tap, decides offline.
    assert StartTimeout(1, TimeoutName.RESULT) in effects


def test_tap_timeout_shows_unreachable_without_holding() -> None:
    state, ctx, _ = start()
    state, ctx, effects = handle(state, ctx, Timeout(1, TimeoutName.TAP))
    assert state == KioskState.RESULT
    assert ctx.result == Result.UNREACHABLE
    assert effects == [CancelTimeout(1, TimeoutName.TAP), StartTimeout(1, TimeoutName.RESULT)]
    # The reply arriving after the deadline cannot replace what is on screen.
    assert handle(state, ctx, GatekeeperResult(1, Result.CHECKED_IN)) == (state, ctx, [])


def test_result_expiry_clears_the_screen_and_the_next_tap_starts_fresh() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, GatekeeperResult(1, Result.CHECKED_OUT, message="Bye."))
    # A held/repeated read of the same tap cannot tap again or extend the result timer.
    assert handle(state, ctx, CardRead(1, UID, STUDENT)) == (state, ctx, [])
    state, ctx, effects = handle(state, ctx, Timeout(1, TimeoutName.RESULT))
    assert state == KioskState.IDLE
    assert ctx == replace(READY, tap_id=1)
    assert effects == [CancelTimeout(1, TimeoutName.RESULT)]
    assert handle(state, ctx, CardRead(1, UID, STUDENT)) == (state, ctx, [])
    _, _, effects = handle(state, ctx, CardRead(2, UID, STUDENT))
    assert Tap(2, UID, STUDENT) in effects


def test_bad_scan_in_idle_asks_to_read_again() -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, BadScan(0, "student number missing"))
    assert state == KioskState.RESULT
    assert (ctx.result, ctx.reason) == (Result.READ_AGAIN, "student number missing")
    assert effects == [StartTimeout(0, TimeoutName.RESULT)]


@pytest.mark.parametrize(
    ("event", "resting"),
    [
        (CancelSession(1), KioskState.IDLE),
        (ReaderFault(1, "field-off timeout"), KioskState.READER_ERROR),
        (GatekeeperOffline(), KioskState.OFFLINE),
    ],
)
def test_interrupted_tap_rests_and_ignores_the_late_reply(event: Event, resting) -> None:
    state, ctx, _ = start()
    state, ctx, effects = handle(state, ctx, event)
    assert state == resting
    assert ctx.result is None
    assert effects == [CancelTimeout(1, TimeoutName.TAP)]
    for late in (GatekeeperResult(1, Result.CHECKED_IN), GatekeeperError(1)):
        assert handle(state, ctx, late) == (state, ctx, [])


def test_conflicting_or_duplicate_reads_while_checking_are_ignored() -> None:
    state, ctx, _ = start()
    for event in (
        CardRead(1, UID, STUDENT),
        CardRead(1, "0002ABCD", "000000002"),
        CardRead(2, UID, STUDENT),
        BadScan(1, "mixed"),
    ):
        assert handle(state, ctx, event) == (state, ctx, [])


def test_cancel_a_start_b_then_delayed_a_events_cannot_affect_b() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, CancelSession(1))
    assert (state, ctx.tap_id) == (KioskState.IDLE, 1)
    assert handle(state, ctx, CardRead(1, UID, STUDENT)) == (state, ctx, [])
    state, ctx, _ = handle(state, ctx, CardRead(2, "0002ABCD", STUDENT))
    for event in (
        CardRead(1, UID, STUDENT),
        GatekeeperResult(1, Result.CHECKED_OUT),
        GatekeeperError(1),
        Timeout(1, TimeoutName.TAP),
        CancelSession(1),
        ReaderFault(1, "old failure"),
        ReaderReady(1),
    ):
        assert handle(state, ctx, event) == (state, ctx, [])


@pytest.mark.parametrize("gatekeeper_first", [True, False])
def test_recovery_requires_both_health_flags_and_noise_cannot_bypass_offline(
    gatekeeper_first: bool,
) -> None:
    state, ctx, _ = handle(KioskState.IDLE, READY, GatekeeperOffline())
    state, ctx, _ = handle(state, ctx, ReaderFault(0, "field-on timeout"))
    for event in (BadScan(0, "bad input"), Timeout(0, TimeoutName.RESULT), CancelSession(0)):
        assert handle(state, ctx, event) == (state, ctx, [])
    events = [GatekeeperOnline(), ReaderReady(0)]
    if not gatekeeper_first:
        events.reverse()
    state, ctx, _ = handle(state, ctx, events[0])
    assert state != KioskState.IDLE
    state, ctx, _ = handle(state, ctx, events[1])
    assert state == KioskState.IDLE


def test_result_screen_and_old_timer_cannot_restore_idle_after_gatekeeper_loss() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, GatekeeperResult(1, Result.CHECKED_OUT))
    assert handle(state, ctx, Timeout(1, TimeoutName.TAP)) == (state, ctx, [])
    state, ctx, effects = handle(state, ctx, GatekeeperOffline())
    assert state == KioskState.OFFLINE
    assert ctx.result is None
    assert effects == [CancelTimeout(1, TimeoutName.RESULT)]
    assert handle(state, ctx, Timeout(1, TimeoutName.RESULT)) == (state, ctx, [])
