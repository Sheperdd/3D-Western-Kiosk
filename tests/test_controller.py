import asyncio

import pytest

from kiosk import controller
from kiosk.controller import fake_register_and_activate
from kiosk.events import (
    ActivateUid,
    BackendError,
    BackendOnline,
    BackendOp,
    BackendResult,
    CancelTimeout,
    CaptureIdentity,
    Event,
    FailureKind,
    IdentityConfirmed,
    KioskState,
    Outcome,
    ReaderFault,
    ReaderReady,
    RegisterAndActivate,
    StartTimeout,
    StopCapture,
    Timeout,
    TimeoutName,
    UidScan,
)
from kiosk.machine import Context


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


def test_capture_dispatch_emits_identity_and_releases_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        monkeypatch.setattr(controller, "DEMO_BACKEND_DELAY", 0)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        captures: dict[int, asyncio.Task[None]] = {}
        controller.dispatch(queue, CaptureIdentity(7, "0001ABCD"), {}, tasks, captures)
        task = captures[7]
        assert tasks == {task}
        await asyncio.wait_for(asyncio.gather(task), 1)
        assert queue.get_nowait() == IdentityConfirmed(7, "0001ABCD", "1234567890")
        assert queue.empty()
        assert not tasks
        controller.dispatch(queue, StopCapture(7), {}, tasks, captures)
        assert not captures

    asyncio.run(check())


