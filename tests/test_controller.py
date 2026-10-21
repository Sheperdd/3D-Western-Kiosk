import asyncio
from types import SimpleNamespace

import pytest

from kiosk import controller, readers
from kiosk.events import (
    CancelSession,
    CancelTimeout,
    CardRead,
    Event,
    FailureKind,
    GatekeeperError,
    GatekeeperOffline,
    GatekeeperOnline,
    GatekeeperResult,
    KioskState,
    ReaderFault,
    ReaderReady,
    Result,
    StartTimeout,
    Tap,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context


@pytest.fixture(autouse=True)
def fresh_demo_visits(monkeypatch: pytest.MonkeyPatch) -> None:
    # The fake backend's checked-in set is module state; don't leak it between tests.
    monkeypatch.setattr(controller, "DEMO_CHECKED_IN", set())


@pytest.mark.parametrize("number", ["000123456", None, OSError("Reader disconnected")])
def test_gatekeeper_waits_until_student_number_is_collected(
    monkeypatch: pytest.MonkeyPatch, number
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        reading_number = asyncio.Event()
        release_number = asyncio.Event()
        backend_calls = []
        terminal = asyncio.Event()
        events = []
        original_handle = controller.handle

        def observe(state, context, event):
            events.append(event)
            result = original_handle(state, context, event)
            if isinstance(event, (GatekeeperResult, ReaderFault)) or result[0] == KioskState.RESULT:
                terminal.set()
            return result

        async def read_uid(reader):
            return "0001ABCD"

        async def read_number(reader, *, timeout):
            reading_number.set()
            await release_number.wait()
            if isinstance(number, OSError):
                raise number
            return number

        async def tap(effect):
            backend_calls.append(effect)
            return GatekeeperResult(effect.tap_id, Result.CHECKED_OUT)

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(readers, "read_uid_async", read_uid)
        monkeypatch.setattr(readers, "read_student_number_async", read_number)
        queue.put_nowait(GatekeeperOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=object(),
                student_reader=SimpleNamespace(read_one=lambda: None),
                send_tap=tap,
            )
        )
        try:
            await asyncio.wait_for(reading_number.wait(), 1)
            assert backend_calls == [], "UID alone started a tap"
            assert not any(isinstance(event, CardRead) for event in events)
            release_number.set()
            await asyncio.wait_for(terminal.wait(), 1)
            completed = [event for event in events if isinstance(event, CardRead)]
            if isinstance(number, str):
                assert completed == [CardRead(1, "0001ABCD", number)]
                assert backend_calls == [Tap(1, "0001ABCD", number)]
            else:
                assert completed == backend_calls == []
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    "uid_reader,student_reader", [(None, None), (object(), None), (None, object())]
)
def test_hardware_requires_both_readers(uid_reader, student_reader) -> None:
    async def check() -> None:
        with pytest.raises(ValueError, match="requires both uid_reader and student_reader"):
            await asyncio.wait_for(
                controller.run(
                    asyncio.Queue(),
                    hardware_mode=True,
                    uid_reader=uid_reader,
                    student_reader=student_reader,
                ),
                1,
            )

    asyncio.run(check())


@pytest.mark.parametrize("tap_id", [0, 2], ids=["stale", "future"])
def test_hardware_ignores_reader_fault_from_another_session(tap_id: int) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        for event in [
            GatekeeperOnline(),
            ReaderReady(0),
            CardRead(1, "0001ABCD", "invalid"),  # Result feedback, no backend write.
            ReaderFault(tap_id, "Wrong session"),
            ReaderFault(1, "Current reader failure"),
        ]:
            queue.put_nowait(event)
        with pytest.raises(RuntimeError, match="Current reader failure"):
            await asyncio.wait_for(
                controller.run(
                    queue, hardware_mode=True, uid_reader=object(), student_reader=object()
                ),
                1,
            )

    asyncio.run(check())


