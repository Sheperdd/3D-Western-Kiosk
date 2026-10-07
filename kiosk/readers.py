"""This module contains the hardware operations for the PN532 NFC reader, and the OMNIKEY 5427 CK
reader, which is a USB smart card reader. The PN532 is used to get the UID of the card, and the
OMNIKEY is used to read the student number from the card."""

import asyncio
import logging
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager

INTER_KEY_TIMEOUT = 2.0  # Seconds; tune against the physical reader if needed.
logger = logging.getLogger(__name__)


class _StudentNumberParser:
    def __init__(self) -> None:
        self.buffer = ""
        self.previous = 0.0

    def feed(self, timestamp: float, character: str) -> str | None:
        if timestamp - self.previous > INTER_KEY_TIMEOUT:
            self.buffer = ""
        self.previous = timestamp
        if character == "\n":
            buffer = self.buffer
            self.buffer = ""
            if len(buffer) == 9 and buffer.isascii() and buffer.isdigit():
                return buffer
        else:
            self.buffer = (self.buffer + character)[:10]
        return None


def student_numbers(events: Iterable[tuple[float, str]]) -> Iterator[str]:
    parser = _StudentNumberParser()
    for timestamp, character in events:
        number = parser.feed(timestamp, character)
        if number is not None:
            yield number


def _character(event) -> str | None:
    from evdev import ecodes

    if event.type != ecodes.EV_KEY or event.value != 1:
        return None
    if event.code == ecodes.KEY_ENTER:
        return "\n"
    digits = {getattr(ecodes, f"KEY_{digit}"): str(digit) for digit in range(10)}
    return digits.get(event.code, "?")


def read_characters(device) -> Iterator[tuple[float, str]]:
    for event in device.read_loop():
        character = _character(event)
        if character is not None:
            yield event.timestamp(), character


async def read_student_number_async(device, *, timeout: float = 10.0) -> str | None:
    """Read an unverified number; the caller owns device access and input freshness."""
    parser = _StudentNumberParser()
    deadline = asyncio.timeout(timeout)
    loop = asyncio.get_running_loop()
    events = device.async_read_loop()
    try:
        async with deadline:
            while True:
                event = await asyncio.shield(anext(events))
                character = _character(event)
                if character is not None:
                    number = parser.feed(event.timestamp(), character)
                    if number is not None:
                        return number
    except TimeoutError:
        if not deadline.expired():
            raise
        return None
    finally:
        loop.remove_reader(device.fileno())


def set_rf_field(reader, enabled: bool) -> None:
    logger.debug("[DEBUG-readers] RF-%s command starting", "on" if enabled else "off")
    response = reader.call_function(
        0x32,  # RFConfiguration command
        params=bytes([0x01, 0x03 if enabled else 0x02]),
        response_length=0,
    )
    if response is None:
        raise RuntimeError("PN532 did not confirm the command")
    logger.debug("[DEBUG-readers] RF-%s acknowledged", "on" if enabled else "off")


def read_uid(reader, timeout: float = 5.0) -> str | None:
    try:
        set_rf_field(reader, True)
        logger.debug("[DEBUG-readers] UID read starting (timeout=%ss)", timeout)
        uid = reader.read_passive_target(timeout=timeout)
        logger.debug("[DEBUG-readers] UID read returned: %s", "card found" if uid else "no card")
    finally:
        set_rf_field(reader, False)

    if uid is None:
        return None
    return uid.hex().upper()


async def read_uid_async(reader, timeout: float = 5.0) -> str | None:
    worker = asyncio.create_task(asyncio.to_thread(read_uid, reader, timeout=timeout))
    cancellation: asyncio.CancelledError | None = None
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as error:
            logger.debug("[DEBUG-readers] Cancellation requested; waiting for UID worker cleanup")
            cancellation = error

    result = worker.result()
    logger.debug("[DEBUG-readers] UID worker finished")
    if cancellation is not None:
        raise cancellation
    return result


async def read_card_async(
    uid_reader, student_reader, *, student_timeout: float = 10.0
) -> tuple[str, str] | None:
    """Wait for a UID, then a complete number; None means incomplete collection.

    One caller owns both devices. Discard queued input BEFORE each UID attempt,
    never after RF-off when the new number may already be arriving. This boundary
    removes buffered input, but cannot prove same-card identity or exclude a swap.
    Cancellation waits for the PN532 worker through read_uid_async().
    """
    while True:
        logger.debug("[DEBUG-readers] Draining queued OMNIKEY input")
        discarded = 0
        while student_reader.read_one() is not None:
            discarded += 1
            if discarded % 100 == 0:
                logger.debug("[DEBUG-readers] Still draining OMNIKEY: %s events", discarded)
            await asyncio.sleep(0)
        logger.debug("[DEBUG-readers] OMNIKEY drain finished: %s events", discarded)
        logger.debug("[DEBUG-readers] Scheduling UID worker")
        uid = await read_uid_async(uid_reader)
        if uid is not None:
            break
    print(f"UID received: {uid}")
    print("Keep the card presented; waiting for student number...")
    number = await read_student_number_async(student_reader, timeout=student_timeout)
    if number is None:
        return None
    print(f"Student number received (unverified): {number}")
    return uid, number


@contextmanager
def open_readers(device_path: str):
    """Context manager to open the PN532 and OMNIKEY readers."""
    import board
    from adafruit_pn532.spi import PN532_SPI
    from digitalio import DigitalInOut
    from evdev import InputDevice

    with (
        closing(InputDevice(device_path)) as device,
        board.SPI() as spi,
        DigitalInOut(board.D5) as cs,
    ):
        reader = PN532_SPI(spi, cs)
        try:
            reader.SAM_configuration()
            set_rf_field(reader, False)
            if "OMNIKEY" not in device.name.upper():
                raise ValueError(f"{device_path} is {device.name!r}, not an OMNIKEY reader")
            with device.grab_context():
                yield reader, device
        finally:
            set_rf_field(reader, False)
