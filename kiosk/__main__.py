import argparse
import asyncio
import logging

from kiosk.controller import run
from kiosk.events import BackendOnline, CardRead, Event, IdentityConfirmed, ReaderReady


async def main(device: str | None = None) -> None:
    queue: asyncio.Queue[Event] = asyncio.Queue()
    if device is None:
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        queue.put_nowait(CardRead(1, "1234567890", "000123456"))
        queue.put_nowait(IdentityConfirmed(1, "1234567890", "000123456"))
        await run(queue)

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
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Makerspace access kiosk.")
    parser.add_argument("--device", help="OMNIKEY input device path, such as /dev/input/event4.")
    parser.add_argument(
        "--debug-readers", action="store_true", help="Log reader stages and cancellation timing."
    )
    args = parser.parse_args()
    if args.debug_readers:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
        logging.getLogger("kiosk.readers").setLevel(logging.DEBUG)
    try:
        asyncio.run(main(device=args.device))
    except KeyboardInterrupt:
        print("\nStopped.")
