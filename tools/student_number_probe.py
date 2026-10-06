"""OMNIKEY diagnostic: print nine-digit scans; never register or activate cards."""

import argparse
import time

from kiosk.readers import open_readers, set_rf_field

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", nargs="?", default="/dev/input/event4")
    args = parser.parse_args()
    try:
        with open_readers(args.device) as (reader, device):
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
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as error:
        parser.exit(
            1, f"Reader error: {error}. Check the device path/permissions and stop evtest.\n"
        )
    except ValueError as error:
        parser.exit(1, f"Reader error: {error}. Check the device path/permissions.\n")


if __name__ == "__main__":
    main()
