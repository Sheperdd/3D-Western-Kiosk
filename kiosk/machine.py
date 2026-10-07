"""Pure transitions for one student interaction. Persistence and access policy are backend-owned."""

from dataclasses import dataclass, replace
from string import hexdigits

from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOffline,
    BackendOnline,
    BackendOp,
    BackendResult,
    BadScan,
    CancelSession,
    CancelTimeout,
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
    StartTimeout,
    Timeout,
    TimeoutName,
)


@dataclass(frozen=True)
class Context:
    # Keep the last session ID after cleanup to reject delayed/repeated presentations.
    session_id: int = 0
    uid: str | None = None
    observed_student_number: str | None = None
    # Only IdentityConfirmed may populate this trusted registration input.
    student_number: str | None = None
    pending_op: BackendOp | None = None
    outcome: Outcome | None = None
    reason: str | None = None
    backend_online: bool = False
    reader_ready: bool = False


_DENIALS = {
    Outcome.UNKNOWN_STUDENT,
    Outcome.MISSING_INDUCTION,
    Outcome.DENIED,
    Outcome.UID_CONFLICT,
}
_BACKEND_OUTCOMES = {
    BackendOp.ACTIVATE_UID: _DENIALS
    | {Outcome.ACTIVATED, Outcome.ALREADY_ACTIVE, Outcome.UNREGISTERED},
    BackendOp.REGISTER_AND_ACTIVATE: _DENIALS
    | {Outcome.REGISTERED_AND_ACTIVE, Outcome.REPLACED_AND_ACTIVE},
}
_WAITING = {KioskState.ACTIVATING, KioskState.AWAITING_IDENTITY, KioskState.REGISTERING}
_RESTING = {
    KioskState.IDLE,
    KioskState.OFFLINE,
    KioskState.READER_ERROR,
    KioskState.OUTCOME_UNKNOWN,
}


def _valid_uid(uid: str) -> bool:
    # Hexadecimal bytes, without prescribing an unverified card-specific UID length.
    return bool(uid) and len(uid) % 2 == 0 and all(char in hexdigits for char in uid)


def _resting_state(ctx: Context) -> KioskState:
    if ctx.pending_op is not None:
        return KioskState.OUTCOME_UNKNOWN
    if not ctx.backend_online:
        return KioskState.OFFLINE
    if not ctx.reader_ready:
        return KioskState.READER_ERROR
    return KioskState.IDLE


def _end_session(ctx: Context, *, keep_pending: bool = False) -> tuple[Context, list[Effect]]:
    effects: list[Effect] = []
    if ctx.uid is not None:
        effects = [
            CancelTimeout(ctx.session_id, TimeoutName.SESSION),
        ]
    if ctx.outcome is not None:
        effects.append(CancelTimeout(ctx.session_id, TimeoutName.RESULT))
    return (
        replace(
            ctx,
            uid=None,
            observed_student_number=None,
            student_number=None,
            pending_op=ctx.pending_op if keep_pending else None,
            outcome=None,
            reason=None,
        ),
        effects,
    )


def _abort(ctx: Context) -> tuple[KioskState, Context, list[Effect]]:
    # Once an effect could have written, ending the interaction cannot assert it was undone.
    ctx, effects = _end_session(ctx, keep_pending=True)
    return _resting_state(ctx), ctx, effects


def _finish(
    ctx: Context, outcome: Outcome, reason: str | None = None
) -> tuple[KioskState, Context, list[Effect]]:
    ctx, effects = _end_session(ctx)
    return (
        KioskState.RESULT,
        replace(ctx, outcome=outcome, reason=reason),
        [*effects, StartTimeout(ctx.session_id, TimeoutName.RESULT)],
    )


def _register(ctx: Context) -> tuple[KioskState, Context, list[Effect]]:
    assert ctx.uid is not None and ctx.student_number is not None
    return (
        KioskState.REGISTERING,
        replace(ctx, pending_op=BackendOp.REGISTER_AND_ACTIVATE),
        [RegisterAndActivate(ctx.session_id, ctx.uid, ctx.student_number)],
    )


