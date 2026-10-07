import asyncio
from types import SimpleNamespace

import pytest

from kiosk import controller, readers
from kiosk.controller import fake_register_and_activate
from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOffline,
    BackendOnline,
    BackendOp,
    BackendResult,
    CancelSession,
    CancelTimeout,
    CardRead,
    Event,
    FailureKind,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderFault,
    ReaderReady,
    RegisterAndActivate,
    StartTimeout,
    Timeout,
    TimeoutName,
)
from kiosk.machine import Context


@pytest.mark.parametrize("number", ["000123456", None, OSError("Reader disconnected")])
def test_backend_waits_until_student_number_is_collected(
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
            if isinstance(event, (BackendResult, ReaderFault)) or result[0] == KioskState.RESULT:
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

        async def activate(queue, effect, seconds, desired_outcome):
            backend_calls.append(effect)
            queue.put_nowait(
                BackendResult(effect.session_id, BackendOp.ACTIVATE_UID, desired_outcome)
            )

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(readers, "read_uid_async", read_uid)
        monkeypatch.setattr(readers, "read_student_number_async", read_number)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=object(),
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            await asyncio.wait_for(reading_number.wait(), 1)
            assert backend_calls == [], "UID alone started backend processing"
            assert not any(isinstance(event, CardRead) for event in events)
            release_number.set()
            await asyncio.wait_for(terminal.wait(), 1)
            completed = [event for event in events if isinstance(event, CardRead)]
            if isinstance(number, str):
                assert completed == [CardRead(1, "0001ABCD", number)]
                assert backend_calls == [ActivateUid(1, "0001ABCD")]
            else:
                assert completed == backend_calls == []
            assert not any(isinstance(event, IdentityConfirmed) for event in events)
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


def test_unregistered_hardware_session_expires_without_confirming_raw_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[tuple[KioskState, Context]] = asyncio.Queue()
        events = []
        number_received = asyncio.Event()
        timer_blocker = asyncio.Event()
        original_handle = controller.handle
        original_activate = controller.fake_activate_uid

        def observe(state, context, event):
            events.append(event)
            result = original_handle(state, context, event)
            observed.put_nowait((result[0], result[1]))
            return result

        async def read_uid(uid_reader):
            return "0001ABCD"

        async def read_student_number(student_reader, *, timeout):
            number_received.set()
            return "000123456"

        async def activate(queue, effect, seconds, desired_outcome):
            await number_received.wait()
            await original_activate(queue, effect, 0, Outcome.UNREGISTERED)

        async def timer(queue, effect, seconds):
            await timer_blocker.wait()

        async def reach(target):
            while True:
                state, context = await observed.get()
                if state == target:
                    return context

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(readers, "read_uid_async", read_uid)
        monkeypatch.setattr(readers, "read_student_number_async", read_student_number)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=object(),
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            context = await asyncio.wait_for(reach(KioskState.AWAITING_IDENTITY), 1)
            assert context.observed_student_number == "000123456"
            assert context.student_number is None
            queue.put_nowait(Timeout(1, TimeoutName.SESSION))
            context = await asyncio.wait_for(reach(KioskState.RESULT), 1)
            assert context.outcome == Outcome.SESSION_EXPIRED
            assert not any(isinstance(event, IdentityConfirmed) for event in events)
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

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
        monkeypatch.setattr(controller, "DEMO_BACKEND_DELAY", 0)
        monkeypatch.setitem(controller.DEMO_TIMEOUT_SECONDS, TimeoutName.RESULT, 0)
        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=True,
                uid_reader=reader,
                student_reader=SimpleNamespace(read_one=lambda: None),
            )
        )
        try:
            queue.put_nowait(BackendOnline())
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
                assert context.session_id == 0
                queue.put_nowait(ReaderReady(0))
            else:
                assert event == CardRead(1, "0001ABCD", "000000001")
                assert state == KioskState.ACTIVATING
                event, state, context = await asyncio.wait_for(observed.get(), 1)
                assert event == BackendResult(1, BackendOp.ACTIVATE_UID, Outcome.ACTIVATED)
                assert state == KioskState.RESULT
                assert context.outcome == Outcome.ACTIVATED

            _, state, _ = await asyncio.wait_for(observed.get(), 1)
            assert state == KioskState.IDLE
            queue.put_nowait(BackendOnline())
            event, _, _ = await asyncio.wait_for(observed.get(), 1)
            assert event == BackendOnline()
            await asyncio.wait_for(rearmed.wait(), 1)
            assert calls == [reader] * (2 if reader_fails else 3)
            assert observed.empty()
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())
    output = capsys.readouterr().out
    assert output.count("UID received: 0001ABCD") == (0 if reader_fails else 1)


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
            queue.put_nowait(BackendOffline())
            queue.put_nowait(BackendOnline())
            return pair

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        queue.put_nowait(BackendOnline())
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
            for expected in [BackendOnline(), ReaderReady(0), BackendOffline(), BackendOnline()]:
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
    [None, BackendOffline(), ReaderFault(0, "Reader disconnected"), CancelSession(0)],
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
        queue.put_nowait(BackendOnline())
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
            if interruption is not None:
                queue.put_nowait(BackendOnline())
                queue.put_nowait(ReaderReady(0))
                await asyncio.wait_for(recovered.wait(), 1)
                assert calls == [reader]
                runner.cancel()
            await asyncio.sleep(0)
            assert not runner.done()
            assert not cleanup_finished.is_set()
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
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
@pytest.mark.parametrize("outcome", [Outcome.ACTIVATED, Outcome.DENIED])
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

        async def activate(queue, effect, seconds, desired_outcome):
            calls.append(effect)
            queue.put_nowait(BackendResult(effect.session_id, BackendOp.ACTIVATE_UID, outcome))

        async def timer(queue, effect, seconds):
            if effect.name == TimeoutName.SESSION:
                await blocker.wait()
            else:
                gate = asyncio.Event()
                result_timers.put_nowait(gate)
                await gate.wait()
                queue.put_nowait(Timeout(effect.session_id, effect.name))

        async def reach_result():
            while True:
                event, state, context = await observed.get()
                assert not isinstance(event, IdentityConfirmed)
                if state == KioskState.RESULT:
                    return context

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(queue, hardware_mode=True, uid_reader=object(), student_reader=object())
        )
        try:
            first = await asyncio.wait_for(reach_result(), 1)
            first_timer = await asyncio.wait_for(result_timers.get(), 1)
            assert first.outcome == (Outcome.READ_AGAIN if first_pair is None else outcome)
            assert reads == 1
            assert not second_started.is_set()
            assert len(calls) == int(first_pair is not None)
            first_timer.set()
            await asyncio.wait_for(second_started.wait(), 1)
            assert len(calls) == int(first_pair is not None)  # Waiting for the new pair.
            release_second.set()
            second = await asyncio.wait_for(reach_result(), 1)
            assert second.session_id == first.session_id + 1
            assert second.outcome == outcome
            assert calls[-1] == ActivateUid(second.session_id, second_uid)
            assert len(calls) == 1 + int(first_pair is not None)
            assert reads == 2
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    "interruption", [BackendOffline(), ReaderFault(0, "disconnected"), CancelSession(0)]
)
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
        reads = 0
        original_handle = controller.handle

        def observe(state, context, event):
            events.append(event)
            result = original_handle(state, context, event)
            if cleanup_started.is_set() and result[0] == KioskState.IDLE:
                recovered.set()
            return result

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
        queue.put_nowait(BackendOnline())
        queue.put_nowait(ReaderReady(0))
        runner = asyncio.create_task(
            controller.run(queue, hardware_mode=True, uid_reader=object(), student_reader=object())
        )
        try:
            await asyncio.wait_for(first_started.wait(), 1)
            queue.put_nowait(interruption)
            await asyncio.wait_for(cleanup_started.wait(), 1)
            queue.put_nowait(BackendOnline())
            queue.put_nowait(ReaderReady(0))
            await asyncio.wait_for(recovered.wait(), 1)
            assert reads == 1
            assert not second_started.is_set()
            release_cleanup.set()  # No further event is needed to wake the controller.
            await asyncio.wait_for(second_started.wait(), 1)
            assert reads == 2
            assert not any(isinstance(event, (CardRead, BackendResult)) for event in events)
        finally:
            release_cleanup.set()
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            None,
            BackendResult(7, BackendOp.REGISTER_AND_ACTIVATE, Outcome.REGISTERED_AND_ACTIVE),
        ),
        (
            FailureKind.NOT_SENT,
            BackendError(7, BackendOp.REGISTER_AND_ACTIVATE, FailureKind.NOT_SENT),
        ),
        (
            FailureKind.UNKNOWN,
            BackendError(7, BackendOp.REGISTER_AND_ACTIVATE, FailureKind.UNKNOWN),
        ),
    ],
    ids=["success", "not-sent", "unknown"],
)
def test_fake_registration_emits_exactly_one_response(
    failure: FailureKind | None, expected: BackendResult | BackendError
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        effect = RegisterAndActivate(7, "0001ABCD", "000000001")

        await fake_register_and_activate(queue, effect, seconds=0, failure=failure)

        assert queue.get_nowait() == expected
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome.ACTIVATED,
        Outcome.ALREADY_ACTIVE,
        Outcome.UNREGISTERED,
        Outcome.UNKNOWN_STUDENT,
        Outcome.MISSING_INDUCTION,
        Outcome.DENIED,
        Outcome.UID_CONFLICT,
    ],
)
def test_fake_activation_preserves_operation_and_outcome(outcome: Outcome) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        await controller.fake_activate_uid(queue, ActivateUid(9, "0001ABCD"), 0, outcome)
        assert queue.get_nowait() == BackendResult(9, BackendOp.ACTIVATE_UID, outcome)
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize("operation", list(BackendOp))
@pytest.mark.parametrize("failure_point", ["delay", "response"])
def test_backend_exception_emits_matching_unknown_error(
    monkeypatch: pytest.MonkeyPatch, operation: BackendOp, failure_point: str
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def fail_delay(seconds):
            raise RuntimeError("Injected backend failure")

        original_put = queue.put
        first_response = True

        async def fail_first_response(event):
            nonlocal first_response
            if first_response:
                first_response = False
                raise RuntimeError("Injected response failure")
            await original_put(event)

        # Exercise both the simulated wait and the existing exception-handler body.
        if failure_point == "delay":
            monkeypatch.setattr(controller.asyncio, "sleep", fail_delay)
        else:
            monkeypatch.setattr(queue, "put", fail_first_response)

        if operation == BackendOp.ACTIVATE_UID:
            await controller.fake_activate_uid(queue, ActivateUid(12, "0001ABCD"), 0)
        else:
            await controller.fake_register_and_activate(
                queue, RegisterAndActivate(12, "0001ABCD", "000000001"), 0
            )

        assert queue.get_nowait() == BackendError(12, operation, FailureKind.UNKNOWN)
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize("operation", list(BackendOp))
def test_backend_cancellation_propagates_without_error_event(
    monkeypatch: pytest.MonkeyPatch, operation: BackendOp
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def cancelled_response(event):
            raise asyncio.CancelledError

        monkeypatch.setattr(queue, "put", cancelled_response)
        with pytest.raises(asyncio.CancelledError):
            if operation == BackendOp.ACTIVATE_UID:
                await controller.fake_activate_uid(queue, ActivateUid(12, "0001ABCD"), 0)
            else:
                await controller.fake_register_and_activate(
                    queue, RegisterAndActivate(12, "0001ABCD", "000000001"), 0
                )
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
    ("name", "expected_seconds"),
    [(TimeoutName.SESSION, 13.0), (TimeoutName.RESULT, 3.0)],
)
def test_timer_dispatch_uses_configured_duration(
    monkeypatch: pytest.MonkeyPatch, name: TimeoutName, expected_seconds: float
) -> None:
    async def check() -> None:
        monkeypatch.setattr(
            controller,
            "DEMO_TIMEOUT_SECONDS",
            {TimeoutName.SESSION: 13.0, TimeoutName.RESULT: 3.0},
        )
        durations: list[float] = []

        async def record_delay(seconds: float) -> None:
            durations.append(seconds)

        monkeypatch.setattr(controller.asyncio, "sleep", record_delay)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        controller.dispatch(queue, StartTimeout(8, name), {}, tasks)
        await asyncio.gather(*tasks)
        assert durations == [expected_seconds]
        assert queue.get_nowait() == Timeout(8, name)
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize("replace", [False, True], ids=["cancel", "replace"])
def test_timer_dispatch_cancels_old_task(monkeypatch: pytest.MonkeyPatch, replace: bool) -> None:
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
        start = StartTimeout(1, TimeoutName.SESSION)
        key = (start.session_id, start.name)
        controller.dispatch(queue, start, timers, tasks)
        old_task = timers[key]
        await asyncio.sleep(0)  # Let the original timer start waiting.

        if replace:
            controller.dispatch(queue, start, timers, tasks)
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
        for name in TimeoutName:
            monkeypatch.setitem(controller.DEMO_TIMEOUT_SECONDS, name, 0)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        timers: dict[tuple[int, TimeoutName], asyncio.Task[None]] = {}
        tasks: set[asyncio.Task[None]] = set()
        keys = [(1, TimeoutName.SESSION), (1, TimeoutName.RESULT), (2, TimeoutName.SESSION)]
        for key in keys:
            controller.dispatch(queue, StartTimeout(*key), timers, tasks)
        scheduled = list(timers.values())
        controller.dispatch(queue, CancelTimeout(*keys[0]), timers, tasks)
        await asyncio.gather(*scheduled, return_exceptions=True)
        assert set(timers) == set(keys[1:])
        assert {queue.get_nowait(), queue.get_nowait()} == {Timeout(*key) for key in keys[1:]}
        assert queue.empty()

    asyncio.run(check())


@pytest.mark.parametrize(
    "effect", [ActivateUid(4, "0001ABCD"), RegisterAndActivate(4, "0001ABCD", "000000001")]
)
def test_backend_dispatch_tracks_and_releases_tasks(
    monkeypatch: pytest.MonkeyPatch, effect
) -> None:
    async def check() -> None:
        monkeypatch.setattr(controller, "DEMO_BACKEND_DELAY", 0)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        controller.dispatch(queue, effect, {}, tasks)
        assert len(tasks) == 1
        await asyncio.gather(*tasks)
        assert not tasks
        assert queue.qsize() == 1

    asyncio.run(check())


@pytest.mark.parametrize(
    ("activation", "identity", "failure", "expected_state", "expected_outcome"),
    [
        (Outcome.ACTIVATED, False, None, KioskState.RESULT, Outcome.ACTIVATED),
        (Outcome.DENIED, False, None, KioskState.RESULT, Outcome.DENIED),
        (Outcome.UNREGISTERED, True, None, KioskState.RESULT, Outcome.REGISTERED_AND_ACTIVE),
        (Outcome.UNREGISTERED, True, FailureKind.NOT_SENT, KioskState.OFFLINE, None),
        (Outcome.UNREGISTERED, True, FailureKind.UNKNOWN, KioskState.OUTCOME_UNKNOWN, None),
        (Outcome.UNREGISTERED, False, None, KioskState.RESULT, Outcome.SESSION_EXPIRED),
    ],
    ids=["activation", "denial", "registration", "not-sent", "unknown", "missing-identity"],
)
def test_controller_flow(
    monkeypatch: pytest.MonkeyPatch, activation, identity, failure, expected_state, expected_outcome
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        observed: asyncio.Queue[tuple[KioskState, Context]] = asyncio.Queue()
        session_expiry = asyncio.Event()
        result_expiry = asyncio.Event()
        original_handle = controller.handle
        original_activation = controller.fake_activate_uid
        registration_calls = []

        def observe(state, context, event):
            result = original_handle(state, context, event)
            observed.put_nowait((result[0], result[1]))
            return result

        async def activate(queue, effect, seconds, desired_outcome):
            await original_activation(queue, effect, 0, activation)

        async def register(queue, effect, seconds, failure=None):
            registration_calls.append(effect)
            await fake_register_and_activate(queue, effect, 0, selected_failure)

        async def timer(queue, effect, seconds):
            gate = session_expiry if effect.name == TimeoutName.SESSION else result_expiry
            await gate.wait()
            await queue.put(Timeout(effect.session_id, effect.name))

        async def reach(target):
            while True:
                state, context = await observed.get()
                if state == target:
                    return context

        selected_failure = failure
        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setattr(controller, "fake_register_and_activate", register)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        for event in [BackendOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(controller.run(queue))
        try:
            # Consume startup before looking for terminal states such as OFFLINE.
            await asyncio.wait_for(reach(KioskState.ACTIVATING), 1)
            if identity:
                queue.put_nowait(IdentityConfirmed(1, "0001ABCD", "000000001"))
            if activation == Outcome.UNREGISTERED and not identity:
                await asyncio.wait_for(reach(KioskState.AWAITING_IDENTITY), 1)
                session_expiry.set()
            context = await asyncio.wait_for(reach(expected_state), 1)
            assert context.outcome == expected_outcome
            assert len(registration_calls) == int(identity)
            if identity:
                assert registration_calls == [RegisterAndActivate(1, "0001ABCD", "000000001")]
            if expected_state == KioskState.RESULT:
                result_expiry.set()
                context = await asyncio.wait_for(reach(KioskState.IDLE), 1)
                assert context.outcome is None
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

        async def activate(queue, effect, seconds, desired_outcome):
            await wait_until_cancelled()

        monkeypatch.setattr(controller, "fire_timeout", timer)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        for event in [BackendOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(
            controller.run(
                queue,
                hardware_mode=hardware_mode,
                uid_reader=object(),
                student_reader=SimpleNamespace(read_one=lambda: None),
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
            hardware_mode: bool = False,
        ):
            nonlocal captured_timers, captured_tasks
            captured_timers = timers
            captured_tasks = background_tasks
            original_dispatch(
                queue,
                effect,
                timers,
                background_tasks,
                hardware_mode=hardware_mode,
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

        async def activate(queue, effect, seconds, desired_outcome):
            await blocker.wait()

        monkeypatch.setattr(controller, "dispatch", capture_dispatch)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        for event in [BackendOnline(), ReaderReady(0), CardRead(1, "0001ABCD", "000000001")]:
            queue.put_nowait(event)
        runner = asyncio.create_task(controller.run(queue))
        tracked: list[asyncio.Task[None]] = []
        try:
            await asyncio.wait_for(timer_started.wait(), 1)
            assert old_task is not None
            key = (1, TimeoutName.SESSION)
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


@pytest.mark.parametrize("hardware_mode", [False, True])
def test_late_backend_response_resolves_hold_without_showing_success(
    monkeypatch: pytest.MonkeyPatch,
    hardware_mode: bool,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        release_backend = asyncio.Event()
        holding = asyncio.Event()
        resolved = asyncio.Event()
        rearmed = asyncio.Event()
        blocker = asyncio.Event()
        reads = 0
        states: list[KioskState] = []
        original_handle = controller.handle
        original_activation = controller.fake_activate_uid

        def observe(state, context, event):
            result = original_handle(state, context, event)
            states.append(result[0])
            if result[0] == KioskState.OUTCOME_UNKNOWN:
                holding.set()
            if isinstance(event, BackendResult) and result[0] == KioskState.IDLE:
                resolved.set()
            return result

        async def activate(queue, effect, seconds, desired_outcome):
            await release_backend.wait()
            await original_activation(queue, effect, 0, Outcome.ACTIVATED)

        async def read_card(reader, student_reader, *, student_timeout):
            nonlocal reads
            reads += 1
            if reads == 1:
                return "0001ABCD", "000000001"
            rearmed.set()
            await blocker.wait()

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "read_card_async", read_card)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setitem(controller.DEMO_TIMEOUT_SECONDS, TimeoutName.SESSION, 0)
        for event in [BackendOnline(), ReaderReady(0)]:
            queue.put_nowait(event)
        if not hardware_mode:
            queue.put_nowait(CardRead(1, "0001ABCD", "000000001"))
        runner = asyncio.create_task(
            controller.run(
                queue, hardware_mode=hardware_mode, uid_reader=object(), student_reader=object()
            )
        )
        try:
            await asyncio.wait_for(holding.wait(), 1)
            assert not resolved.is_set()
            assert reads == int(hardware_mode)
            assert not rearmed.is_set()
            release_backend.set()
            await asyncio.wait_for(resolved.wait(), 1)
            assert KioskState.RESULT not in states
            assert states[-2:] == [KioskState.OUTCOME_UNKNOWN, KioskState.IDLE]
            if hardware_mode:
                await asyncio.wait_for(rearmed.wait(), 1)
                assert reads == 2
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())
