import asyncio
import logging
from collections.abc import Awaitable, Callable

from kiosk.events import (
    BadScan,
    CancelSession,
    CancelTimeout,
    CardRead,
    Effect,
    Event,
    GatekeeperError,
    GatekeeperResult,
    KioskState,
    ReaderFault,
    Result,
    StartTimeout,
    Tap,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context, handle
from kiosk.readers import read_card_async


async def fire_timeout(queue: asyncio.Queue[Event], effect: StartTimeout, seconds: float) -> None:
    await asyncio.sleep(seconds)
    await queue.put(Timeout(effect.tap_id, effect.name))


type TapSender = Callable[[Tap], Awaitable[GatekeeperResult | GatekeeperError]]

# Demo gatekeeper for running without GK_URL; visits live in memory only.
DEMO_CHECKED_IN: set[str] = set()
DEMO_TAP_DELAY = 2.5


async def fake_tap(tap: Tap) -> GatekeeperResult:
    """Toggle like the gatekeeper: check out a checked-in UID, else check in."""
    await asyncio.sleep(DEMO_TAP_DELAY)
    if tap.uid in DEMO_CHECKED_IN:
        DEMO_CHECKED_IN.discard(tap.uid)
        return GatekeeperResult(tap.tap_id, Result.CHECKED_OUT)
    DEMO_CHECKED_IN.add(tap.uid)
    return GatekeeperResult(tap.tap_id, Result.CHECKED_IN)


async def deliver_tap(queue: asyncio.Queue[Event], send_tap: TapSender, tap: Tap) -> None:
    try:
        event = await send_tap(tap)
    except Exception:
        logging.exception("Tap request failed")
        event = GatekeeperError(tap.tap_id)
    await queue.put(event)


TIMEOUT_SECONDS: dict[TimeoutName, float] = {
    # Must exceed send_tap's worst case (2 attempts x 2 s ClientTimeout), or a late successful
    # retry is ignored and the student's next tap toggles them back.
    TimeoutName.TAP: 5.0,
}
STUDENT_NUMBER_TIMEOUT = 10.0  # After UID/RF handover; waiting for a card has no deadline.

# Timers for the displays
RESULT_DURATION_SECONDS: dict[Result, float] = {
    Result.CHECKED_IN: 10.0,  # Proposed; tune on the real monitor.
    Result.CHECKED_OUT: 6.0,
    # ponytail: one duration for every denial; the signup/orientation QRs need scan time.
    # Key by reason if 30 s blocks the queue for denials without a QR.
    Result.DENIED: 30.0,
    Result.IGNORED_DUPLICATE: 6.0,
    Result.READ_AGAIN: 6.0,
    Result.UNREACHABLE: 6.0,
    Result.NOT_SET_UP: 10.0,
}


def dispatch(
    queue: asyncio.Queue[Event],
    effect: Effect,
    timers: dict[tuple[int, TimeoutName], asyncio.Task[None]],
    background_tasks: set[asyncio.Task[None]],
    *,
    result: Result | None = None,
    send_tap: TapSender = fake_tap,
) -> None:
    task: asyncio.Task[None] | None = None
    if isinstance(effect, StartTimeout):
        if effect.name == TimeoutName.RESULT:
            if result is None:
                raise ValueError("Result timer requires a result")
            seconds = RESULT_DURATION_SECONDS[result]
        else:
            seconds = TIMEOUT_SECONDS[effect.name]
        if (effect.tap_id, effect.name) in timers:
            timers[(effect.tap_id, effect.name)].cancel()
        task = asyncio.create_task(fire_timeout(queue, effect, seconds))
        timers[(effect.tap_id, effect.name)] = task

    elif isinstance(effect, CancelTimeout):
        timer = timers.pop((effect.tap_id, effect.name), None)
        if timer is not None:
            timer.cancel()

    elif isinstance(effect, Tap):
        task = asyncio.create_task(deliver_tap(queue, send_tap, effect))

    if task is not None:
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    print(type(effect).__name__)


async def run(
    queue: asyncio.Queue[Event],
    *,
    hardware_mode: bool = False,
    uid_reader=None,
    student_reader=None,
    on_state_change: Callable[[KioskState, Context, bool], None] | None = None,
    send_tap: TapSender = fake_tap,
) -> None:
    if hardware_mode and (uid_reader is None or student_reader is None):
        raise ValueError("Hardware mode requires both uid_reader and student_reader")

    state = KioskState.OFFLINE
    context = Context()
    timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {}  # tap_id, timeout_name -> task
    background_tasks: set[asyncio.Task[None]] = set()
    acquisition_task: asyncio.Task[None] | None = None
    acquired_scan: CardRead | BadScan | ReaderFault | None = None
    admission_revoked = False
    next_event: asyncio.Task[Event] | None = None

    async def acquire_card() -> None:
        nonlocal acquired_scan
        tap_id = context.tap_id
        try:
            pair = await read_card_async(
                uid_reader, student_reader, student_timeout=STUDENT_NUMBER_TIMEOUT
            )
            if (
                admission_revoked
                or state != KioskState.IDLE
                or not context.reader_ready
                or not context.gatekeeper_online
                or context.tap_id != tap_id
            ):
                return
            if pair is None:
                reason = "Incomplete scan: student number missing. Remove the card and try again."
                print(reason)
                acquired_scan = BadScan(tap_id, reason)
            else:
                acquired_scan = CardRead(tap_id + 1, *pair)
            queue.put_nowait(acquired_scan)
        except Exception as error:
            logging.exception("Card acquisition failed")
            acquired_scan = ReaderFault(context.tap_id, str(error))
            queue.put_nowait(acquired_scan)

    try:
        if on_state_change is not None:
            on_state_change(state, context, False)

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
                        and event.tap_id == context.tap_id
                    ):
                        admission_revoked = True
                    print("Processing event:", type(event).__name__)

                    state, context, effects = handle(state, context, event)

                    print("State: ", state.name, "Result: ", context.result)
                    for effect in effects:
                        dispatch(
                            queue,
                            effect,
                            timers,
                            background_tasks,
                            result=context.result,
                            send_tap=send_tap,
                        )

                    if (
                        hardware_mode
                        and isinstance(event, ReaderFault)
                        and event.tap_id == context.tap_id
                    ):
                        raise RuntimeError(f"Reader fault: {event.reason}")

            ready_for_card = state == KioskState.IDLE
            if hardware_mode:
                ready = (
                    state == KioskState.IDLE and context.reader_ready and context.gatekeeper_online
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
                on_state_change(state, context, ready_for_card)
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
