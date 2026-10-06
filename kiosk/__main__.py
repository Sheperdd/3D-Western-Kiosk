import asyncio

from kiosk.controller import run
from kiosk.events import BackendOnline, Event, IdentityConfirmed, ReaderReady, UidScan


async def main():
    queue: asyncio.Queue[Event] = asyncio.Queue()
    queue.put_nowait(BackendOnline())
    queue.put_nowait(ReaderReady(0))
    queue.put_nowait(UidScan(1, "1234567890"))
    queue.put_nowait(IdentityConfirmed(1, "1234567890", "1234567890"))

    await run(queue)


if __name__ == "__main__":
    asyncio.run(main())
