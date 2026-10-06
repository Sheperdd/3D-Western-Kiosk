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
    CaptureIdentity,
    Event,
    FailureKind,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderFault,
    ReaderReady,
    RegisterAndActivate,
    StartTimeout,
    StopCapture,
    Timeout,
    TimeoutName,
    UidScan,
)
from kiosk.machine import Context, handle

# Synthetic identifiers only. Leading zeros belong to the identifiers.
UID = "0001ABCD"
STUDENT = "000000001"
READY = Context(backend_online=True, reader_ready=True)
IDENTITY = IdentityConfirmed(1, UID, STUDENT)


def start():
    return handle(KioskState.IDLE, READY, UidScan(1, UID))


def awaiting_identity():
    state, ctx, _ = start()
    return handle(state, ctx, BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED))


def waiting_for(op: BackendOp):
    if op == BackendOp.ACTIVATE_UID:
        return start()
    state, ctx, _ = awaiting_identity()
    return handle(state, ctx, IDENTITY)


@pytest.mark.parametrize("backend_first", [True, False])
def test_startup_requires_both_backend_and_reader_readiness(backend_first: bool) -> None:
    state, ctx = KioskState.OFFLINE, Context()
    events = [BackendOnline(), ReaderReady(0)]
    if not backend_first:
        events.reverse()
    for event in events:
        assert handle(state, ctx, UidScan(1, UID)) == (state, ctx, [])
        state, ctx, effects = handle(state, ctx, event)
        assert effects == []
    assert (state, ctx) == (KioskState.IDLE, READY)


def test_uid_starts_activation_and_optional_identity_capture_without_losing_leading_zeros() -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, UidScan(1, UID.lower()))
    assert state == KioskState.ACTIVATING
    assert ctx.uid == UID
    assert ctx.student_number is None
    assert ctx.pending_op == BackendOp.ACTIVATE_UID
    assert effects == [
        StartTimeout(1, TimeoutName.SESSION),
        CaptureIdentity(1, UID),
        ActivateUid(1, UID),
    ]


@pytest.mark.parametrize("outcome", [Outcome.ACTIVATED, Outcome.ALREADY_ACTIVE])
def test_returning_student_needs_only_uid_and_every_new_tap_rechecks_backend(
    outcome: Outcome,
) -> None:
    state, ctx, _ = start()
    state, ctx, effects = handle(state, ctx, BackendResult(1, BackendOp.ACTIVATE_UID, outcome))
    assert state == KioskState.RESULT
    assert ctx.outcome == outcome
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert StopCapture(1) in effects
    assert StartTimeout(1, TimeoutName.RESULT) in effects

    # A held/repeated read cannot retrigger activation or extend the result timer.
    assert handle(state, ctx, UidScan(1, UID)) == (state, ctx, [])
    state, ctx, _ = handle(state, ctx, Timeout(1, TimeoutName.RESULT))
    assert state == KioskState.IDLE
    assert handle(state, ctx, UidScan(1, UID)) == (state, ctx, [])
    state, ctx, effects = handle(state, ctx, UidScan(2, UID))
    assert state == KioskState.ACTIVATING
    assert ActivateUid(2, UID) in effects


@pytest.mark.parametrize("identity_first", [True, False])
@pytest.mark.parametrize("outcome", [Outcome.REGISTERED_AND_ACTIVE, Outcome.REPLACED_AND_ACTIVE])
def test_registration_and_replacement_accept_both_arrival_orders(
    identity_first: bool, outcome: Outcome
) -> None:
    state, ctx, initial_effects = start()
    unregistered = BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED)
    events = [IDENTITY, unregistered] if identity_first else [unregistered, IDENTITY]
    effects = []
    for index, event in enumerate(events):
        state, ctx, effects = handle(state, ctx, event)
        if index == 0:
            assert state == (
                KioskState.ACTIVATING if identity_first else KioskState.AWAITING_IDENTITY
            )
            assert ctx.outcome is None
            assert effects == []
    assert state == KioskState.REGISTERING
    assert ctx.student_number == STUDENT
    assert effects == [RegisterAndActivate(1, UID, STUDENT)]
    assert ctx.pending_op == BackendOp.REGISTER_AND_ACTIVATE
    # The registration phase shares the original deadline; it doesn't restart the clock.
    assert StartTimeout(1, TimeoutName.SESSION) in initial_effects
    assert not any(isinstance(effect, StartTimeout) for effect in effects)

    state, ctx, effects = handle(
        state, ctx, BackendResult(1, BackendOp.REGISTER_AND_ACTIVATE, outcome)
    )
    assert state == KioskState.RESULT
    assert ctx.outcome == outcome
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert not any(isinstance(effect, (ActivateUid, RegisterAndActivate)) for effect in effects)


