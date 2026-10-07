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

        def read_one(self):
            return self.events.pop(0) if self.events else None

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


@pytest.mark.parametrize(
    "scan", ["000123456\n000123456\n", "", "000123456", "123?56789\n", "1234567890\n"]
)
def test_card_read_drains_before_uid_and_preserves_handover_input(input_device, scan) -> None:
    async def check() -> None:
        device = input_device()
        device.feed("000999999\n")  # Buffered before this attempt, never accepted.
        commands = []
        polls = 0

        class UidReader:
            def call_function(self, command, *, params, response_length):
                assert command == 0x32 and response_length == 0
                commands.append(params)
                if params == b"\x01\x03":
                    assert not device.events  # Also drained before the second UID poll.
                elif polls == 1:
                    device.feed("000888888\n")  # No UID: discard before the next attempt.
                else:
                    device.feed(scan)  # Arrives during RF-off, before its await returns.
                return b""

            def read_passive_target(self, *, timeout):
                nonlocal polls
                polls += 1
                return None if polls == 1 else bytes.fromhex("0001ABCD")

        pair = await asyncio.wait_for(
            readers.read_card_async(UidReader(), device, student_timeout=0.01), 1
        )
        assert pair == (("0001ABCD", "000123456") if scan.startswith("000123456\n") else None)
        assert commands == [b"\x01\x03", b"\x01\x02"] * 2
        assert device.removed == [device.fileno()]
        if pair is not None:
            assert len(device.events) == 10  # Duplicate did not become another acquisition.

    asyncio.run(check())


@pytest.mark.parametrize("failure_at", ["field-on", "uid", "field-off", "drain"])
def test_card_read_propagates_reader_failures_without_a_pair(input_device, failure_at) -> None:
    async def check() -> None:
        device = input_device()
        commands = []

        class UidReader:
            def call_function(self, command, *, params, response_length):
                commands.append(params)
                if (failure_at == "field-on" and params == b"\x01\x03") or (
                    failure_at == "field-off" and params == b"\x01\x02"
                ):
                    return None
                return b""

            def read_passive_target(self, *, timeout):
                if failure_at == "uid":
                    raise RuntimeError("UID failed")
                return bytes.fromhex("0001ABCD")

        def fail_drain():
            raise RuntimeError("Drain failed")

        if failure_at == "drain":
            device.read_one = fail_drain
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(readers.read_card_async(UidReader(), device), 1)
        assert commands == ([] if failure_at == "drain" else [b"\x01\x03", b"\x01\x02"])
        assert not device.waiting.is_set()

    asyncio.run(check())


def test_next_card_discards_previous_duplicate_and_partial_input(input_device, monkeypatch) -> None:
    async def check() -> None:
        device = input_device()
        scans = iter(
            [
                ("0001ABCD", "000000001\n000000001\n000"),
                ("0002ABCD", "000000002\n"),
            ]
        )

        async def read_uid(reader):
            assert not device.events  # Drain belongs before the new UID/RF sequence.
            uid, characters = next(scans)
            device.feed(characters)
            return uid

        monkeypatch.setattr(readers, "read_uid_async", read_uid)
        assert await readers.read_card_async(object(), device) == ("0001ABCD", "000000001")
        assert device.events  # The previous card left a duplicate and partial scan buffered.
        assert await readers.read_card_async(object(), device) == ("0002ABCD", "000000002")
        assert not device.events

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
