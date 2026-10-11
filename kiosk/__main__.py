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

    def update_display(state: KioskState, outcome: Outcome | None) -> None:
        display_data[1] = {
            "screen": state.name,
            "labels": [outcome.name] if outcome is not None else [],
        }

        if state == KioskState.IDLE:
            public_status = "WAITING"
        elif state in (KioskState.OFFLINE, KioskState.READER_ERROR, KioskState.OUTCOME_UNKNOWN):
            public_status = "UNAVAILABLE"
        else:
            public_status = "IN USE"

        display_data[2] = {
            "screen": "GENERAL INSTRUCTIONS",
            "labels": [public_status, "Makerspace guidance placeholder."],
        }

    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 8000)
        await site.start()

        if device is None:
            queue.put_nowait(BackendOnline())
            queue.put_nowait(ReaderReady(0))
            queue.put_nowait(CardRead(1, "1234567890", "000123456"))
            queue.put_nowait(IdentityConfirmed(1, "1234567890", "000123456"))
            await run(queue, on_state_change=update_display)

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