@pytest.mark.parametrize("op", list(BackendOp))
@pytest.mark.parametrize(
    "outcome",
    [Outcome.UNKNOWN_STUDENT, Outcome.MISSING_INDUCTION, Outcome.DENIED, Outcome.UID_CONFLICT],
)
def test_backend_denial_selects_feedback_without_any_followup_write(
    op: BackendOp, outcome: Outcome
) -> None:
    state, ctx, _ = waiting_for(op)
    state, ctx, effects = handle(state, ctx, BackendResult(1, op, outcome, "policy_reason"))
    assert state == KioskState.RESULT
    assert ctx.outcome == outcome
    assert ctx.reason == "policy_reason"
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert not any(isinstance(effect, (ActivateUid, RegisterAndActivate)) for effect in effects)


def test_duplicates_and_previous_operation_replies_do_not_repeat_registration() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, IDENTITY)
    assert handle(state, ctx, IDENTITY) == (state, ctx, [])
    assert handle(state, ctx, UidScan(1, UID.lower())) == (state, ctx, [])
    old_reply = BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED)
    state, ctx, _ = handle(state, ctx, old_reply)
    for event in (IDENTITY, old_reply, BackendError(1, BackendOp.ACTIVATE_UID)):
        assert handle(state, ctx, event) == (state, ctx, [])


@pytest.mark.parametrize("uid", ["", "123", "GG00", "00 01", "０１", "00\n"])
def test_invalid_uid_never_reaches_backend(uid: str) -> None:
    state, ctx, effects = handle(KioskState.IDLE, READY, UidScan(1, uid))
    assert state == KioskState.RESULT
    assert ctx.outcome == Outcome.READ_AGAIN
    assert ctx.uid is ctx.pending_op is None
    assert not any(isinstance(effect, (ActivateUid, RegisterAndActivate)) for effect in effects)


@pytest.mark.parametrize("student", ["", "12x", " 123", "１２３", "123\n"])
def test_invalid_student_number_cannot_register(student: str) -> None:
    state, ctx, _ = awaiting_identity()
    state, ctx, effects = handle(state, ctx, IdentityConfirmed(1, UID, student))
    assert state == KioskState.RESULT
    assert ctx.outcome == Outcome.READ_AGAIN
    assert ctx.uid is ctx.student_number is None
    assert not any(isinstance(effect, RegisterAndActivate) for effect in effects)


@pytest.mark.parametrize(
    "event",
    [IdentityConfirmed(1, "0002ABCD", STUDENT), UidScan(1, "0002ABCD"), BadScan(1, "mixed")],
)
def test_conflicting_capture_before_registration_discards_both_identifiers(event: Event) -> None:
    state, ctx, _ = awaiting_identity()
    state, ctx, effects = handle(state, ctx, event)
    assert state == KioskState.RESULT
    assert ctx.outcome == Outcome.READ_AGAIN
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert not any(isinstance(effect, RegisterAndActivate) for effect in effects)


def test_conflicting_student_numbers_during_activation_do_not_overwrite_the_first() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, IDENTITY)
    state, ctx, effects = handle(state, ctx, IdentityConfirmed(1, UID, "000000002"))
    assert state == KioskState.OUTCOME_UNKNOWN
    assert ctx.uid is ctx.student_number is None
    assert ctx.pending_op == BackendOp.ACTIVATE_UID
    assert not any(isinstance(effect, RegisterAndActivate) for effect in effects)


def test_identity_before_a_session_is_ignored() -> None:
    assert handle(KioskState.IDLE, READY, IDENTITY) == (KioskState.IDLE, READY, [])


def test_missing_identity_expires_without_registration() -> None:
    state, ctx, _ = awaiting_identity()
    state, ctx, effects = handle(state, ctx, Timeout(1, TimeoutName.SESSION))
    assert state == KioskState.RESULT
    assert ctx.outcome == Outcome.SESSION_EXPIRED
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert not any(isinstance(effect, RegisterAndActivate) for effect in effects)


def test_cancel_a_start_b_then_delayed_a_events_cannot_affect_b() -> None:
    state, ctx, _ = awaiting_identity()
    state, ctx, _ = handle(state, ctx, CancelSession(1))
    assert state == KioskState.IDLE
    assert ctx.uid is ctx.student_number is ctx.pending_op is None
    assert ctx.session_id == 1
    assert handle(state, ctx, UidScan(1, UID)) == (state, ctx, [])
    state, ctx, _ = handle(state, ctx, UidScan(2, "0002ABCD"))
    for event in (
        IDENTITY,
        UidScan(1, UID),
        BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.ACTIVATED),
        BackendError(1, BackendOp.ACTIVATE_UID),
        Timeout(1, TimeoutName.SESSION),
        CancelSession(1),
        ReaderFault(1, "old failure"),
        ReaderReady(1),
    ):
        assert handle(state, ctx, event) == (state, ctx, [])