def handle(
    state: KioskState, ctx: Context, event: Event
) -> tuple[KioskState, Context, list[Effect]]:
    """Return decisions only; the controller performs all I/O and serializes events.

    Start in OFFLINE with Context(), then confirm backend and reader readiness.
    Issue each (session_id, op) at most once; retries/restart reconciliation require
    a backend agreement. Session IDs alone never establish same-card identity.
    """
    if isinstance(event, BackendOffline):
        return _abort(replace(ctx, backend_online=False))
    if isinstance(event, BackendOnline):
        ctx = replace(ctx, backend_online=True)
        return (_resting_state(ctx) if state in _RESTING else state), ctx, []

    if isinstance(event, CardRead) and state == KioskState.IDLE:
        if event.session_id <= ctx.session_id:
            return state, ctx, []
        if _resting_state(ctx) != KioskState.IDLE:
            return _resting_state(ctx), ctx, []
        uid = event.uid.upper()
        ctx = replace(
            ctx,
            session_id=event.session_id,
            uid=uid,
            observed_student_number=event.student_number,
        )
        if (
            not _valid_uid(event.uid)
            or len(event.student_number) != 9
            or not event.student_number.isascii()
            or not event.student_number.isdecimal()
        ):
            return _finish(ctx, Outcome.READ_AGAIN)
        return (
            KioskState.ACTIVATING,
            replace(ctx, pending_op=BackendOp.ACTIVATE_UID),
            [
                StartTimeout(ctx.session_id, TimeoutName.SESSION),
                ActivateUid(ctx.session_id, uid),
            ],
        )

    # Every remaining event is scoped. Cancellation cannot retract already queued events.
    if event.session_id != ctx.session_id:
        return state, ctx, []

    if isinstance(event, ReaderFault):
        return _abort(replace(ctx, reader_ready=False))
    if isinstance(event, ReaderReady):
        ctx = replace(ctx, reader_ready=True)
        return (_resting_state(ctx) if state in _RESTING else state), ctx, []

    if isinstance(event, BadScan) and state == KioskState.IDLE:
        return _finish(ctx, Outcome.READ_AGAIN, event.reason)

    if isinstance(event, (BackendResult, BackendError)):
        if ctx.pending_op != event.op or state not in {
            KioskState.ACTIVATING,
            KioskState.REGISTERING,
            KioskState.OUTCOME_UNKNOWN,
        }:
            return state, ctx, []
        if isinstance(event, BackendError):
            ctx = replace(
                ctx,
                backend_online=False,
                pending_op=None if event.kind == FailureKind.NOT_SENT else ctx.pending_op,
            )
            return _abort(ctx)
        if event.outcome not in _BACKEND_OUTCOMES[event.op]:
            # An invalid/partial response is not proof of either success or rollback.
            return _abort(ctx)
        ctx = replace(ctx, pending_op=None)
        if state == KioskState.OUTCOME_UNKNOWN:
            # Resolve the original operation without showing an absent student's result
            # or starting registration from a cancelled activation's UNREGISTERED reply.
            return _abort(ctx)
        if event.outcome == Outcome.UNREGISTERED:
            if ctx.student_number is not None:
                return _register(ctx)
            return KioskState.AWAITING_IDENTITY, ctx, []
        return _finish(ctx, event.outcome, event.reason)

    if isinstance(event, CancelSession):
        if state in _WAITING or state == KioskState.RESULT:
            return _abort(ctx)
        return state, ctx, []

    if isinstance(event, Timeout):
        if event.name == TimeoutName.RESULT and state == KioskState.RESULT:
            return _abort(ctx)
        if event.name == TimeoutName.SESSION and state in _WAITING:
            if ctx.pending_op is not None:
                return _abort(ctx)
            return _finish(ctx, Outcome.SESSION_EXPIRED)
        return state, ctx, []

    if state not in _WAITING:
        return state, ctx, []

    if isinstance(event, IdentityConfirmed):
        if (
            not _valid_uid(event.uid)
            or event.uid.upper() != ctx.uid
            or not event.student_number.isascii()
            or not event.student_number.isdecimal()
            or event.student_number != ctx.observed_student_number
            or ctx.student_number not in (None, event.student_number)
        ):
            if ctx.pending_op is not None:
                return _abort(ctx)
            return _finish(ctx, Outcome.READ_AGAIN)
        ctx = replace(ctx, student_number=event.student_number)
        if state == KioskState.AWAITING_IDENTITY:
            return _register(ctx)
        return state, ctx, []

    if isinstance(event, BadScan) or (
        isinstance(event, CardRead)
        and (event.uid.upper() != ctx.uid or event.student_number != ctx.observed_student_number)
    ):
        if ctx.pending_op is not None:
            return _abort(ctx)
        return _finish(ctx, Outcome.READ_AGAIN)

    return state, ctx, []
