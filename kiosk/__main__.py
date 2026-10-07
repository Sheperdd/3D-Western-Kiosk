import argparse
import asyncio

from kiosk.controller import run
from kiosk.events import BackendOnline, Event, IdentityConfirmed, ReaderReady, UidScan


async def main(device: str | None = None) -> None:
    queue: asyncio.Queue[Event] = asyncio.Queue()
    if device is None:
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        queue.put_nowait(UidScan(1, "1234567890"))
        queue.put_nowait(IdentityConfirmed(1, "1234567890", "1234567890"))
        await run(queue)

    else:
        from kiosk.readers import open_readers

        with open_readers(device):
            queue.put_nowait(BackendOnline())
            queue.put_nowait(ReaderReady(0))
            await run(queue, hardware_mode=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Makerspace access kiosk.")
    parser.add_argument("--device", help="OMNIKEY input device path, such as /dev/input/event4.")
    args = parser.parse_args()
    asyncio.run(main(device=args.device))