@pytest.mark.parametrize("failure_point", ["delay", "response"])
def test_capture_exception_emits_reader_fault(
    monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        original_put = queue.put

        async def fail_delay(seconds):
            raise RuntimeError("Injected capture failure")

        async def fail_identity(event):
            if isinstance(event, IdentityConfirmed):
                raise RuntimeError("Injected capture failure")
            await original_put(event)

        if failure_point == "delay":
            monkeypatch.setattr(controller.asyncio, "sleep", fail_delay)
        else:
            monkeypatch.setattr(queue, "put", fail_identity)
        await controller.fake_capture_identity(queue, CaptureIdentity(7, "0001ABCD"), 0, "001")
        fault = queue.get_nowait()
        assert isinstance(fault, ReaderFault)
        assert fault.session_id == 7
        assert "Injected capture failure" in fault.reason
        assert queue.empty()

    asyncio.run(check())


def test_stop_capture_cancels_only_matching_capture_and_tracks_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        tasks: set[asyncio.Task[None]] = set()
        captures: dict[int, asyncio.Task[None]] = {}
        release = asyncio.Event()
        captures_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        started = 0

        async def controlled_delay(seconds):
            nonlocal started
            started += 1
            if started == 2:
                captures_started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release_cleanup.wait()
                raise

        async def activate(queue, effect, seconds, desired_outcome):
            await release.wait()
            await queue.put(
                BackendResult(effect.session_id, BackendOp.ACTIVATE_UID, desired_outcome)
            )

        # Gate the real capture coroutine's delay so cancellation exercises its exception handling.
        monkeypatch.setattr(controller.asyncio, "sleep", controlled_delay)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        controller.dispatch(queue, CaptureIdentity(7, "0001ABCD"), {}, tasks, captures)
        controller.dispatch(queue, CaptureIdentity(8, "0002ABCD"), {}, tasks, captures)
        controller.dispatch(queue, ActivateUid(7, "0001ABCD"), {}, tasks, captures)
        scheduled = list(tasks)
        stopped = captures[7]
        other = captures[8]
        backend = next(task for task in tasks if task not in captures.values())
        try:
            await asyncio.wait_for(captures_started.wait(), 1)
            controller.dispatch(queue, StopCapture(7), {}, tasks, captures)
            controller.dispatch(queue, StopCapture(7), {}, tasks, captures)
            controller.dispatch(queue, StopCapture(99), {}, tasks, captures)
            await asyncio.wait_for(cleanup_started.wait(), 1)
            assert captures == {8: other}
            assert stopped in tasks
            assert not stopped.done()
            assert other.cancelling() == backend.cancelling() == 0

            release_cleanup.set()
            release.set()
            await asyncio.wait_for(asyncio.gather(*scheduled, return_exceptions=True), 1)
            assert stopped.cancelled()
            assert not tasks
            assert {queue.get_nowait(), queue.get_nowait()} == {
                IdentityConfirmed(8, "0002ABCD", "1234567890"),
                BackendResult(7, BackendOp.ACTIVATE_UID, Outcome.UNREGISTERED),
            }
            assert queue.empty()  # No identity or ReaderFault for the cancelled capture.
        finally:
            release_cleanup.set()
            release.set()
            for task in scheduled:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*scheduled, return_exceptions=True)

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
        controller.dispatch(queue, StartTimeout(8, name), {}, tasks, {})
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
        captures: dict[int, asyncio.Task[None]] = {}
        release = asyncio.Event()

        async def controlled_timer(queue, effect, seconds):
            await release.wait()
            await controller_original_timer(queue, effect, 0)

        controller_original_timer = controller.fire_timeout
        monkeypatch.setattr(controller, "fire_timeout", controlled_timer)
        start = StartTimeout(1, TimeoutName.SESSION)
        key = (start.session_id, start.name)
        controller.dispatch(queue, start, timers, tasks, captures)
        old_task = timers[key]
        await asyncio.sleep(0)  # Let the original timer start waiting.

        if replace:
            controller.dispatch(queue, start, timers, tasks, captures)
            assert timers[key] is not old_task
        else:
            controller.dispatch(queue, CancelTimeout(*key), timers, tasks, captures)
            assert key not in timers

        release.set()
        await asyncio.gather(old_task, *timers.values(), return_exceptions=True)
        assert old_task.cancelled()
        if replace:
            assert queue.get_nowait() == Timeout(*key)
        assert queue.empty()

        # Repeated cancellation and cancellation of absent timers are harmless.
        controller.dispatch(queue, CancelTimeout(*key), timers, tasks, captures)
        controller.dispatch(queue, CancelTimeout(*key), timers, tasks, captures)
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
        captures: dict[int, asyncio.Task[None]] = {}
        for key in keys:
            controller.dispatch(queue, StartTimeout(*key), timers, tasks, captures)
        scheduled = list(timers.values())
        controller.dispatch(queue, CancelTimeout(*keys[0]), timers, tasks, captures)
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
        controller.dispatch(queue, effect, {}, tasks, {})
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
        original_capture = controller.fake_capture_identity
        missing_identity = asyncio.Event()
        registration_calls = []

        def observe(state, context, event):
            result = original_handle(state, context, event)
            observed.put_nowait((result[0], result[1]))
            return result

        async def activate(queue, effect, seconds, desired_outcome):
            await original_activation(queue, effect, 0, activation)

        async def capture(queue, effect, seconds, student_number):
            if not identity:
                await missing_identity.wait()
            await original_capture(queue, effect, 0, "000000001")

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
        monkeypatch.setattr(controller, "fake_capture_identity", capture)
        monkeypatch.setattr(controller, "fake_register_and_activate", register)
        monkeypatch.setattr(controller, "fire_timeout", timer)
        for event in [BackendOnline(), ReaderReady(0), UidScan(1, "0001ABCD")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(controller.run(queue))
        try:
            # Consume startup before looking for terminal states such as OFFLINE.
            await asyncio.wait_for(reach(KioskState.ACTIVATING), 1)
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


def test_shutdown_cancels_and_awaits_timer_backend_and_capture(
    monkeypatch: pytest.MonkeyPatch,
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
            if len(children) == 3:
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

        async def capture(queue, effect, seconds, student_number):
            await wait_until_cancelled()

        monkeypatch.setattr(controller, "fire_timeout", timer)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setattr(controller, "fake_capture_identity", capture)
        for event in [BackendOnline(), ReaderReady(0), UidScan(1, "0001ABCD")]:
            queue.put_nowait(event)

        runner = asyncio.create_task(controller.run(queue))
        try:
            await asyncio.wait_for(all_started.wait(), timeout=1)
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(runner, timeout=1)

            # Assert before test cleanup or asyncio.run() can finish leaked tasks.
            assert len(children) == 3
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
        captured_captures: dict[int, asyncio.Task[None]] = {}
        old_task: asyncio.Task[None] | None = None

        def capture_dispatch(queue, effect, timers, background_tasks, capture_tasks):
            nonlocal captured_timers, captured_tasks, captured_captures
            captured_timers = timers
            captured_tasks = background_tasks
            captured_captures = capture_tasks
            original_dispatch(queue, effect, timers, background_tasks, capture_tasks)

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
        for event in [BackendOnline(), ReaderReady(0), UidScan(1, "0001ABCD")]:
            queue.put_nowait(event)
        runner = asyncio.create_task(controller.run(queue))
        tracked: list[asyncio.Task[None]] = []
        try:
            await asyncio.wait_for(timer_started.wait(), 1)
            assert old_task is not None
            key = (1, TimeoutName.SESSION)
            effect = StartTimeout(*key) if replace else CancelTimeout(*key)
            original_dispatch(queue, effect, captured_timers, captured_tasks, captured_captures)
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


def test_late_backend_response_resolves_hold_without_showing_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        release_backend = asyncio.Event()
        holding = asyncio.Event()
        resolved = asyncio.Event()
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

        monkeypatch.setattr(controller, "handle", observe)
        monkeypatch.setattr(controller, "fake_activate_uid", activate)
        monkeypatch.setitem(controller.DEMO_TIMEOUT_SECONDS, TimeoutName.SESSION, 0)
        for event in [BackendOnline(), ReaderReady(0), UidScan(1, "0001ABCD")]:
            queue.put_nowait(event)
        runner = asyncio.create_task(controller.run(queue))
        try:
            await asyncio.wait_for(holding.wait(), 1)
            assert not resolved.is_set()
            release_backend.set()
            await asyncio.wait_for(resolved.wait(), 1)
            assert KioskState.RESULT not in states
            assert states[-2:] == [KioskState.OUTCOME_UNKNOWN, KioskState.IDLE]
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(check())
