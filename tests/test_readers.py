import asyncio
import threading

import pytest

from kiosk import readers
from kiosk.readers import student_numbers


@pytest.mark.parametrize(
    ("scan", "expected"),
    [
        ("000123456\n", ["000123456"]),
        ("1234567890\n", []),
        ("1234567890\n000123456\n", ["000123456"]),
    ],
    ids=["leading-zeros", "overlong-scan", "valid-scan-after-rejection"],
)
def test_student_numbers_parses_complete_scans(scan: str, expected: list[str]) -> None:
    events = ((index * 0.01, character) for index, character in enumerate(scan))

    assert list(student_numbers(events)) == expected


@pytest.mark.parametrize(
    "result",
    ["0001ABCD", None, RuntimeError("Reader cleanup failed")],
    ids=["uid", "no-card", "cleanup-failure"],
)
@pytest.mark.parametrize(
    "cancellations", [0, 1, 2], ids=["uninterrupted", "cancelled", "cancelled-twice"]
)
def test_read_uid_async_waits_for_worker_cleanup(
    monkeypatch: pytest.MonkeyPatch, result: str | None | RuntimeError, cancellations: int
) -> None:
    async def check() -> None:
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()
        device = object()
        calls = []

        def blocking_read_uid(reader, *, timeout):
            calls.append((reader, timeout))
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(3):
                    raise TimeoutError("Test did not release reader")
                if isinstance(result, RuntimeError):
                    raise result
                return result
            finally:
                finished.set()

        monkeypatch.setattr(readers, "read_uid", blocking_read_uid)
        task = asyncio.create_task(readers.read_uid_async(device, timeout=0.25))
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert calls == [(device, 0.25)]
            assert not task.done()
            for _ in range(cancellations):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert not finished.is_set()

            release.set()
            if isinstance(result, RuntimeError):
                with pytest.raises(RuntimeError, match="Reader cleanup failed") as raised:
                    await asyncio.wait_for(task, 1)
                assert raised.value is result
            elif cancellations:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            else:
                assert await asyncio.wait_for(task, 1) == result
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())