@pytest.mark.parametrize("op", list(BackendOp))
@pytest.mark.parametrize(
    "event",
    [
        CancelSession(1),
        Timeout(1, TimeoutName.SESSION),
        BadScan(1, "ambiguous presentation"),
        ReaderFault(1, "field-off timeout"),
        BackendOffline(),
        IdentityConfirmed(1, "0002ABCD", STUDENT),
    ],
)
def test_interrupted_write_holds_until_authoritative_outcome(op: BackendOp, event: Event) -> None:
    state, ctx, _ = waiting_for(op)
    state, ctx, effects = handle(state, ctx, event)
    assert state == KioskState.OUTCOME_UNKNOWN
    assert ctx.pending_op == op
    assert ctx.uid is ctx.student_number is ctx.outcome is None
    assert not any(isinstance(effect, (ActivateUid, RegisterAndActivate)) for effect in effects)
    assert handle(state, ctx, UidScan(2, UID)) == (state, ctx, [])
    # Health recovery alone cannot resolve an outstanding write.
    for health in (BackendOnline(), ReaderReady(1)):
        state, ctx, effects = handle(state, ctx, health)
        assert state == KioskState.OUTCOME_UNKNOWN
        assert effects == []
    result = Outcome.ACTIVATED if op == BackendOp.ACTIVATE_UID else Outcome.REPLACED_AND_ACTIVE
    state, ctx, effects = handle(state, ctx, BackendResult(1, op, result))
    assert state == KioskState.IDLE
    assert ctx.pending_op is ctx.outcome is None  # Never show the departed student's success.
    assert effects == []


@pytest.mark.parametrize("op", list(BackendOp))
@pytest.mark.parametrize("kind", list(FailureKind))
def test_backend_failure_distinguishes_not_sent_from_unknown(
    op: BackendOp, kind: FailureKind
) -> None:
    state, ctx, _ = waiting_for(op)
    state, ctx, _ = handle(state, ctx, BackendError(1, op, kind))
    assert not ctx.backend_online
    assert ctx.uid is ctx.student_number is ctx.outcome is None
    if kind == FailureKind.NOT_SENT:
        assert state == KioskState.OFFLINE
        assert ctx.pending_op is None
        state, ctx, _ = handle(state, ctx, BackendOnline())
        assert state == KioskState.IDLE
    else:
        assert state == KioskState.OUTCOME_UNKNOWN
        assert ctx.pending_op == op
        state, ctx, _ = handle(state, ctx, BackendOnline())
        assert state == KioskState.OUTCOME_UNKNOWN


def test_cancelled_activation_unregistered_reply_does_not_continue_registration() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, IDENTITY)
    state, ctx, _ = handle(state, ctx, CancelSession(1))
    state, ctx, effects = handle(
        state, ctx, BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED)
    )
    assert state == KioskState.IDLE
    assert ctx.pending_op is ctx.outcome is None
    assert effects == []


@pytest.mark.parametrize(
    ("op", "outcome"),
    [
        (BackendOp.ACTIVATE_UID, Outcome.REGISTERED_AND_ACTIVE),
        (BackendOp.REGISTER_AND_ACTIVATE, Outcome.ACTIVATED),
        (BackendOp.REGISTER_AND_ACTIVATE, Outcome.ALREADY_ACTIVE),
        (BackendOp.REGISTER_AND_ACTIVATE, Outcome.UNREGISTERED),
        (BackendOp.ACTIVATE_UID, Outcome.READ_AGAIN),
    ],
)
def test_wrong_response_shape_cannot_claim_success_or_assume_rollback(
    op: BackendOp, outcome: Outcome
) -> None:
    state, ctx, _ = waiting_for(op)
    state, ctx, _ = handle(state, ctx, BackendResult(1, op, outcome))
    assert state == KioskState.OUTCOME_UNKNOWN
    assert ctx.pending_op == op
    assert ctx.outcome is None


@pytest.mark.parametrize("backend_first", [True, False])
def test_recovery_requires_both_health_flags_and_noise_cannot_bypass_offline(backend_first: bool):
    state, ctx, _ = handle(KioskState.IDLE, READY, BackendOffline())
    state, ctx, _ = handle(state, ctx, ReaderFault(0, "field-on timeout"))
    for event in (BadScan(0, "bad input"), Timeout(0, TimeoutName.RESULT), CancelSession(0)):
        assert handle(state, ctx, event) == (state, ctx, [])
    events = [BackendOnline(), ReaderReady(0)]
    if not backend_first:
        events.reverse()
    state, ctx, _ = handle(state, ctx, events[0])
    assert state != KioskState.IDLE
    state, ctx, _ = handle(state, ctx, events[1])
    assert state == KioskState.IDLE


def test_reader_fault_during_write_survives_backend_resolution() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, ReaderFault(1, "field command failed"))
    state, ctx, _ = handle(state, ctx, BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.ACTIVATED))
    assert state == KioskState.READER_ERROR
    assert ctx.outcome is None
    assert handle(state, ctx, UidScan(2, UID)) == (state, ctx, [])
    state, ctx, _ = handle(state, ctx, ReaderReady(1))
    assert state == KioskState.IDLE


def test_result_screen_and_old_timer_cannot_restore_idle_after_backend_loss() -> None:
    state, ctx, _ = start()
    state, ctx, _ = handle(state, ctx, BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.ACTIVATED))
    assert handle(state, ctx, Timeout(1, TimeoutName.SESSION)) == (state, ctx, [])
    state, ctx, _ = handle(state, ctx, BackendOffline())
    assert state == KioskState.OFFLINE
    assert ctx.outcome is None
    assert handle(state, ctx, Timeout(1, TimeoutName.RESULT)) == (state, ctx, [])
