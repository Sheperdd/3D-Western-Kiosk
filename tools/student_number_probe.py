"""Two-reader diagnostic: print unverified card pairs; never register or activate cards."""

import argparse
import asyncio

from kiosk.readers import open_readers, read_card_async


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", nargs="?", default="/dev/input/event4")
    args = parser.parse_args()
    try:
        with open_readers(args.device) as (uid_reader, student_reader):
            print("Scan a card; Ctrl+C to stop.", flush=True)

            while True:
                print("Waiting for UID...", flush=True)

                pair = await read_card_async(uid_reader, student_reader)
                if pair is None:
                    print("Incomplete scan. Remove the card and try again.", flush=True)
                else:
                    uid, number = pair
                    print(f"UID: {uid}  Student number (unverified): {number}", flush=True)
                # shortcut: the pause assumes card removal; add detection if required.
                await asyncio.sleep(2)
    except OSError as error:
        parser.exit(
            1, f"Reader error: {error}. Check the device path/permissions and stop evtest.\n"
        )
    except ValueError as error:
        parser.exit(1, f"Reader error: {error}. Check the device path/permissions.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
