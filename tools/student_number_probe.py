"""OMNIKEY diagnostic: print nine-digit scans; never register or activate cards."""

import argparse
import time

from kiosk.readers import open_readers, read_characters, read_uid, student_numbers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", nargs="?", default="/dev/input/event4")
    args = parser.parse_args()
    try:
        with open_readers(args.device) as (reader, device):
            print("Scan a card; Ctrl+C to stop.", flush=True)

            while True:
                print("Waiting for UID...", flush=True)

                uid = read_uid(reader)

                if uid is None:
                    print("No card detected; try again.", flush=True)
                    continue

                print(f"UID: {uid}", flush=True)

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
