"""Pure transitions for one tap. Persistence and access policy are gatekeeper-owned."""

from dataclasses import dataclass, replace
from string import hexdigits

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
    StartTimeout,
    Tap,
    Timeout,
    TimeoutName,
)


@dataclass(frozen=True)
class Context:
    # Keep the last tap ID after cleanup to reject delayed/repeated presentations.
    tap_id: int = 0
    result: Result | None = None
    reason: str | None = None
    message: str | None = None
    notices: tuple[str, ...] = ()
    first_name: str | None = None
    gatekeeper_online: bool = False
    reader_ready: bool = False


_RESTING = {KioskState.IDLE, KioskState.OFFLINE, KioskState.READER_ERROR}
_ERROR_RESULTS = {
    FailureKind.UNREACHABLE: Result.UNREACHABLE,
    FailureKind.BAD_REQUEST: Result.READ_AGAIN,
    FailureKind.BAD_KEY: Result.NOT_SET_UP,
}


def _valid_uid(uid: str) -> bool:
    # Hexadecimal bytes, without prescribing an unverified card-specific UID length.
    return bool(uid) and len(uid) % 2 == 0 and all(char in hexdigits for char in uid)


def _resting_state(ctx: Context) -> KioskState:
    if not ctx.gatekeeper_online:
        return KioskState.OFFLINE
    if not ctx.reader_ready:
        return KioskState.READER_ERROR
    return KioskState.IDLE


def _end_tap(state: KioskState, ctx: Context) -> tuple[Context, list[Effect]]:
    effects: list[Effect] = []
    if state == KioskState.CHECKING:
        effects.append(CancelTimeout(ctx.tap_id, TimeoutName.TAP))
    if state == KioskState.RESULT:
        effects.append(CancelTimeout(ctx.tap_id, TimeoutName.RESULT))
    ctx = replace(ctx, result=None, reason=None, message=None, notices=(), first_name=None)
    return ctx, effects


def _abort(state: KioskState, ctx: Context) -> tuple[KioskState, Context, list[Effect]]:
    # A tap in flight may still land; the contract says never assume either way.
    ctx, effects = _end_tap(state, ctx)
    return _resting_state(ctx), ctx, effects


def _finish(
    state: KioskState,
    ctx: Context,
    result: Result,
    reason: str | None = None,
    message: str | None = None,
    notices: tuple[str, ...] = (),
    first_name: str | None = None,
) -> tuple[KioskState, Context, list[Effect]]:
    ctx, effects = _end_tap(state, ctx)
    return (
        KioskState.RESULT,
        replace(
            ctx,
            result=result,
            reason=reason,
            message=message,
            notices=notices,
            first_name=first_name,
        ),
        [*effects, StartTimeout(ctx.tap_id, TimeoutName.RESULT)],
    )


def handle(
    state: KioskState, ctx: Context, event: Event
) -> tuple[KioskState, Context, list[Effect]]:
    """Return decisions only; the controller performs all I/O and serializes events.

    Start in OFFLINE with Context(), then confirm gatekeeper and reader readiness.
    Issue each tap at most once; the controller owns the contract's single retry.
    """
    if isinstance(event, GatekeeperOffline):
        return _abort(state, replace(ctx, gatekeeper_online=False))
    if isinstance(event, GatekeeperOnline):
        ctx = replace(ctx, gatekeeper_online=True)
        return (_resting_state(ctx) if state in _RESTING else state), ctx, []

    if isinstance(event, CardRead) and state == KioskState.IDLE:
        if event.tap_id <= ctx.tap_id:
            return state, ctx, []
        ctx = replace(ctx, tap_id=event.tap_id)
        if (
            not _valid_uid(event.uid)
            or len(event.student_number) != 9
            or not event.student_number.isascii()
            or not event.student_number.isdecimal()
        ):
            return _finish(state, ctx, Result.READ_AGAIN)
        return (
            KioskState.CHECKING,
            ctx,
            [
                StartTimeout(ctx.tap_id, TimeoutName.TAP),
                Tap(ctx.tap_id, event.uid.upper(), event.student_number),
            ],
        )

    # Every remaining event is scoped. Cancellation cannot retract already queued events.
    if event.tap_id != ctx.tap_id:
        return state, ctx, []

    if isinstance(event, ReaderFault):
        return _abort(state, replace(ctx, reader_ready=False))
    if isinstance(event, ReaderReady):
        ctx = replace(ctx, reader_ready=True)
        return (_resting_state(ctx) if state in _RESTING else state), ctx, []

    if isinstance(event, BadScan) and state == KioskState.IDLE:
        return _finish(state, ctx, Result.READ_AGAIN, event.reason)

    if isinstance(event, GatekeeperResult) and state == KioskState.CHECKING:
        return _finish(
            state,
            ctx,
            event.result,
            event.reason,
            event.message,
            event.notices,
            event.first_name,
        )
    if isinstance(event, GatekeeperError) and state == KioskState.CHECKING:
        return _finish(state, ctx, _ERROR_RESULTS[event.kind])

    if isinstance(event, CancelSession) and state in {KioskState.CHECKING, KioskState.RESULT}:
        return _abort(state, ctx)

    if isinstance(event, Timeout):
        if event.name == TimeoutName.RESULT and state == KioskState.RESULT:
            return _abort(state, ctx)
        if event.name == TimeoutName.TAP and state == KioskState.CHECKING:
            return _finish(state, ctx, Result.UNREACHABLE)

    return state, ctx, []