@pytest.mark.parametrize("reader_fails", [False, True], ids=["uid", "reader-fault"])
def test_hardware_acquisition_waits_for_readiness_and_rearms_when_ready(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], reader_fails: bool
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[tuple[Event, KioskState, Context]] = asyncio.Queue()
        original_handle = controller.handle
        reader = object()
        calls = []
        rearmed = asyncio.Event()
        blocker = asyncio.Event()

        def observe(state, context, event):
            result = original_handle(state, context, event)
            observed.put_nowait((event, result[0], result[1]))
            return result

        async def read_uid(uid_reader):
            calls.append(uid_reader)
            if len(calls) > (1 if reader_fails else 2):
                rearmed.set()
                await blocker.wait()
            await asyncio.sleep(0)
            if reader_fails:
                raise RuntimeError("RF-off failed")
            return None if len(calls) == 1 else "0001ABCD"

        async def read_student_number(student_reader, *, timeout):
            return "000000001"

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(readers, "read_uid_async", read_uid)
        monkeypatch.setattr(readers, "read_student_number_async", read_student_number)
        monkeypatch.setattr(controller, "DEMO_TAP_DELAY", 0)
        monkeypatch.setattr(controller, "DEMO_CHECKED_IN", {"0001ABCD"})
        monkeypatch.setitem(controller.RESULT_DURATION_SECONDS, Result.CHECKED_OUT, 0)
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=reader,
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            queue.put_nowait(GatekeeperOnline())
            _, state, _ = await asyncio.wait_for(observed.get(), 1)
            assert state == KioskState.READER_ERROR
            assert not calls
            queue.put_nowait(ReaderReady(0))
            _, state, _ = await asyncio.wait_for(observed.get(), 1)
            assert state == KioskState.IDLE

            event, state, context = await asyncio.wait_for(observed.get(), 1)
            if reader_fails:
                assert event == ReaderFault(0, "RF-off failed")
                assert state == KioskState.READER_ERROR
                assert context.tap_id == 0
                # Hardware mode exits so systemd restarts it; there is no in-process rearm.
                with pytest.raises(RuntimeError, match="Reader fault: RF-off failed"):
                    await asyncio.wait_for(runner, 1)
                assert calls == [reader]
                return
            else:
                assert event == CardRead(1, "0001ABCD", "000000001")
                assert state == KioskState.CHECKING
                event, state, context = await asyncio.wait_for(observed.get(), 1)
                assert event == GatekeeperResult(1, Result.CHECKED_OUT)
                assert state == KioskState.RESULT
                assert context.result == Result.CHECKED_OUT

            _, state, _ = await asyncio.wait_for(observed.get(), 1)
            assert state == KioskState.IDLE
            queue.put_nowait(GatekeeperOnline())
            event, _, _ = await asyncio.wait_for(observed.get(), 1)
            assert event == GatekeeperOnline()
            await asyncio.wait_for(rearmed.wait(), 1)
            assert calls == [reader] * (2 if reader_fails else 3)
            assert observed.empty()
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())
    output = capsys.readouterr().out
    assert output.count("UID received.") == (0 if reader_fails else 1)
    assert "0001ABCD" not in output and "000000001" not in output


