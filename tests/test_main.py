import asyncio
from functools import partial
from unittest.mock import AsyncMock, Mock

import pytest

from kiosk import __main__ as entrypoint
from kiosk.display import DISPLAY_DATA
from kiosk.events import (
    CardRead,
    GatekeeperOnline,
    KioskState,
    ReaderReady,
    Result,
)
from kiosk.machine import Context


@pytest.fixture(autouse=True)
def no_gatekeeper_config(monkeypatch) -> None:
    # Demo mode unless a test opts in; a developer's own GK_* must not leak into tests.
    monkeypatch.delenv("GK_URL", raising=False)
    monkeypatch.delenv("GK_KIOSK_KEY", raising=False)


def test_display_callback_updates_shared_payloads(monkeypatch) -> None:
    runner = Mock(setup=AsyncMock(), cleanup=AsyncMock())
    runner_factory = Mock(return_value=runner)
    monkeypatch.setattr(entrypoint.web, "AppRunner", runner_factory)
    monkeypatch.setattr(entrypoint.web, "TCPSite", Mock(return_value=Mock(start=AsyncMock())))

    shown = Context(
        result=Result.DENIED,
        reason="UNKNOWN_STUDENT",
        message="Sign up first.",
        notices=("Refresher due.",),
        first_name="Sam",
    )
    cleared = {"result": None, "reason": None, "message": None, "notices": []}

    async def run(queue, *, on_state_change, send_tap):
        app = runner_factory.call_args.args[0]
        display_data = app[DISPLAY_DATA]
        # app.js rejects a payload missing any field, so the startup one must match too.
        assert display_data[1] == {"state": "STARTING", **cleared}
        for state, expected_status in (
            (KioskState.IDLE, "WAITING"),
            (KioskState.OFFLINE, "UNAVAILABLE"),
            (KioskState.READER_ERROR, "UNAVAILABLE"),
            (KioskState.CHECKING, "IN USE"),
            (KioskState.RESULT, "IN USE"),
        ):
            on_state_change(state, shown, state == KioskState.IDLE)
            assert app[DISPLAY_DATA] is display_data
            assert display_data[1] == {
                "state": state.name,
                "result": "DENIED",
                "reason": "UNKNOWN_STUDENT",
                "message": "Sign up first.",
                "notices": ["Refresher due."],
                "demo": True,  # No GK_URL: the fake gatekeeper.
            }  # No name, student number or UID.
            assert display_data[2] == {"status": expected_status, "demo": True}

        on_state_change(KioskState.IDLE, Context(), False)
        assert display_data[1] == {"state": "REARMING", **cleared, "demo": True}
        assert display_data[2] == {"status": "IN USE", "demo": True}
        on_state_change(KioskState.IDLE, Context(), True)
        assert display_data[1] == {"state": "IDLE", **cleared, "demo": True}
        assert display_data[2] == {"status": "WAITING", "demo": True}

    monkeypatch.setattr(entrypoint, "run", run)
    asyncio.run(entrypoint.main())
    runner.cleanup.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
def test_demo_checks_in_then_out_and_cancels_timers(monkeypatch, cancelled) -> None:
    runner = Mock(setup=AsyncMock(), cleanup=AsyncMock())
    monkeypatch.setattr(entrypoint.web, "AppRunner", Mock(return_value=runner))
    monkeypatch.setattr(entrypoint.web, "TCPSite", Mock(return_value=Mock(start=AsyncMock())))
    timer = Mock()
    schedule = Mock(return_value=timer)

    async def run(queue, *, on_state_change, send_tap):
        assert send_tap is entrypoint.fake_tap  # No GK_URL: the demo gatekeeper.
        assert queue.get_nowait() == GatekeeperOnline()
        assert queue.get_nowait() == ReaderReady(0)
        assert queue.empty()
        on_state_change(KioskState.IDLE, Context(), True)
        (check_in_delay, check_in), (check_out_delay, check_out) = (
            call.args for call in schedule.call_args_list
        )
        assert (check_in_delay, check_out_delay) == (10.0, 30.0)
        if cancelled:
            raise asyncio.CancelledError
        check_in()
        assert queue.get_nowait() == CardRead(1, "04A1B2C3D4E501", "251900001")
        check_out()
        assert queue.get_nowait() == CardRead(2, "04A1B2C3D4E501", "251900001")
        assert queue.empty()

    async def check():
        monkeypatch.setattr(asyncio.get_running_loop(), "call_later", schedule)
        monkeypatch.setattr(entrypoint, "run", run)
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await entrypoint.main()
        else:
            await entrypoint.main()

    asyncio.run(check())
    assert timer.cancel.call_count == 2
    runner.cleanup.assert_awaited_once()


def test_gatekeeper_url_selects_the_real_client(monkeypatch) -> None:
    runner = Mock(setup=AsyncMock(), cleanup=AsyncMock())
    runner_factory = Mock(return_value=runner)
    monkeypatch.setattr(entrypoint.web, "AppRunner", runner_factory)
    monkeypatch.setattr(entrypoint.web, "TCPSite", Mock(return_value=Mock(start=AsyncMock())))
    monkeypatch.setenv("GK_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("GK_KIOSK_KEY", "test-key")
    senders = []
    watched = []

    async def watch_health(session, queue):
        watched.append(session)
        await asyncio.Event().wait()  # Runs until main() cancels it.

    async def run(queue, *, on_state_change, send_tap):
        await asyncio.sleep(0)  # Let the watcher start.
        senders.append(send_tap)
        # Health polling owns online/offline; only reader readiness is queued up front.
        assert queue.get_nowait() == ReaderReady(0)
        assert queue.empty()
        # Real gatekeeper: neither display may claim "no real access changes".
        on_state_change(KioskState.IDLE, Context(), True)
        display_data = runner_factory.call_args.args[0][DISPLAY_DATA]
        assert display_data[1]["demo"] is False
        assert display_data[2]["demo"] is False

    monkeypatch.setattr(entrypoint, "watch_health", watch_health)
    monkeypatch.setattr(entrypoint, "run", run)
    asyncio.run(entrypoint.main())
    [sender] = senders
    assert isinstance(sender, partial) and sender.func is entrypoint.send_tap
    session = sender.args[0]
    assert watched == [session]
    assert session.closed
    assert session.headers["X-Device-Key"] == "test-key"
    assert session.timeout.total == 2


@pytest.mark.parametrize("missing", ["GK_URL", "GK_KIOSK_KEY"])
def test_hardware_mode_fails_fast_without_gatekeeper_config(monkeypatch, missing) -> None:
    monkeypatch.setenv("GK_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("GK_KIOSK_KEY", "test-key")
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit, match="GK_URL and GK_KIOSK_KEY"):
        asyncio.run(entrypoint.main(device="/dev/input/event4"))
