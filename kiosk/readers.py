"""This module contains the hardware operations for the PN532 NFC reader, and the OMNIKEY 5427 CK
reader, which is a USB smart card reader. The PN532 is used to get the UID of the card, and the
OMNIKEY is used to read the student number from the card."""

from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager

INTER_KEY_TIMEOUT = 2.0  # Seconds; tune against the physical reader if needed.


def student_numbers(events: Iterable[tuple[float, str]]) -> Iterator[str]:
    buffer = ""
    previous = 0.0
    for timestamp, character in events:
        if timestamp - previous > INTER_KEY_TIMEOUT:
            buffer = ""
        previous = timestamp
        if character == "\n":
            if len(buffer) == 9 and buffer.isascii() and buffer.isdigit():
                yield buffer
            buffer = ""
        else:
            # Ten characters keep an overlong scan invalid without unbounded storage.
            buffer = (buffer + character)[:10]


def read_characters(device) -> Iterator[tuple[float, str]]:
    from evdev import ecodes

    digits = {getattr(ecodes, f"KEY_{i}"): str(i) for i in range(10)}
    for event in device.read_loop():
        if event.type != ecodes.EV_KEY or event.value != 1:
            continue  # Ignore releases, held-key repeats, and non-key events.
        if event.code == ecodes.KEY_ENTER:  # noqa: SIM108 - Keep the translation steps explicit.
            character = "\n"
        else:
            character = digits.get(event.code, "?")
        yield event.timestamp(), character


def set_rf_field(reader, enabled: bool) -> None:
    response = reader.call_function(
        0x32,  # RFConfiguration command
        params=bytes([0x01, 0x03 if enabled else 0x02]),
        response_length=0,
    )
    if response is None:
        raise RuntimeError("PN532 did not confirm the command")


def read_uid(reader, timeout: float = 5.0) -> str | None:
    try:
        set_rf_field(reader, True)
        uid = reader.read_passive_target(timeout=timeout)
    finally:
        set_rf_field(reader, False)

    if uid is None:
        return None
    return uid.hex().upper()


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
