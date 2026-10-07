import asyncio
import logging

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


async def fake_activate_uid(
    queue: asyncio.Queue[Event],
    effect: ActivateUid,
    seconds: float,
    desired_outcome: Outcome = Outcome.DENIED,
) -> None:
    try:
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


# Laptop demo settings; production durations still need agreement.
DEMO_TIMEOUT_SECONDS: dict[TimeoutName, float] = {
    TimeoutName.SESSION: 10.0,
    TimeoutName.RESULT: 2.0,
}
DEMO_BACKEND_DELAY = 0.001
STUDENT_NUMBER_TIMEOUT = 10.0  # After UID/RF handover; waiting for a card has no deadline.


def dispatch(
    queue: asyncio.Queue[Event],
    effect: Effect,
    timers: dict[tuple[int, TimeoutName], asyncio.Task[None]],
    background_tasks: set[asyncio.Task[None]],
    *,
    hardware_mode: bool = False,
) -> None:
    if isinstance(effect, StartTimeout):
        if (effect.session_id, effect.name) in timers:
            timers[(effect.session_id, effect.name)].cancel()
        timer = asyncio.create_task(fire_timeout(queue, effect, DEMO_TIMEOUT_SECONDS[effect.name]))
        timers[(effect.session_id, effect.name)] = timer
        background_tasks.add(timer)
        timer.add_done_callback(background_tasks.discard)

    elif isinstance(effect, CancelTimeout):
        if (effect.session_id, effect.name) in timers:
            timers[(effect.session_id, effect.name)].cancel()
            del timers[(effect.session_id, effect.name)]

    elif isinstance(effect, ActivateUid):
        outcome = Outcome.ACTIVATED if hardware_mode else Outcome.UNREGISTERED
        backend_task = asyncio.create_task(
            fake_activate_uid(queue, effect, DEMO_BACKEND_DELAY, outcome)
        )
        background_tasks.add(backend_task)
        backend_task.add_done_callback(background_tasks.discard)

    elif isinstance(effect, RegisterAndActivate):
        backend_task = asyncio.create_task(
            fake_register_and_activate(
                queue, effect, DEMO_BACKEND_DELAY, failure=FailureKind.UNKNOWN
            )
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
) -> None:
    if hardware_mode and (uid_reader is None or student_reader is None):
        raise ValueError("Hardware mode requires both uid_reader and student_reader")

    state = KioskState.OFFLINE
    context = Context()
    timers: dict[
        tuple[int, TimeoutName], asyncio.Task[None]
    ] = {}  # session_id, timeout_name -> task
    background_tasks: set[asyncio.Task[None]] = set()
    # ponytail: one presentation per run; add rearming only with validated card removal.
    acquisition_task: asyncio.Task[None] | None = None
    acquired_scan: CardRead | BadScan | None = None
    admission_revoked = False

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
                reason = (
                    "Incomplete scan: student number missing. Restart and present the card again."
                )
                print(reason)
                acquired_scan = BadScan(session_id, reason)
            else:
                acquired_scan = CardRead(session_id + 1, *pair)
            queue.put_nowait(acquired_scan)
        except Exception as error:
            logging.exception("Card acquisition failed")
            queue.put_nowait(ReaderFault(context.session_id, str(error)))

    try:
        while True:
            event = await queue.get()
            if event is acquired_scan and admission_revoked:
                continue
            if (
                acquisition_task is not None
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
                    hardware_mode=hardware_mode,
                )
            if hardware_mode:
                if state == KioskState.IDLE and context.reader_ready and not admission_revoked:
                    if acquisition_task is None:
                        acquisition_task = asyncio.create_task(acquire_card())
                        background_tasks.add(acquisition_task)
                        acquisition_task.add_done_callback(background_tasks.discard)
                elif acquisition_task is not None:
                    admission_revoked = True
                    if not acquisition_task.done() and acquisition_task.cancelling() == 0:
                        acquisition_task.cancel()
    finally:
        admission_revoked = True
        background_snapshot = list(background_tasks)
        for task in background_snapshot:
            if not task.done() and task.cancelling() == 0:
                task.cancel()

        await asyncio.gather(*background_snapshot, return_exceptions=True)
