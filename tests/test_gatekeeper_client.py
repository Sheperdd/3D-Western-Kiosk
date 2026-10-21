"""The gatekeeper client against a fake gatekeeper: a real aiohttp server on a random port."""

import asyncio
import socket
from collections.abc import Awaitable, Callable

import pytest
from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.test_utils import TestServer

from kiosk import gatekeeper
from kiosk.events import (
    FailureKind,
    GatekeeperError,
    GatekeeperOffline,
    GatekeeperOnline,
    GatekeeperResult,
    Result,
    Tap,
)
from kiosk.gatekeeper import gatekeeper_up, send_tap, watch_health

# Test-stack student Sam (docs/kiosk-api.md); synthetic, not a real person.
TAP = Tap(7, "04A1B2C3D4E501", "251900001")
KEY = "test-kiosk-key"
CLIENT_TIMEOUT = 0.2  # Short so timeout tests stay fast; production uses 2 s.
HEALTHY = {"ok": True, "version": "0.1.0", "hasSnapshot": True, "journalPending": 0}

type Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def serve[T](path: str, handler: Handler, use: Callable[[ClientSession], Awaitable[T]]) -> T:
    app = web.Application()
    app.router.add_route("*", path, handler)
    async with (
        TestServer(app) as server,
        ClientSession(
            base_url=server.make_url("/"),
            headers={"X-Device-Key": KEY},
            timeout=ClientTimeout(total=CLIENT_TIMEOUT),
        ) as session,
    ):
        return await use(session)


def tap_against(handler: Handler) -> GatekeeperResult | GatekeeperError:
    return asyncio.run(serve("/v1/kiosk/tap", handler, lambda session: send_tap(session, TAP)))


def reply(result: str, **fields) -> dict:
    # Shape of a real gatekeeper reply, including fields the kiosk ignores.
    return {
        "v": 1,
        "result": result,
        "reason": None,
        "message": "Welcome, Sam.",
        "student": {"studentNumber": 251900001, "firstName": "Sam", "lastName": "Tester"},
        "orientation": {"status": "ACTIVE", "allowedUntil": None, "message": None},
        "certifications": [],
        "notices": [],
        "cardLinked": True,
        "visitId": "0c8fe347-425f-4ae1-aaea-3ffc92cd9b58",
        "serverTime": "2026-10-21T18:44:22.803Z",
        "someFutureField": {"ignored": True},
        **fields,
    }


def test_request_sends_uid_integer_student_number_and_key() -> None:
    seen: list[tuple[dict, str | None]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append((await request.json(), request.headers.get("X-Device-Key")))
        return web.json_response(reply("CHECKED_IN"))

    tap_against(handler)
    assert seen == [({"uid": "04A1B2C3D4E501", "studentNumber": 251900001}, KEY)]
    assert type(seen[0][0]["studentNumber"]) is int  # "251900001" would get a 422.


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (Result.CHECKED_IN, None),
        (Result.CHECKED_OUT, None),
        (Result.DENIED, "ORIENTATION_REQUIRED"),
        (Result.IGNORED_DUPLICATE, None),
    ],
)
def test_wire_result_is_returned_as_given(result: Result, reason: str | None) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(
            reply(result.value, reason=reason, notices=["Laser Cutter: refresher due."])
        )

    assert tap_against(handler) == GatekeeperResult(
        7, result, reason, "Welcome, Sam.", ("Laser Cutter: refresher due.",), "Sam"
    )


def test_unknown_student_has_no_name() -> None:
    async def handler(request: web.Request) -> web.Response:
        message = "We can't find your account yet. Sign up on the website first."
        return web.json_response(
            reply("DENIED", reason="UNKNOWN_STUDENT", message=message, student=None)
        )

    event = tap_against(handler)
    assert isinstance(event, GatekeeperResult)
    assert (event.result, event.reason, event.first_name, event.notices) == (
        Result.DENIED,
        "UNKNOWN_STUDENT",
        None,
        (),
    )


