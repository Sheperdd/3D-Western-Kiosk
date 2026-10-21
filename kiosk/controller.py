import asyncio
import logging
from collections.abc import Callable

from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOp,
    BackendResult,
    BadScan,
    CancelSession,
    CancelTimeout,
    CardRead,
    Effect,
    Event,
    FailureKind,
    KioskState,
    Outcome,
    ReaderFault,
    RegisterAndActivate,
    StartTimeout,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle
from kiosk.readers import read_card_async


async def fire_timeout(queue: asyncio.Queue[Event], effect: StartTimeout, seconds: float) -> None:
    await asyncio.sleep(seconds)
    timeout_event = Timeout(effect.session_id, effect.name)
    await queue.put(timeout_event)


# ponytail: in-memory demo visits; lost on restart, which the real ops backend replaces.
DEMO_CHECKED_IN: set[str] = set()


async def fake_activate_uid(
    queue: asyncio.Queue[Event],
    effect: ActivateUid,
    seconds: float,
    desired_outcome: Outcome | None = None,
) -> None:
    """Without desired_outcome, toggle like ops: check out a checked-in UID, else UNREGISTERED."""
    try:
        if desired_outcome is None:
            if effect.uid in DEMO_CHECKED_IN:
                DEMO_CHECKED_IN.discard(effect.uid)
                desired_outcome = Outcome.CHECKED_OUT
            else:
                desired_outcome = Outcome.UNREGISTERED
        await asyncio.sleep(seconds)
        await queue.put(BackendResult(effect.session_id, BackendOp.ACTIVATE_UID, desired_outcome))
    except Exception as e:
        logging.exception("Activation request failed with exception: %s", e)
        await queue.put(
            BackendError(effect.session_id, BackendOp.ACTIVATE_UID, FailureKind.UNKNOWN)
        )


async def fake_register_and_activate(
    queue: asyncio.Queue[Event],
    effect: RegisterAndActivate,
    seconds: float,
    failure: FailureKind | None = None,
) -> None:
    try:
        await asyncio.sleep(seconds)

        if failure is not None:
            await queue.put(
                BackendError(effect.session_id, BackendOp.REGISTER_AND_ACTIVATE, failure)
            )
        else:
            DEMO_CHECKED_IN.add(effect.uid)
            await queue.put(
                BackendResult(
                    effect.session_id,
                    BackendOp.REGISTER_AND_ACTIVATE,
                    Outcome.REGISTERED_AND_ACTIVE,
                )
            )
    except Exception as e:
        logging.exception("Registration request failed with exception: %s", e)
        await queue.put(
            BackendError(effect.session_id, BackendOp.REGISTER_AND_ACTIVATE, FailureKind.UNKNOWN)
        )


# Simulated backend settings for both reader modes; production durations need agreement.
DEMO_TIMEOUT_SECONDS: dict[TimeoutName, float] = {
    TimeoutName.SESSION: 10.0,
}
DEMO_ACTIVATION_DELAY = 2.5
DEMO_REGISTRATION_DELAY = 0.001
STUDENT_NUMBER_TIMEOUT = 10.0  # After UID/RF handover; waiting for a card has no deadline.

# Timers for the displays
RESULT_DURATION_SECONDS: dict[Outcome, float] = {
    Outcome.CHECKED_OUT: 6.0,  # Proposed; tune on the real monitor.
    Outcome.REGISTERED_AND_ACTIVE: 10.0,
    Outcome.REPLACED_AND_ACTIVE: 10.0,
    Outcome.UNKNOWN_STUDENT: 30.0,
    Outcome.MISSING_INDUCTION: 30.0,
    Outcome.DENIED: 10.0,
    Outcome.UID_CONFLICT: 10.0,
    Outcome.READ_AGAIN: 6.0,
    Outcome.SESSION_EXPIRED: 6.0,
}


def dispatch(
    queue: asyncio.Queue[Event],
    effect: Effect,
    timers: dict[tuple[int, TimeoutName], asyncio.Task[None]],
    background_tasks: set[asyncio.Task[None]],
    *,
    outcome: Outcome | None = None,
) -> None:
    if isinstance(effect, StartTimeout):
        if effect.name == TimeoutName.RESULT:
            if outcome is None:
                raise ValueError("Result timer requires an outcome")
            seconds = RESULT_DURATION_SECONDS[outcome]
        else:
            seconds = DEMO_TIMEOUT_SECONDS[effect.name]
        if (effect.session_id, effect.name) in timers:
            timers[(effect.session_id, effect.name)].cancel()
        timer = asyncio.create_task(fire_timeout(queue, effect, seconds))
        timers[(effect.session_id, effect.name)] = timer
        background_tasks.add(timer)
        timer.add_done_callback(background_tasks.discard)

    elif isinstance(effect, CancelTimeout):
        if (effect.session_id, effect.name) in timers:
            timers[(effect.session_id, effect.name)].cancel()
            del timers[(effect.session_id, effect.name)]

    elif isinstance(effect, ActivateUid):
        backend_task = asyncio.create_task(fake_activate_uid(queue, effect, DEMO_ACTIVATION_DELAY))
        background_tasks.add(backend_task)
        backend_task.add_done_callback(background_tasks.discard)

    elif isinstance(effect, RegisterAndActivate):
        backend_task = asyncio.create_task(
            fake_register_and_activate(queue, effect, DEMO_REGISTRATION_DELAY)
        )
        background_tasks.add(backend_task)
        backend_task.add_done_callback(background_tasks.discard)

    print(type(effect).__name__)