@pytest.mark.parametrize("pair", [("0001ABCD", "000000001"), None])
def test_hardware_discards_queued_scan_after_readiness_is_lost_and_restored(
    monkeypatch: pytest.MonkeyPatch,
    pair,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[Event] = asyncio.Queue()
        original_handle = controller.handle
        calls = []
        rearmed = asyncio.Event()
        blocker = asyncio.Event()

        def observe(state, context, event):
            observed.put_nowait(event)
            return original_handle(state, context, event)

        async def read_card(reader, student_reader, *, student_timeout):
            calls.append(reader)
            if len(calls) > 1:
                rearmed.set()
                await blocker.wait()
            queue.put_nowait(GatekeeperOffline())
            queue.put_nowait(GatekeeperOnline())
            return pair

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        queue.put_nowait(GatekeeperOnline())
        queue.put_nowait(ReaderReady(0))
        reader = object()
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=reader,
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            for expected in [
                GatekeeperOnline(),
                ReaderReady(0),
                GatekeeperOffline(),
                GatekeeperOnline(),
            ]:
                assert await asyncio.wait_for(observed.get(), 1) == expected
            queue.put_nowait(ReaderReady(0))
            assert await asyncio.wait_for(observed.get(), 1) == ReaderReady(0)
            await asyncio.wait_for(rearmed.wait(), 1)
            assert calls == [reader, reader]
            assert observed.empty()
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    "interruption",
    [None, GatekeeperOffline(), ReaderFault(0, "Reader disconnected"), CancelSession(0)],
    ids=["shutdown", "backend-offline", "reader-fault", "cancel-session"],
)
def test_hardware_acquisition_cancellation_drains_cleanup(
    monkeypatch: pytest.MonkeyPatch, interruption: Event | None
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        cleanup_finished = asyncio.Event()
        recovered = asyncio.Event()
        blocker = asyncio.Event()
        events = []
        calls = []
        original_handle = controller.handle

        def observe(state, context, event):
            events.append(event)
            result = original_handle(state, context, event)
            if cleanup_started.is_set() and result[0] == KioskState.IDLE:
                recovered.set()
            return result

        async def read_card(reader, student_reader, *, student_timeout):
            calls.append(reader)
            started.set()
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                pass  # Even a reader that returns late must not get its pair admitted.
            finally:
                cleanup_started.set()
                await release_cleanup.wait()
                cleanup_finished.set()
            return "0001ABCD", "000000001"

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        queue.put_nowait(GatekeeperOnline())
        queue.put_nowait(ReaderReady(0))
        reader = object()
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=reader,
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            if interruption is None:
                runner.cancel()
            else:
                queue.put_nowait(interruption)
            await asyncio.wait_for(cleanup_started.wait(), 1)
            reader_fault = isinstance(interruption, ReaderFault)
            if interruption is not None and not reader_fault:
                queue.put_nowait(GatekeeperOnline())
                queue.put_nowait(ReaderReady(0))
                await asyncio.wait_for(recovered.wait(), 1)
                assert calls == [reader]
                runner.cancel()
            await asyncio.sleep(0)
            # A reader-fault exit must also wait for cleanup before the devices close.
            assert not runner.done()
            assert not cleanup_finished.is_set()
            release_cleanup.set()
            with pytest.raises(RuntimeError if reader_fault else asyncio.CancelledError):
                await asyncio.wait_for(runner, 1)
            assert cleanup_finished.is_set()
            assert not any(isinstance(event, CardRead) for event in events)
            assert queue.empty()
        finally:
            release_cleanup.set()
            if not runner.done() and runner.cancelling() == 0:
                runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("first_pair", [("0001ABCD", "000000001"), None])
@pytest.mark.parametrize("outcome", [Result.CHECKED_OUT, Result.DENIED])
@pytest.mark.parametrize("second_uid", ["0001ABCD", "0002ABCD"])
def test_repeated_scans_wait_for_feedback_and_collect_both_again(
    monkeypatch: pytest.MonkeyPatch, first_pair, outcome, second_uid
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[tuple[Event, KioskState, Context]] = asyncio.Queue()
        result_timers: asyncio.Queue[asyncio.Event] = asyncio.Queue()
        second_started = asyncio.Event()
        release_second = asyncio.Event()
        blocker = asyncio.Event()
        calls = []
        reads = 0
        original_handle = controller.handle

        def observe(state, context, event):
            result = original_handle(state, context, event)
            observed.put_nowait((event, result[0], result[1]))
            return result

        async def read_card(reader, student_reader, *, student_timeout):
            nonlocal reads
            reads += 1
            if reads == 1:
                return first_pair
            assert reads == 2
            second_started.set()
            await release_second.wait()
            return second_uid, "000000002"

        async def tap(effect):
            calls.append(effect)
            return GatekeeperResult(effect.tap_id, outcome)

        async def timer(queue, effect, seconds):
            if effect.name == TimeoutName.TAP:
                await blocker.wait()
            else:
                gate = asyncio.Event()
                result_timers.put_nowait(gate)
                await gate.wait()
                queue.put_nowait(Timeout(effect.tap_id, effect.name))

        async def reach_result():
            while True:
                event, state, context = await observed.get()
                if state == KioskState.RESULT:
                    return context

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        queue.put_nowait(GatekeeperOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=object(),
                student_reader=object(),
                send_tap=tap,
            )
        )
        try:
            first = await asyncio.wait_for(reach_result(), 1)
            first_timer = await asyncio.wait_for(result_timers.get(), 1)
            assert first.result == (Result.READ_AGAIN if first_pair is None else outcome)
            assert reads == 1
            assert not second_started.is_set()
            assert len(calls) == int(first_pair is not None)
            first_timer.set()
            await asyncio.wait_for(second_started.wait(), 1)
            assert len(calls) == int(first_pair is not None)  # Waiting for the new pair.
            release_second.set()
            second = await asyncio.wait_for(reach_result(), 1)
            assert second.tap_id == first.tap_id + 1
            assert second.result == outcome
            assert calls[-1] == Tap(second.tap_id, second_uid, "000000002")
            assert len(calls) == 1 + int(first_pair is not None)
            assert reads == 2
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


# Reader faults exit in hardware mode instead of rearming; see the drains_cleanup test.
@pytest.mark.parametrize("interruption", [GatekeeperOffline(), CancelSession(0)])
def test_rearm_waits_for_cancelled_reader_cleanup_without_another_event(
    monkeypatch: pytest.MonkeyPatch, interruption
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        first_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        recovered = asyncio.Event()
        second_started = asyncio.Event()
        blocker = asyncio.Event()
        events = []
        displays = []
        reads = 0
        original_handle = controller.handle

        def observe(state, context, event):
            events.append(event)
            result = original_handle(state, context, event)
            if cleanup_started.is_set() and result[0] == KioskState.IDLE:
                recovered.set()
            return result

        def display(state, context, ready_for_card):
            displays.append((state, ready_for_card))

        async def read_card(reader, student_reader, *, student_timeout):
            nonlocal reads
            reads += 1
            if reads == 2:
                second_started.set()
                await blocker.wait()
                return None
            first_started.set()
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release_cleanup.wait()
                return "0001ABCD", "000000001"  # Late result must be discarded.

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        queue.put_nowait(GatekeeperOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=object(),
                student_reader=object(),
                on_state_change=display,
            )
        )
        try:
            await asyncio.wait_for(first_started.wait(), 1)
            queue.put_nowait(interruption)
            await asyncio.wait_for(cleanup_started.wait(), 1)
            queue.put_nowait(GatekeeperOnline())
            queue.put_nowait(ReaderReady(0))
            await asyncio.wait_for(recovered.wait(), 1)
            assert reads == 1
            assert not second_started.is_set()
            assert displays[-1] == (KioskState.IDLE, False)
            release_cleanup.set()  # No further event is needed to wake the controller.
            await asyncio.wait_for(second_started.wait(), 1)
            assert reads == 2
            assert displays[-1] == (KioskState.IDLE, True)
            assert not any(isinstance(event, (CardRead, GatekeeperResult)) for event in events)
        finally:
            release_cleanup.set()
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


def test_tap_exception_emits_unreachable_error() -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def broken(tap):
            raise RuntimeError("Injected gatekeeper failure")

        await controller.deliver_tap(queue, broken, Tap(12, "0001ABCD", "000000001"))
        assert queue.get_nowait() == GatekeeperError(12, FailureKind.UNREACHABLE)
        assert queue.empty()

    asyncio.run(check())


def test_tap_cancellation_propagates_without_error_event() -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def cancelled(tap):
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await controller.deliver_tap(queue, cancelled, Tap(12, "0001ABCD", "000000001"))
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize("name", list(TimeoutName))
def test_timer_emits_matching_session_and_name(name: TimeoutName) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        await controller.fire_timeout(queue, StartTimeout(8, name), 0)
        assert queue.get_nowait() == Timeout(8, name)
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize(
    ("name", "result", "expected_seconds"),
    [
        (TimeoutName.TAP, None, 13.0),
        (TimeoutName.RESULT, Result.CHECKED_IN, 10.0),
        (TimeoutName.RESULT, Result.CHECKED_OUT, 6.0),
        (TimeoutName.RESULT, Result.DENIED, 30.0),
        (TimeoutName.RESULT, Result.IGNORED_DUPLICATE, 6.0),
        (TimeoutName.RESULT, Result.READ_AGAIN, 6.0),
        (TimeoutName.RESULT, Result.UNREACHABLE, 6.0),
        (TimeoutName.RESULT, Result.NOT_SET_UP, 10.0),
    ],
)
def test_timer_dispatch_uses_configured_duration(
    monkeypatch: pytest.MonkeyPatch,
    name: TimeoutName,
    result: Result | None,
    expected_seconds: float,
) -> None:
    async def check() -> None:
        monkeypatch.setattr(
            controller,
            "TIMEOUT_SECONDS",
            {TimeoutName.TAP: 13.0},
        )
        durations: list[float] = []

        async def record_delay(seconds: float) -> None:
            durations.append(seconds)

        monkeypatch.setattr(controller.asyncio, "sleep", record_delay)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        controller.dispatch(queue, StartTimeout(8, name), {}, tasks, result=result)
        await asyncio.gather(*tasks)
        assert durations == [expected_seconds]
        assert queue.get_nowait() == Timeout(8, name)
        assert queue.empty()

    asyncio.run(check())


def test_result_timer_rejects_missing_result() -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        key = (8, TimeoutName.RESULT)
        old_task = asyncio.create_task(controller.fire_timeout(queue, StartTimeout(*key), 60))
        timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {key: old_task}
        tasks: set[asyncio.Task[None]] = {old_task}
        try:
            with pytest.raises(ValueError):
                controller.dispatch(queue, StartTimeout(*key), timers, tasks)
            assert timers == {key: old_task}
            assert tasks == {old_task}
            assert old_task.cancelling() == 0
            assert queue.empty()
        finally:
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("name", list(TimeoutName))
@pytest.mark.parametrize("replace", [False, True], ids=["cancel", "replace"])
def test_timer_dispatch_cancels_old_task(
    monkeypatch: pytest.MonkeyPatch, replace: bool, name: TimeoutName
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {}
        tasks: set[asyncio.Task[None]] = set()
        release = asyncio.Event()

        async def controlled_timer(queue, effect, seconds):
            await release.wait()
            await controller_original_timer(queue, effect, 0)

        controller_original_timer = controller.fire_timeout
        monkeypatch.setattr(controller, "fire_timeout", controlled_timer)
        start = StartTimeout(1, name)
        key = (start.tap_id, start.name)
        controller.dispatch(queue, start, timers, tasks, result=Result.CHECKED_OUT)
        old_task = timers[key]
        await asyncio.sleep(0)  # Let the original timer start waiting.

        if replace:
            controller.dispatch(queue, start, timers, tasks, result=Result.CHECKED_OUT)
            assert timers[key] is not old_task
        else:
            controller.dispatch(queue, CancelTimeout(*key), timers, tasks)
            assert key not in timers

        release.set()
        await asyncio.gather(old_task, *timers.values(), return_exceptions=True)
        assert old_task.cancelled()
        if replace:
            assert queue.get_nowait() == Timeout(*key)
        assert queue.empty()

        # Repeated cancellation and cancellation of absent timers are harmless.
        controller.dispatch(queue, CancelTimeout(*key), timers, tasks)
        controller.dispatch(queue, CancelTimeout(*key), timers, tasks)
        assert not timers

    asyncio.run(check())


def test_cancellation_does_not_touch_other_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        monkeypatch.setitem(controller.TIMEOUT_SECONDS, TimeoutName.TAP, 0)
        monkeypatch.setitem(controller.RESULT_DURATION_SECONDS, Result.CHECKED_OUT, 0)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {}
        tasks: set[asyncio.Task[None]] = set()
        keys = [(1, TimeoutName.TAP), (1, TimeoutName.RESULT), (2, TimeoutName.TAP)]
        for key in keys:
            controller.dispatch(queue, StartTimeout(*key), timers, tasks, result=Result.CHECKED_OUT)
        scheduled = list(timers.values())
        controller.dispatch(queue, CancelTimeout(*keys[0]), timers, tasks)
        await asyncio.gather(*scheduled, return_exceptions=True)
        assert set(timers) == set(keys[1:])
        assert {queue.get_nowait(), queue.get_nowait()} == {Timeout(*key) for key in keys[1:]}
        assert queue.empty()

    asyncio.run(check())


def test_tap_dispatch_tracks_and_releases_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        durations: list[float] = []

        async def record_delay(seconds: float) -> None:
            durations.append(seconds)

        monkeypatch.setattr(controller.asyncio, "sleep", record_delay)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        controller.dispatch(queue, Tap(4, "0001ABCD", "000000001"), {}, tasks)
        assert len(tasks) == 1
        await asyncio.gather(*tasks)
        assert not tasks
        assert queue.qsize() == 1
        assert durations == [2.5]

    asyncio.run(check())


@pytest.mark.parametrize("hardware_mode", [False, True])
@pytest.mark.parametrize("checked_in", [False, True], ids=["check-in", "check-out"])
def test_default_gatekeeper_toggles_without_readers(
    monkeypatch: pytest.MonkeyPatch, hardware_mode: bool, checked_in: bool
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        results = asyncio.Queue()

        def observe(state, context, ready_for_card):
            if state == KioskState.RESULT:
                results.put_nowait(context.result)

        monkeypatch.setattr(controller, "DEMO_TAP_DELAY", 0)
        monkeypatch.setattr(controller, "DEMO_CHECKED_IN", {"0001ABCD"} if checked_in else set())
        for event in [GatekeeperOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=hardware_mode,
                uid_reader=object(),
                student_reader=object(),
                on_state_change=observe,
            )
        )
        try:
            result = await asyncio.wait_for(results.get(), 1)
            assert result == (Result.CHECKED_OUT if checked_in else Result.CHECKED_IN)
            # The next tap of the same card flips the visit the other way.
            assert ("0001ABCD" in controller.DEMO_CHECKED_IN) is not checked_in
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        (GatekeeperResult(1, Result.CHECKED_IN, message="Welcome, Sam."), Result.CHECKED_IN),
        (GatekeeperResult(1, Result.CHECKED_OUT), Result.CHECKED_OUT),
        (GatekeeperResult(1, Result.DENIED, "UNKNOWN_STUDENT"), Result.DENIED),
        (GatekeeperError(1, FailureKind.UNREACHABLE), Result.UNREACHABLE),
        (GatekeeperError(1, FailureKind.BAD_KEY), Result.NOT_SET_UP),
        (None, Result.UNREACHABLE),
    ],
    ids=["check-in", "check-out", "denial", "unreachable", "bad-key", "tap-timeout"],
)
def test_controller_flow(
    monkeypatch: pytest.MonkeyPatch,
    reply: GatekeeperResult | GatekeeperError | None,
    shown: Result,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[tuple[KioskState, Result | None]] = asyncio.Queue()
        tap_expiry = asyncio.Event()
        result_expiry = asyncio.Event()

        def observe(state, context, ready_for_card):
            observed.put_nowait((state, context.result))

        async def tap(effect):
            if reply is not None:
                return reply
            tap_expiry.set()  # No answer; the tap deadline fires instead.
            await asyncio.Event().wait()
            raise AssertionError("Cancelled before answering")

        async def timer(queue, effect, seconds):
            await (tap_expiry if effect.name == TimeoutName.TAP else result_expiry).wait()
            await queue.put(Timeout(effect.tap_id, effect.name))

        async def reach(target):
            while True:
                state, result = await observed.get()
                if state == target:
                    return result

        monkeypatch.setattr(controller, "fire_timeout", timer)
        for event in [GatekeeperOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(controller.run(queue, on_state_change=observe, send_tap=tap))
        try:
            await asyncio.wait_for(reach(KioskState.CHECKING), 1)
            assert await asyncio.wait_for(reach(KioskState.RESULT), 1) == shown
            result_expiry.set()
            assert await asyncio.wait_for(reach(KioskState.IDLE), 1) is None
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("hardware_mode", [False, True])
def test_shutdown_cancels_and_awaits_timer_and_backend(
    monkeypatch: pytest.MonkeyPatch, hardware_mode: bool
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        children: list[asyncio.Task[None]] = []
        all_started = asyncio.Event()
        blocker = asyncio.Event()
        finished: list[asyncio.Task[None]] = []

        async def wait_until_cancelled() -> None:
            task = asyncio.current_task()
            assert task is not None
            children.append(task)
            if len(children) == 2:
                all_started.set()
            try:
                await blocker.wait()
            finally:
                # Cleanup yields, so merely requesting cancellation is insufficient.
                await asyncio.sleep(0)
                finished.append(task)

        async def timer(queue, effect, seconds):
            await wait_until_cancelled()

        async def tap(effect):
            await wait_until_cancelled()
            raise AssertionError("Cancelled before answering")

        monkeypatch.setattr(controller, "fire_timeout", timer)
        for event in [GatekeeperOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=hardware_mode,
                uid_reader=object(),
                student_reader=SimpleNamespace(read_one=lambda: None),
                send_tap=tap,
            )
        )
        try:
            await asyncio.wait_for(all_started.wait(), timeout=1)
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(runner, timeout=1)

            # Assert before test cleanup or asyncio.run() can finish leaked tasks.
            assert len(children) == 2
            assert all(task.cancelled() for task in children)
            assert set(finished) == set(children)
        finally:
            for task in [runner, *children]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(runner, *children, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("replace", [False, True], ids=["cancelled", "replaced"])
def test_shutdown_awaits_removed_timer_cleanup(
    monkeypatch: pytest.MonkeyPatch, replace: bool
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        timer_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        cleanup_finished = asyncio.Event()
        blocker = asyncio.Event()
        original_dispatch = controller.dispatch
        captured_timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {}
        captured_tasks: set[asyncio.Task[None]] = set()
        old_task: asyncio.Task[None] | None = None

        def capture_dispatch(
            queue,
            effect,
            timers,
            background_tasks,
            *,
            result: Result | None = None,
            send_tap,
        ):
            nonlocal captured_timers, captured_tasks
            captured_timers = timers
            captured_tasks = background_tasks
            original_dispatch(
                queue,
                effect,
                timers,
                background_tasks,
                result=result,
                send_tap=send_tap,
            )

        async def timer(queue, effect, seconds):
            nonlocal old_task
            if old_task is not None:
                await blocker.wait()
                return
            old_task = asyncio.current_task()
            timer_started.set()
            try:
                await blocker.wait()
            finally:
                cleanup_started.set()
                await release_cleanup.wait()
                cleanup_finished.set()

        async def tap(effect):
            await blocker.wait()
            raise AssertionError("Cancelled before answering")

        monkeypatch.setattr(controller, "dispatch", capture_dispatch)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        for event in [GatekeeperOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)
        runner = asyncio.create_task(controller.run(queue, send_tap=tap))
        tracked: list[asyncio.Task[None]] = []
        try:
            await asyncio.wait_for(timer_started.wait(), 1)
            assert old_task is not None
            key = (1, TimeoutName.TAP)
            effect = StartTimeout(*key) if replace else CancelTimeout(*key)
            original_dispatch(queue, effect, captured_timers, captured_tasks)
            await asyncio.wait_for(cleanup_started.wait(), 1)

            assert old_task not in captured_timers.values()
            assert old_task in captured_tasks
            tracked = list(captured_tasks)
            runner.cancel()
            await asyncio.sleep(0)  # Let shutdown reach its task-cancellation loop.
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(runner, 1)

            # Assert before test cleanup can conceal unfinished child tasks.
            assert cleanup_finished.is_set(), "Shutdown interrupted an already-cancelling timer"
            assert all(task.done() for task in tracked)
            assert not captured_tasks
        finally:
            release_cleanup.set()
            remaining = {runner, *tracked, *captured_tasks}
            for task in remaining:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)

    asyncio.run(check())


# Hardware reader faults exit the process; the machine tests cover that transition.
@pytest.mark.parametrize("hardware_mode", [False, True])
@pytest.mark.parametrize(
    ("interruption", "resting_state"),
    [(CancelSession(1), KioskState.IDLE), (GatekeeperOffline(), KioskState.OFFLINE)],
    ids=["cancel-session", "gatekeeper-offline"],
)
def test_interrupted_tap_rests_at_once_and_ignores_the_late_reply(
    monkeypatch: pytest.MonkeyPatch,
    hardware_mode: bool,
    interruption: Event,
    resting_state: KioskState,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        release_reply = asyncio.Event()
        started = asyncio.Event()
        rested = asyncio.Event()
        late_reply_handled = asyncio.Event()
        rearmed = asyncio.Event()
        blocker = asyncio.Event()
        reads = 0
        states: list[KioskState] = []
        original_handle = controller.handle

        def observe_event(state, context, event):
            result = original_handle(state, context, event)
            if isinstance(event, GatekeeperResult):
                late_reply_handled.set()
            return result

        def observe(state, context, ready_for_card):
            states.append(state)
            if started.is_set() and state == resting_state:
                rested.set()

        async def tap(effect):
            started.set()
            await release_reply.wait()
            return GatekeeperResult(effect.tap_id, Result.CHECKED_IN)

        async def read_card(reader, student_reader, *, student_timeout):
            nonlocal reads
            reads += 1
            if reads == 1:
                return "0001ABCD", "000000001"
            rearmed.set()
            await blocker.wait()

        monkeypatch.setattr(controller, "handle", observe_event)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        for event in [GatekeeperOnline(), ReaderReady(0)]:
            queue.put_nowait(event)
        if not hardware_mode:
            queue.put_nowait(CardRead(1, "0001ABCD", "000000001"))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=hardware_mode,
                uid_reader=object(),
                student_reader=object(),
                on_state_change=observe,
                send_tap=tap,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            queue.put_nowait(interruption)
            await asyncio.wait_for(rested.wait(), 1)
            # No hold: the reader rearms while the old request is still in flight.
            if hardware_mode and resting_state == KioskState.IDLE:
                await asyncio.wait_for(rearmed.wait(), 1)
            release_reply.set()
            await asyncio.wait_for(late_reply_handled.wait(), 1)
            await asyncio.sleep(0)
            assert KioskState.RESULT not in states
            assert states[-1] == resting_state
            assert rearmed.is_set() == (hardware_mode and resting_state == KioskState.IDLE)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())
