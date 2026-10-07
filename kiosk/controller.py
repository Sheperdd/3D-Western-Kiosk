import asyncio
import logging

from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOp,
    BackendResult,
    CancelTimeout,
    CaptureIdentity,
    Effect,
    Event,
    FailureKind,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderFault,
    RegisterAndActivate,
    StartTimeout,
    StopCapture,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle


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


async def fake_capture_identity(
    queue: asyncio.Queue[Event],
    effect: CaptureIdentity,
    seconds: float,
    student_number: str,
) -> None:
    try:
        await asyncio.sleep(seconds)
        await queue.put(IdentityConfirmed(effect.session_id, effect.uid, student_number))
    except Exception as e:
        logging.exception("Capture identity request failed with exception: %s", e)
        await queue.put(
            ReaderFault(effect.session_id, f"Capture identity request failed with exception: {e}")
        )


# Laptop demo settings; production durations still need agreement.
DEMO_TIMEOUT_SECONDS: dict[TimeoutName, float] = {
    TimeoutName.SESSION: 10.0,
    TimeoutName.RESULT: 2.0,
}
DEMO_BACKEND_DELAY = 0.1


def dispatch(
    queue: asyncio.Queue[Event],
    effect: Effect,
    timers: dict[tuple[int, TimeoutName], asyncio.Task[None]],
    background_tasks: set[asyncio.Task[None]],
    capture_tasks: dict[int, asyncio.Task[None]],
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

    elif isinstance(effect, CaptureIdentity):
        if not hardware_mode:
            capture_task = asyncio.create_task(
                fake_capture_identity(
                    queue, effect, DEMO_BACKEND_DELAY, student_number="1234567890"
                )
            )
            background_tasks.add(capture_task)
            capture_task.add_done_callback(background_tasks.discard)
            capture_tasks[effect.session_id] = capture_task

    elif isinstance(effect, StopCapture):
        if effect.session_id in capture_tasks:
            capture_tasks[effect.session_id].cancel()
            del capture_tasks[effect.session_id]

    print(type(effect).__name__)


async def run(queue: asyncio.Queue[Event], *, hardware_mode: bool = False) -> None:
    state = KioskState.OFFLINE
    context = Context()
    timers: dict[
        tuple[int, TimeoutName], asyncio.Task[None]
    ] = {}  # session_id, timeout_name -> task
    background_tasks: set[asyncio.Task[None]] = set()
    capture_tasks: dict[int, asyncio.Task[None]] = {}  # session_id -> task

    try:
        while True:
            event = await queue.get()
            print("Processing event:", type(event).__name__)
            state, context, effects = handle(state, context, event)
            print("State: ", state.name, "Outcome: ", context.outcome)
            for effect in effects:
                dispatch(
                    queue,
                    effect,
                    timers,
                    background_tasks,
                    capture_tasks,
                    hardware_mode=hardware_mode,
                )
    finally:
        background_snapshot = list(background_tasks)
        for task in background_snapshot:
            if not task.done() and task.cancelling() == 0:
                task.cancel()

        await asyncio.gather(*background_snapshot, return_exceptions=True)