async def run(
    queue: asyncio.Queue[Event],
    *,
    hardware_mode: bool = False,
    uid_reader=None,
    student_reader=None,
    on_state_change: Callable[[KioskState, Outcome | None, bool], None] | None = None,
) -> None:
    if hardware_mode and (uid_reader is None or student_reader is None):
        raise ValueError("Hardware mode requires both uid_reader and student_reader")

    state = KioskState.OFFLINE
    context = Context()
    timers: dict[
        tuple[int, TimeoutName], asyncio.Task[None]
    ] = {}  # session_id, timeout_name -> task
    background_tasks: set[asyncio.Task[None]] = set()
    acquisition_task: asyncio.Task[None] | None = None
    acquired_scan: CardRead | BadScan | ReaderFault | None = None
    admission_revoked = False
    next_event: asyncio.Task[Event] | None = None

    async def acquire_card() -> None:
        nonlocal acquired_scan
        session_id = context.session_id
        try:
            pair = await read_card_async(
                uid_reader, student_reader, student_timeout=STUDENT_NUMBER_TIMEOUT
            )
            if (
                admission_revoked
                or state != KioskState.IDLE
                or not context.reader_ready
                or not context.backend_online
                or context.session_id != session_id
            ):
                return
            if pair is None:
                reason = "Incomplete scan: student number missing. Remove the card and try again."
                print(reason)
                acquired_scan = BadScan(session_id, reason)
            else:
                acquired_scan = CardRead(session_id + 1, *pair)
            queue.put_nowait(acquired_scan)
        except Exception as error:
            logging.exception("Card acquisition failed")
            acquired_scan = ReaderFault(context.session_id, str(error))
            queue.put_nowait(acquired_scan)

    try:
        if on_state_change is not None:
            on_state_change(state, context.outcome, False)

        while True:
            if next_event is None:
                next_event = asyncio.create_task(queue.get())
            # Reader cleanup may finish after the last health event; wake for either.
            await asyncio.wait(
                [next_event] if acquisition_task is None else [next_event, acquisition_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if next_event.done():
                event = next_event.result()
                next_event = None
                rejected_scan = False
                if event is acquired_scan:
                    acquired_scan = None
                    rejected_scan = admission_revoked and isinstance(event, (CardRead, BadScan))
                if not rejected_scan:
                    if (
                        (acquisition_task is not None or acquired_scan is not None)
                        and isinstance(event, CancelSession)
                        and event.session_id == context.session_id
                    ):
                        admission_revoked = True
                    print("Processing event:", type(event).__name__)

                    state, context, effects = handle(state, context, event)

                    print("State: ", state.name, "Outcome: ", context.outcome)
                    for effect in effects:
                        dispatch(
                            queue,
                            effect,
                            timers,
                            background_tasks,
                            outcome=context.outcome,
                        )

                    if (
                        hardware_mode
                        and isinstance(event, ReaderFault)
                        and context.pending_op is None
                    ):
                        raise RuntimeError(f"Reader fault: {event.reason}")

            ready_for_card = state == KioskState.IDLE
            if hardware_mode:
                ready = (
                    state == KioskState.IDLE
                    and context.reader_ready
                    and context.backend_online
                    and context.pending_op is None
                )
                if not ready:
                    admission_revoked = True
                if acquisition_task is not None:
                    if acquisition_task.done():
                        acquisition_task = None
                    elif admission_revoked and acquisition_task.cancelling() == 0:
                        acquisition_task.cancel()
                if ready and acquisition_task is None and acquired_scan is None and queue.empty():
                    # shortcut: assume card removal during feedback; add detection if required.
                    admission_revoked = False
                    print("Ready for next card.")
                    acquisition_task = asyncio.create_task(acquire_card())
                    background_tasks.add(acquisition_task)
                    acquisition_task.add_done_callback(background_tasks.discard)
                ready_for_card = ready and acquisition_task is not None and not admission_revoked
            if on_state_change is not None:
                on_state_change(state, context.outcome, ready_for_card)
    finally:
        admission_revoked = True
        background_snapshot = list(background_tasks)
        if next_event is not None:
            next_event.cancel()
        for task in background_snapshot:
            if not task.done() and task.cancelling() == 0:
                task.cancel()

        await asyncio.gather(*background_snapshot, return_exceptions=True)
        if next_event is not None:
            await asyncio.gather(next_event, return_exceptions=True)