# Local-only results must never be accepted off the wire; unknown results never show success.
@pytest.mark.parametrize("raw", ["SOMETHING_NEW", "READ_AGAIN", "UNREACHABLE", "NOT_SET_UP"])
def test_unrecognised_result_is_shown_as_denied(raw: str) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(reply(raw, message="Please see staff."))

    event = tap_against(handler)
    assert isinstance(event, GatekeeperResult)
    assert (event.result, event.message) == (Result.DENIED, "Please see staff.")


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, FailureKind.BAD_KEY),
        (422, FailureKind.BAD_REQUEST),
        (404, FailureKind.UNREACHABLE),
        (500, FailureKind.UNREACHABLE),
    ],
)
def test_error_status_maps_to_failure_without_retry(status: int, kind: FailureKind) -> None:
    calls = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        return web.json_response({"v": 1, "error": "SOMETHING"}, status=status)

    assert tap_against(handler) == GatekeeperError(7, kind)
    assert calls == 1  # A reply is an answer; resending cannot change it.


def test_timeout_then_reply_retries_once_with_the_same_tap() -> None:
    bodies: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        bodies.append(await request.json())
        if len(bodies) == 1:
            await asyncio.sleep(CLIENT_TIMEOUT * 5)
        return web.json_response(reply("IGNORED_DUPLICATE"))

    event = tap_against(handler)
    assert isinstance(event, GatekeeperResult)
    assert event.result == Result.IGNORED_DUPLICATE
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


def test_two_timeouts_are_unreachable() -> None:
    calls = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(CLIENT_TIMEOUT * 5)
        return web.json_response(reply("CHECKED_IN"))

    assert tap_against(handler) == GatekeeperError(7, FailureKind.UNREACHABLE)
    assert calls == 2  # Never a third: a late retry could toggle the student back out.


@pytest.mark.parametrize(
    ("use", "down"),
    [
        (lambda session: send_tap(session, TAP), GatekeeperError(7, FailureKind.UNREACHABLE)),
        (gatekeeper_up, False),
    ],
    ids=["tap", "health"],
)
def test_nothing_listening_is_unreachable(use, down) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # Free once the socket closes.

    async def check():
        async with ClientSession(
            base_url=f"http://127.0.0.1:{port}",
            timeout=ClientTimeout(total=CLIENT_TIMEOUT),
        ) as session:
            return await use(session)

    assert asyncio.run(check()) == down


@pytest.mark.parametrize(
    ("status", "body", "up"),
    [
        (200, HEALTHY, True),
        (200, {**HEALTHY, "hasSnapshot": False}, False),  # Never synced: every tap would deny.
        (200, {**HEALTHY, "ok": False}, False),
        (200, {**HEALTHY, "ok": "yes"}, False),
        (200, [HEALTHY], False),
        (503, HEALTHY, False),
    ],
)
def test_gatekeeper_up_needs_ok_and_a_snapshot(status: int, body, up: bool) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(body, status=status)

    assert asyncio.run(serve("/healthz", handler, gatekeeper_up)) is up


@pytest.mark.parametrize("failure", ["garbled", "slow"])
def test_gatekeeper_up_is_false_on_a_bad_or_late_reply(failure: str) -> None:
    async def handler(request: web.Request) -> web.Response:
        if failure == "slow":
            await asyncio.sleep(CLIENT_TIMEOUT * 5)
            return web.json_response(HEALTHY)
        return web.Response(text="<html>proxy error</html>")

    assert asyncio.run(serve("/healthz", handler, gatekeeper_up)) is False


def test_health_watch_queues_only_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gatekeeper, "HEALTH_INTERVAL_SECONDS", 0)
    answers = [False, False, True, True, False, True]  # Then healthy for every later poll.
    polls = 0
    settled = asyncio.Event()

    async def handler(request: web.Request) -> web.Response:
        nonlocal polls
        up = answers[polls] if polls < len(answers) else True
        polls += 1
        if polls == len(answers) + 3:
            settled.set()
        return web.json_response({**HEALTHY, "hasSnapshot": up})

    async def use(session: ClientSession) -> list:
        queue = asyncio.Queue()
        watcher = asyncio.create_task(watch_health(session, queue))
        await asyncio.wait_for(settled.wait(), 1)
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        return [queue.get_nowait() for _ in range(queue.qsize())]

    # The first poll always reports, so the controller learns the starting state.
    assert asyncio.run(serve("/healthz", handler, use)) == [
        GatekeeperOffline(),
        GatekeeperOnline(),
        GatekeeperOffline(),
        GatekeeperOnline(),
    ]
