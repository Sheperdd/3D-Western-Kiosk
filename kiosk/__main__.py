import argparse
import asyncio
import os
from functools import partial

import aiohttp
from aiohttp import web

from kiosk.controller import fake_tap, run
from kiosk.display import DISPLAY_DATA, create_app
from kiosk.events import (
    CardRead,
    Event,
    GatekeeperOnline,
    KioskState,
    ReaderReady,
)
from kiosk.gatekeeper import send_tap, watch_health
from kiosk.machine import Context

# Test-stack student Sam (docs/kiosk-api.md), so demo mode also works against gk-stack.
DEMO_UID = "04A1B2C3D4E501"
DEMO_STUDENT_NUMBER = "251900001"


async def main(device: str | None = None) -> None:
    gk_url = os.environ.get("GK_URL")
    kiosk_key = os.environ.get("GK_KIOSK_KEY")
    if device is not None and not (gk_url and kiosk_key):
        raise SystemExit("Hardware mode needs GK_URL and GK_KIOSK_KEY.")

    demo = not gk_url  # The fake gatekeeper: nothing real is checked in or out.
    queue: asyncio.Queue[Event] = asyncio.Queue()

    app = create_app()
    display_data = app[DISPLAY_DATA]

    def update_display(state: KioskState, context: Context, ready_for_card: bool) -> None:
        # No firstName: the gatekeeper's message already greets the student by name.
        display_data[1] = {
            "state": "REARMING" if state == KioskState.IDLE and not ready_for_card else state.name,
            "result": context.result.name if context.result is not None else None,
            "reason": context.reason,
            "message": context.message,
            "notices": list(context.notices),
            "demo": demo,
        }

        if ready_for_card:
            public_status = "WAITING"
        elif state in (KioskState.OFFLINE, KioskState.READER_ERROR):
            public_status = "UNAVAILABLE"
        else:
            public_status = "IN USE"

        display_data[2] = {"status": public_status, "demo": demo}

    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 8000)
        await site.start()

        # One session for the process; base_url and the key header make send_tap path-only.
        async with aiohttp.ClientSession(
            base_url=gk_url,
            headers={"X-Device-Key": kiosk_key or ""},
            timeout=aiohttp.ClientTimeout(total=2),
        ) as session:
            if gk_url:
                sender = partial(send_tap, session)
                health = asyncio.create_task(watch_health(session, queue))
            else:
                sender = fake_tap
                health = None
                queue.put_nowait(GatekeeperOnline())  # The demo gatekeeper is always up.

            try:
                if device is None:
                    queue.put_nowait(ReaderReady(0))

                    def demo_check_in() -> None:
                        queue.put_nowait(CardRead(1, DEMO_UID, DEMO_STUDENT_NUMBER))

                    def demo_check_out() -> None:
                        queue.put_nowait(CardRead(2, DEMO_UID, DEMO_STUDENT_NUMBER))

                    loop = asyncio.get_running_loop()
                    scan_timers = [
                        loop.call_later(10.0, demo_check_in),
                        loop.call_later(30.0, demo_check_out),
                    ]
                    try:
                        await run(queue, on_state_change=update_display, send_tap=sender)
                    finally:
                        for timer in scan_timers:
                            timer.cancel()

                else:
                    from kiosk.readers import open_readers

                    with open_readers(device) as (uid_reader, student_reader):
                        queue.put_nowait(ReaderReady(0))
                        await run(
                            queue,
                            hardware_mode=True,
                            uid_reader=uid_reader,
                            student_reader=student_reader,
                            on_state_change=update_display,
                            send_tap=sender,
                        )
            finally:
                if health is not None:
                    health.cancel()
                    await asyncio.gather(health, return_exceptions=True)
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
