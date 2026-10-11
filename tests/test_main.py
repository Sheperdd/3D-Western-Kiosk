import asyncio
from unittest.mock import AsyncMock, Mock

from kiosk import __main__ as entrypoint
from kiosk.display import DISPLAY_DATA
from kiosk.events import KioskState, Outcome


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
            on_state_change(state, Outcome.ACTIVATED)
            assert app[DISPLAY_DATA] is display_data
            assert display_data[1] == {"screen": state.name, "labels": ["ACTIVATED"]}
            assert display_data[2] == {
                "screen": "GENERAL INSTRUCTIONS",
                "labels": [expected_status, "Makerspace guidance placeholder."],
            }

        on_state_change(KioskState.IDLE, None)
        assert display_data[1] == {"screen": "IDLE", "labels": []}

    monkeypatch.setattr(entrypoint, "run", run)
    asyncio.run(entrypoint.main())
    runner.cleanup.assert_awaited_once()
