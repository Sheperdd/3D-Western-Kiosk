"""OMNIKEY diagnostic: print nine-digit scans; never register or activate cards."""

import argparse
import time
from contextlib import closing

import board
from adafruit_pn532.spi import PN532_SPI
from digitalio import DigitalInOut

INTER_KEY_TIMEOUT = 2.0  # Seconds; tune against the physical reader if needed.


def student_numbers(events):
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


def read_characters(device):
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


def set_rf_field(reader, enabled):
    response = reader.call_function(
        0x32,  # RFConfiguration command
        params=bytes([0x01, 0x03 if enabled else 0x02]),
        response_length=0,
    )
    if response is None:
        raise RuntimeError("PN532 did not confirm the command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", nargs="?", default="/dev/input/event4")
    args = parser.parse_args()

    from evdev import InputDevice  # Linux-only; parsing tests also run on Windows.

    try:
        with (
            closing(InputDevice(args.device)) as device,
            board.SPI() as spi,
            DigitalInOut(board.D5) as cs,
        ):
            reader = PN532_SPI(spi, cs)
            reader.SAM_configuration()
            set_rf_field(reader, False)
            if "OMNIKEY" not in device.name.upper():
                parser.error(f"{args.device} is {device.name!r}, not an OMNIKEY reader")
            with device.grab_context():
                print("Scan a card; Ctrl+C to stop.", flush=True)

                while True:
                    print("Waiting for UID...", flush=True)

                    try:
                        set_rf_field(reader, True)
                        uid = reader.read_passive_target(timeout=5.0)
                    finally:
                        set_rf_field(reader, False)

                    if uid is None:
                        print("No UID detected. Trying again.", flush=True)
                        continue

                    print("UID:", uid.hex().upper(), flush=True)

                    # Discard student-reader events received during the UID step.
                    while device.read_one() is not None:
                        pass

                    print("Waiting for student number...", flush=True)

                    for number in student_numbers(read_characters(device)):
                        print(f"Student number: {number}", flush=True)
                        time.sleep(2)  # Avoid repeated scans of the same card.
                        break
            # with device.grab_context():
            #     print(f"Reading {device.name}. Scan a card; Ctrl+C to stop.", flush=True)
            #     for number in student_numbers(read_characters(device)):
            #         print(f"Student number: {number}", flush=True)
            #         try:
            #             set_rf_field(reader, True)
            #             uid = reader.read_passive_target(timeout=5.0)

            #             if uid is None:
            #                 print("No card detected")
            #             else:
            #                 print("UID:", uid.hex().upper())
            #         finally:
            #             set_rf_field(reader, False)
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as error:
        parser.exit(
            1, f"Reader error: {error}. Check the device path/permissions and stop evtest.\n"
        )


if __name__ == "__main__":
    main()
