"""This module contains the hardware operations for the PN532 NFC reader, and the OMNIKEY 5427 CK
reader, which is a USB smart card reader. The PN532 is used to get the UID of the card, and the
OMNIKEY is used to read the student number from the card."""

from contextlib import closing, contextmanager


def set_rf_field(reader, enabled: bool) -> None:
    response = reader.call_function(
        0x32,  # RFConfiguration command
        params=bytes([0x01, 0x03 if enabled else 0x02]),
        response_length=0,
    )
    if response is None:
        raise RuntimeError("PN532 did not confirm the command")


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
