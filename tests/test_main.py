import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from kiosk import __main__ as entrypoint
from kiosk.display import DISPLAY_DATA
from kiosk.events import (
    BackendOnline,
    CardRead,
    KioskState,
    Outcome,
    ReaderReady,
)


def test_display_callback_updates_shared_payloads(monkeypatch) -> None:
    runner = Mock(setup=AsyncMock(), cleanup=AsyncMock())
    runner_factory = Mock(return_value=runner)
    monkeypatch.setattr(entrypoint.web, "AppRunner", runner_factory)
    monkeypatch.setattr(entrypoint.web, "TCPSite", Mock(return_value=Mock(start=AsyncMock())))

    async def run(queue, *, on_state_change):
        app = runner_factory.call_args.args[0]
        display_data = app[DISPLAY_DATA]
        for state, expected_status in (
            (KioskState.IDLE, "WAITING"),
            (KioskState.OFFLINE, "UNAVAILABLE"),
            (KioskState.READER_ERROR, "UNAVAILABLE"),
            (KioskState.OUTCOME_UNKNOWN, "UNAVAILABLE"),
            (KioskState.ACTIVATING, "IN USE"),
            (KioskState.AWAITING_IDENTITY, "IN USE"),
            (KioskState.REGISTERING, "IN USE"),
            (KioskState.RESULT, "IN USE"),
        ):
            on_state_change(state, Outcome.ACTIVATED, state == KioskState.IDLE)
            assert app[DISPLAY_DATA] is display_data
            assert display_data[1] == {"state": state.name, "outcome": "ACTIVATED"}
            assert display_data[2] == {"status": expected_status}

        on_state_change(KioskState.IDLE, None, False)
        assert display_data[1] == {"state": "REARMING", "outcome": None}
        assert display_data[2] == {"status": "IN USE"}
        on_state_change(KioskState.IDLE, None, True)
        assert display_data[1] == {"state": "IDLE", "outcome": None}
        assert display_data[2] == {"status": "WAITING"}

    monkeypatch.setattr(entrypoint, "run", run)
    asyncio.run(entrypoint.main())
    runner.cleanup.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
def test_demo_waits_ten_seconds_before_scan_and_cancels_timer(monkeypatch, cancelled) -> None:
    runner = Mock(setup=AsyncMock(), cleanup=AsyncMock())
    monkeypatch.setattr(entrypoint.web, "AppRunner", Mock(return_value=runner))
    monkeypatch.setattr(entrypoint.web, "TCPSite", Mock(return_value=Mock(start=AsyncMock())))
    timer = Mock()
    schedule = Mock(return_value=timer)

    async def run(queue, *, on_state_change):
        assert queue.get_nowait() == BackendOnline()
        assert queue.get_nowait() == ReaderReady(0)
        assert queue.empty()
        on_state_change(KioskState.IDLE, None, True)
        schedule.assert_called_once()
        delay, scan = schedule.call_args.args
        assert delay == 10.0
        if cancelled:
            raise asyncio.CancelledError
        scan()
        assert queue.get_nowait() == CardRead(1, "1234567890", "000123456")
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
    timer.cancel.assert_called_once_with()
    runner.cleanup.assert_awaited_once()
