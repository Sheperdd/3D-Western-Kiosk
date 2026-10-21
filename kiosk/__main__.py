import argparse
import asyncio

from aiohttp import web

from kiosk.controller import run
from kiosk.display import DISPLAY_DATA, create_app
from kiosk.events import (
    BackendOnline,
    CardRead,
    Event,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderReady,
)


async def main(device: str | None = None) -> None:
    queue: asyncio.Queue[Event] = asyncio.Queue()

    app = create_app()
    display_data = app[DISPLAY_DATA]

    def update_display(state: KioskState, outcome: Outcome | None, ready_for_card: bool) -> None:
        display_data[1] = {
            "state": "REARMING" if state == KioskState.IDLE and not ready_for_card else state.name,
            "outcome": outcome.name if outcome is not None else None,
        }

        if ready_for_card:
            public_status = "WAITING"
        elif state in (KioskState.OFFLINE, KioskState.READER_ERROR, KioskState.OUTCOME_UNKNOWN):
            public_status = "UNAVAILABLE"
        else:
            public_status = "IN USE"

        display_data[2] = {"status": public_status}

    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 8000)
        await site.start()

        if device is None:
            queue.put_nowait(BackendOnline())
            queue.put_nowait(ReaderReady(0))

            def demo_check_in() -> None:
                queue.put_nowait(CardRead(1, "1234567890", "000123456"))
                # Synthetic demo confirmation; hardware mode never does this.
                queue.put_nowait(IdentityConfirmed(1, "1234567890", "000123456"))

            def demo_check_out() -> None:
                queue.put_nowait(CardRead(2, "1234567890", "000123456"))

            loop = asyncio.get_running_loop()
            scan_timers = [
                loop.call_later(10.0, demo_check_in),
                loop.call_later(30.0, demo_check_out),
            ]
            try:
                await run(queue, on_state_change=update_display)
            finally:
                for timer in scan_timers:
                    timer.cancel()

        else:
            from kiosk.readers import open_readers

            with open_readers(device) as (uid_reader, student_reader):
                queue.put_nowait(BackendOnline())
                queue.put_nowait(ReaderReady(0))
                await run(
                    queue,
                    hardware_mode=True,
                    uid_reader=uid_reader,
                    student_reader=student_reader,
                    on_state_change=update_display,
                )
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Makerspace access kiosk.")
    parser.add_argument("--device", help="OMNIKEY input device path, such as /dev/input/event4.")
    args = parser.parse_args()
    try:
        asyncio.run(main(device=args.device))
    except KeyboardInterrupt:
        print("\nStopped.")
