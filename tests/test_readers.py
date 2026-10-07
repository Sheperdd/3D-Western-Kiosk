import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

from kiosk import readers
from kiosk.readers import student_numbers


@pytest.fixture
def input_device(monkeypatch: pytest.MonkeyPatch):
    codes = {f"KEY_{digit}": 100 + digit for digit in range(10)}
    ecodes = SimpleNamespace(EV_KEY=1, KEY_ENTER=28, **codes)
    monkeypatch.setitem(sys.modules, "evdev", SimpleNamespace(ecodes=ecodes))

    class InputDevice:
        def __init__(self):
            self.events = []
            self.pending = None
            self.waiting = asyncio.Event()
            self.removed = []
            monkeypatch.setattr(asyncio.get_running_loop(), "remove_reader", self.removed.append)

        def fileno(self):
            return 77

        def feed(self, text, start=0.0):
            for index, character in enumerate(text):
                code = ecodes.KEY_ENTER if character == "\n" else codes.get(f"KEY_{character}", 999)
                timestamp = start + index * 0.01
                self.events.append(
                    SimpleNamespace(
                        type=ecodes.EV_KEY,
                        code=code,
                        value=1,
                        timestamp=lambda timestamp=timestamp: timestamp,
                    )
                )

        def read_loop(self):
            return iter(self.events)

        def async_read_loop(self):
            return self

        def __aiter__(self):
            return self

        def __anext__(self):
            future = asyncio.get_running_loop().create_future()
            if self.events:
                future.set_result(self.events.pop(0))
            else:
                self.pending = future
                self.waiting.set()
            return future

    return InputDevice


@pytest.mark.parametrize("prefix", ["", "1234567890\n", "123?56789\n", "12345\n", "12345"])
def test_async_student_number_reuses_sync_parsing_and_key_filtering(input_device, prefix) -> None:
    async def check() -> None:
        device = input_device()
        device.events.extend(
            SimpleNamespace(type=event_type, code=100, value=value)
            for event_type, value in [(0, 1), (1, 0), (1, 2)]
        )
        device.feed(prefix)
        device.feed("000123456\n", start=3.0)
        device.feed("000654321\n", start=4.0)
        assert list(student_numbers(readers.read_characters(device))) == ["000123456", "000654321"]
        assert await readers.read_student_number_async(device) == "000123456"
        assert device.removed == [device.fileno()]
        assert len(device.events) == 10

    asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
@pytest.mark.parametrize("partial", ["", "000", "000123456"])
def test_async_student_number_discards_partial_input_and_detaches_reader(
    input_device, cancel, partial
) -> None:
    async def check() -> None:
        device = input_device()
        device.feed(partial)
        task = asyncio.create_task(
            readers.read_student_number_async(device, timeout=10.0 if cancel else 0.01)
        )
        try:
            await asyncio.wait_for(device.waiting.wait(), 1)
            assert not task.done()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            else:
                assert await asyncio.wait_for(task, 1) is None
            assert device.removed == [device.fileno()]
            assert device.pending is not None
            assert not device.pending.cancelled()
            device.pending.set_result(SimpleNamespace(type=0, code=0, value=0))
            await asyncio.sleep(0)

            device.feed("123456\n000654321\n")
            assert await readers.read_student_number_async(device) == "000654321"
            assert device.removed == [device.fileno(), device.fileno()]
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("failure", [OSError("Reader disconnected"), TimeoutError("Device failed")])
def test_async_student_number_propagates_device_errors(input_device, failure) -> None:
    async def check() -> None:
        device = input_device()
        task = asyncio.create_task(readers.read_student_number_async(device))
        try:
            await asyncio.wait_for(device.waiting.wait(), 1)
            assert device.pending is not None
            device.pending.set_exception(failure)
            with pytest.raises(type(failure)) as raised:
                await asyncio.wait_for(task, 1)
            assert raised.value is failure
            assert device.removed == [device.fileno()]
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())


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
