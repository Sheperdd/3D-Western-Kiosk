
# Makerspace Access Kiosk

A student-card registration and daily tool-access kiosk for 3D-Western. Students use their existing campus cards instead of borrowing separate RFID cards.

**Status:** the controller collects the UID and student number before starting simulated backend processing, then rearms after result feedback and reader cleanup. Both dummy displays render controller state through the local web app. Card removal is assumed, not detected. Real backend integration and validated same-card identity remain pending. Start with [the implemented transitions and next work](docs/plan.md#7-core-migration-implemented-and-next-work), [glossary](CONTEXT.md), and [open questions](TODO.md).

## Intended student flow

1. **First registration:** present one student card to two adjacent readers. The PN532 reads the hexadecimal UID and disables its RF field; the OMNIKEY then reads the student number. The backend verifies the account, general induction, and eligibility before registering the association and activating the visit. Reliable same-card assurance remains to be established before production registration.
2. **Repeat visits:** keep the card presented until both the UID and student number are collected, then begin backend processing. The backend checks current eligibility and activates access. If already active, the kiosk confirms that status; it does not check the student out.
3. **Replacement card:** registration replaces the old UID association after verification, invalidates the old card's access, and activates the replacement.
4. **Daily reset:** activation expires at midnight in America/Toronto. Registration remains, and an eligible student may immediately reactivate. One activation covers all participating tools; each tool still checks its own training requirements.

No account means an account-signup QR and a rescan after signup. Missing induction means a training-signup QR, with no registration or activation. Backend unavailability prevents registration and activation; success requires backend confirmation.

One-presentation identifier collection has been tested on one card. Real registration, broader reliability, and safe pairing of the two reader outputs remain validation tasks.

## Responsibilities and hardware

The kiosk handles student interaction and calls the agreed backend interface. The backend/tool team owns accounts, training, eligibility, persistent associations, visit records, daily expiry, and tool enforcement. Entrance-door control is outside scope.

The current hardware plan retains a Raspberry Pi 4 (4 GB or more), the OMNIKEY 5427, a PN532 UID reader, and two output-only displays: display 1 guides the current student's registration or activation; display 2 shows general instructions and system status without student-specific information. See the [reader setup and trials](docs/reader-testing.md). The Python core and local web UI are implemented; appliance deployment remains pending.

V1 has no card dispensing, returns, motors, stock tracking, or non-return flags. Founder access is deferred for further requirements gathering. [ADR-0005](docs/adr/0005-student-card-registration-and-daily-activation.md) explains the change.

## Development

Requires Python 3.13 or later, as declared in `pyproject.toml`.

```sh
python -m venv .venv
.venv/Scripts/activate        # Windows; use bin/activate elsewhere
pip install -e .
pip install --group dev
```

That installation supports the desktop demo. On the Raspberry Pi, also install the declared hardware dependencies in the activated environment before running either reader command:

```sh
python -m pip install -e ".[hardware]"
```

See the [reader guide](docs/reader-testing.md) for wiring, input-device identification, and permissions. Full implementation checks (JavaScript tests require Node.js 18 or newer):

```sh
ruff format --check kiosk tests tools
ruff check kiosk tests tools
pyright
pytest
node --test tests/test_display_ui.cjs
```

Run checks in the activated virtual environment. If Pyright cannot locate its interpreter, pass `--pythonpath .venv/Scripts/python.exe` on Windows (or `.venv/bin/python` on the Pi). The tests use fake devices and run on Windows. Full Pyright validation requires the hardware dependencies in a Linux/Pi environment; the desktop-only installation reports missing hardware imports, so it is not a clean full type check.

The pure state machine uses `handle(state, context, event)` to return a new state, context, and effects without I/O. A complete `CardRead` starts backend activation; an unregistered UID proceeds to registration only with a separately confirmed identity pair. Raw observed numbers cannot authorize registration or replacement. Results and timers are scoped to the interaction. Lost write responses hold the machine in `OUTCOME_UNKNOWN`; reconnection alone does not release that hold.

Run `python -u -m kiosk --device /dev/input/eventX` on the Pi using the identified OMNIKEY path. Hold the card through the student-number beep, then take it back. `UID received.` and `Student number received.` print before the simulated backend result; the identifiers themselves are never printed. After the outcome-specific result display, `Ready for next card.` marks automatic rearming; no restart is needed. Missing student-number input expires after `STUDENT_NUMBER_TIMEOUT` (currently 10 seconds) with no backend call, then follows the same feedback/rearm flow. The controller waits for reader cleanup and backend/reader readiness before acquiring again. Card removal is assumed: a held card may be processed again. To see the actual identifiers, use the reader probe (`tools.student_number_probe`) by hand; it is never run by the service.

## Dummy displays

Run `python -m kiosk` and open both pages on the kiosk computer:

- Student display: <http://127.0.0.1:8000/?display=1>
- Public guidance: <http://127.0.0.1:8000/?display=2>

The desktop demo waits 10 seconds after starting the web server before sending one simulated card scan, leaving the ready screen visible during the pause. Both desktop and hardware demos default to successful simulated activation; choosing readers does not select a backend outcome. Registration and failure scenarios are exercised explicitly in the tests. Keep the pages open and restart the process to replay the desktop scan; refreshing a page does not restart the interaction. The displays poll every 250 ms and recover automatically after a connection failure. Python owns state transitions and result durations: success/assistance 10 seconds, signup/training 30 seconds, retry 6 seconds. Activation simulates 2.5 seconds of backend latency; there is no guaranteed minimum visible checking time.

Every controller state and final outcome has student-facing copy. The public display only shows general guidance and availability. Neither displays student identifiers. Success screens show unavailable training/machine details until the backend supplies them. Signup and induction screens have clearly labelled, non-scannable placeholders until approved URLs are available. All screens are visibly marked as a demo.

The UI uses plain HTML, CSS and JavaScript with no build step or external assets. During reader cleanup, display 1 says “Getting ready for the next card” and display 2 remains “In use.” The ready message appears when acquisition is available again. The local student API exposes `state` and `outcome`; the public API exposes only `status`.

Review the wording and check readability on the actual kiosk monitors before deployment. The tests cover the core's decisions using synthetic events. They do not establish physical same-card assurance, backend persistence, replacement invalidation, midnight expiry, or tool enforcement. The internal event/effect names are provisional and do not specify network endpoints. See [plan section 7](docs/plan.md#7-core-migration-implemented-and-next-work) for controller obligations and integration work. Shane normally writes implementation with mentor support; this core migration and the dummy frontend were explicitly delegated.

## Raspberry Pi command reference

Run these on the Pi (over SSH or a local terminal), not on Windows. Paths in angle brackets are placeholders. Commands marked *(after deployment)* depend on the `kioskapp` account, `/opt/kiosk` checkout, and `kiosk.service` described in the [appliance plan](docs/kiosk-appliance-plan.md); they do not exist yet.

### System and access

```sh
ssh <user>@<pi-hostname>.local     # connect from the dev machine
cat /etc/os-release                # OS version
python3 --version
uname -a                           # kernel and architecture
hostname -I                        # Pi's IP addresses
sudo apt update && sudo apt full-upgrade
sudo reboot
sudo shutdown -h now               # always do this before rewiring the PN532
vcgencmd measure_temp              # CPU temperature
vcgencmd get_throttled             # 0x0 = no undervoltage/throttling ever seen
df -h                              # free disk space
free -h                            # free memory
```

### Project setup and updates

```sh
git clone <repo-url> && cd Kiosk
python3 -m venv .venv
source .venv/bin/activate          # every new shell; `deactivate` to leave
python -m pip install -e ".[hardware]"
pip install --group dev            # only if running the checks on the Pi
git pull                           # development checkout only
git log --oneline -5               # which revision is running
```

### SPI and the PN532

```sh
sudo raspi-config                  # Interface Options → SPI → Enable; Display → Screen Blanking → Off
sudo raspi-config nonint get_spi   # 0 = SPI enabled
ls /dev/spidev*                    # expect /dev/spidev0.0 and /dev/spidev0.1
groups                             # need spi and gpio (and input for the OMNIKEY)
sudo usermod -aG spi,gpio,input $USER   # then log out and back in
pinout                             # header diagram; check pin 1 before counting
```

### Finding the OMNIKEY

```sh
sudo apt install usbutils evtest
lsusb                              # is the OMNIKEY on USB?
ls -l /dev/input/by-id/            # stable link; prefer the ...-event-kbd entry
cat /proc/bus/input/devices        # name → eventN mapping
sudo evtest --grab /dev/input/eventX   # watch raw key events; Ctrl+C before running Python
sudo dmesg -w                      # live kernel log while plugging/unplugging USB
```

### Running the kiosk and diagnostics

```sh
python -u -m tools.student_number_probe /dev/input/eventX   # readers only, no backend
python -u -m kiosk --device /dev/input/eventX               # full kiosk, simulated backend
python -m kiosk                                             # desktop demo, no readers
curl -s http://127.0.0.1:8000/                              # is the web server up?
ss -ltnp | grep 8000                                        # what is holding port 8000?
pkill -f "python -m kiosk"                                  # stop a stray kiosk process
pytest                                                      # tests (needs the dev group)
```

Open the displays in the Pi's browser at `http://127.0.0.1:8000/?display=1` and `?display=2`. To view them from your laptop without exposing the port, tunnel it: `ssh -L 8000:127.0.0.1:8000 <user>@<pi-hostname>.local`, then open the same URLs locally.

### Service and logs *(after deployment)*

```sh
sudo systemctl status kiosk
sudo systemctl start|stop|restart kiosk
sudo systemctl enable kiosk        # start at boot
sudo systemctl daemon-reload       # after editing the unit file
journalctl -u kiosk -f             # follow live logs
journalctl -u kiosk -b             # logs since this boot
journalctl -u kiosk --since "10 min ago"
journalctl -u kiosk | grep -E '[0-9]{9}'   # must return nothing (no student numbers logged)
systemd-analyze verify /etc/systemd/system/kiosk.service
```

### Displays and browsers *(after deployment)*

```sh
wlr-randr                          # list outputs (HDMI-A-1, HDMI-A-2) under labwc
chromium --version                 # binary may be chromium-browser on older images
sudo -u kioskapp pkill chromium       # relaunch both kiosk windows after a monitor replug
```

### Network and clock

```sh
nmcli device status                # NetworkManager connection state
nmcli connection show
ping -c 3 <backend-host>
timedatectl                        # "System clock synchronized: yes" before TLS works
```

### Pending-operation hold and rollback *(after deployment)*

```sh
ls -l /var/lib/kiosk/              # a file here means OUTCOME_UNKNOWN is held
cat /var/lib/kiosk/<pending-file>  # check the request ID against ops before deleting
sudo rm /var/lib/kiosk/<pending-file> && sudo systemctl restart kiosk   # operator-only, last resort
cd /opt/kiosk && git checkout <known-good-commit> && sudo systemctl restart kiosk   # as the admin kiosk account
```

Back up the SD card before appliance changes by imaging it from another computer (for example with Raspberry Pi Imager or `dd`), not from the running Pi.
