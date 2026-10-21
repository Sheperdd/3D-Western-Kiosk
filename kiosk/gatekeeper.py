"""HTTP client for the gatekeeper: taps and health (docs/kiosk-api.md)."""

import asyncio
import json
import logging

import aiohttp

from kiosk.events import (
    Event,
    FailureKind,
    GatekeeperError,
    GatekeeperOffline,
    GatekeeperOnline,
    GatekeeperResult,
    Result,
    Tap,
)

# Local-only results must never be accepted off the wire.
WIRE_RESULTS = frozenset(
    {Result.CHECKED_IN, Result.CHECKED_OUT, Result.DENIED, Result.IGNORED_DUPLICATE}
)


async def send_tap(session: aiohttp.ClientSession, tap: Tap) -> GatekeeperResult | GatekeeperError:
    """POST one tap. The session carries base_url, the X-Device-Key header and the timeout."""
    body = {"uid": tap.uid, "studentNumber": int(tap.student_number)}
    for _attempt in range(2):  # Contract rule 2: one immediate retry, inside the 3 s debounce.
        try:
            async with session.post("/v1/kiosk/tap", json=body) as resp:
                status = resp.status
                text = await resp.text()
            break
        except (aiohttp.ClientError, TimeoutError):
            continue
    else:
        return GatekeeperError(tap.tap_id)

    if status == 401:
        logging.error("Gatekeeper rejected the kiosk key (401); check GK_KIOSK_KEY.")
        return GatekeeperError(tap.tap_id, FailureKind.BAD_KEY)
    if status == 422:
        logging.error("Gatekeeper rejected the tap body (422): %s", text)
        return GatekeeperError(tap.tap_id, FailureKind.BAD_REQUEST)
    if status != 200:
        logging.error("Gatekeeper answered %s: %s", status, text)
        return GatekeeperError(tap.tap_id)

    reply = json.loads(text)
    raw = reply.get("result")
    return GatekeeperResult(
        tap.tap_id,
        Result(raw) if raw in WIRE_RESULTS else Result.DENIED,  # Never show success on unknown.
        reply.get("reason"),
        reply.get("message"),
        tuple(reply.get("notices") or ()),
        (reply.get("student") or {}).get("firstName"),
    )


HEALTH_INTERVAL_SECONDS = 5.0


async def gatekeeper_up(session: aiohttp.ClientSession) -> bool:
    """GET /healthz. Without a snapshot every tap would be UNKNOWN_STUDENT, so that is down too."""
    try:
        async with session.get("/healthz") as resp:
            if resp.status != 200:
                return False
            health = json.loads(await resp.text())
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return False
    return (
        isinstance(health, dict) and health.get("ok") is True and health.get("hasSnapshot") is True
    )


async def watch_health(session: aiohttp.ClientSession, queue: asyncio.Queue[Event]) -> None:
    """Poll forever; queue GatekeeperOnline/Offline only when the answer changes."""
    online: bool | None = None
    while True:
        up = await gatekeeper_up(session)
        if up != online:
            online = up
            logging.warning("Gatekeeper %s.", "online" if up else "offline")
            await queue.put(GatekeeperOnline() if up else GatekeeperOffline())
        await asyncio.sleep(HEALTH_INTERVAL_SECONDS)
