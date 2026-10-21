# Raspberry Pi kiosk appliance — Friday supervised test

Updated 2026-10-19. Target: Friday 2026-10-23.

## Summary and boundaries

Prepare the existing Raspberry Pi 4 desktop installation to start the kiosk automatically, show both displays on their assigned monitors, send real activation requests to the team backend, and recover from application crashes, reader faults, and restored power without a keyboard.

Use Chromium's **kiosk mode** for fullscreen presentation and **systemd** [Linux's service manager] to supervise the Python process. This builds on [Raspberry Pi's official kiosk setup](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/).

This repo stays kiosk-only. Machine nodes live in a separate repo and use the team's backend API. Friday is a **supervised test**, not unattended production access. Shane implements code and deployment templates with mentor support.

**Friday's backend contract is [ops-api.md](ops-api.md); Shane owns ops-backend.** For the supervised test only, the kiosk auto-registers unverified UID + student-number pairs: the controller emits `IdentityConfirmed` right after each `CardRead` (marked `TODO(same-card)`). This knowingly accepts the card-swap gap described in the [TODO](../TODO.md#same-card-identity-options--investigation-deferred) and must be reverted before unattended use.

Already in place, no work needed: the web server starts before the readers open (`kiosk/__main__.py`), and the pages show "connection lost" and recover by themselves when Python restarts (`kiosk/web/app.js`).

## 1. Pi configuration

- Inventory the OS, labwc desktop session, Chromium version and binary name, SPI enabled, both HDMI outputs (`HDMI-A-1`, `HDMI-A-2`), and the OMNIKEY's `/dev/input/by-id/` link. Keep the existing OS.
- Back up the working SD card before appliance changes.
- Create a non-administrator `kioskapp` account in the `input`, `spi`, `gpio`, `video`, and `render` groups. It runs the Python service and is the desktop autologin user. The existing `kiosk` account is Shane's admin account. Autologin must never land in an account with sudo: the kiosk is on public display and has USB ports. Verify Shane's own SSH access before enabling autologin.
- Deploy a pinned git checkout to `/opt/kiosk` with its own virtual environment (`pip install -e ".[hardware]"`), separate from Shane's development checkout. The admin `kiosk` account owns it; `kioskapp` can read and run it but not change it.
- Confirm NetworkManager reconnects automatically. Booting and showing local status must not depend on the network.
- Turn off screen blanking with `raspi-config`.
- Keep the filesystem writable. A read-only overlay is deferred; it would also discard the pending-operation record (section 4).

## 2. Automatic startup and both displays

### Python: `kiosk.service`

A system unit (starts at boot, independent of desktop login). Directives and why:

| Directive | Reason |
|---|---|
| `User=kioskapp`, `WorkingDirectory=/opt/kiosk` | Non-admin account, deployed checkout. |
| `ExecStart=/opt/kiosk/.venv/bin/python -m kiosk --device /dev/input/by-id/<omnikey>-event-kbd --backend <url>` | Stable reader path; real backend. |
| `Environment=PYTHONUNBUFFERED=1` | `print()` is block-buffered when not attached to a terminal; without this the journal lags. |
| `EnvironmentFile=/etc/kiosk/kiosk.env` | Backend credential. Root-owned, mode 0600, never committed, never logged. |
| `StateDirectory=kiosk` | systemd creates `/var/lib/kiosk/`, writable by `kioskapp`, for the pending-operation record. |
| `Restart=always`, `RestartSec=5` | Restart after any exit. `systemctl stop` still stays stopped. |
| `StartLimitIntervalSec=0` (in `[Unit]`) | Never give up retrying, so an unplugged reader cannot permanently disable the service. |
| `KillSignal=SIGINT`, `TimeoutStopSec=30` | Python's default SIGTERM handling exits **without** running `finally` blocks, so the PN532 RF-off and device cleanup in `open_readers` would be skipped. `asyncio.run` turns SIGINT into task cancellation, so the existing cleanup runs. No code needed. |

HTTP stays bound to `127.0.0.1:8000`. Logs go to the journal; its default size limits are enough.

### Browsers

The labwc `autostart` file (in the `kioskapp` user's labwc config; source in `deploy/labwc/`) waits 30 seconds once, then starts one shell loop per display.

**The 30-second boot delay is required.** Without it, Chromium launched right after login comes up as a fullscreen grey window every time (both instances log "Network service crashed" about two seconds in). Launched later, or relaunched by the loop, it renders. Root cause unknown (tested 2026-10-20).

Each loop:

1. Wait until `curl -sf http://127.0.0.1:8000/` succeeds. If Chromium loads before the server is up, it shows its own error page, which does not reliably retry.
2. `while :; do chromium …; sleep 5; done` so a closed or crashed browser comes back after five seconds.

Chromium flags per instance:

- `--kiosk --no-first-run --noerrdialogs`
- `--user-data-dir=<separate directory per display>`. Two kiosk windows need separate profiles.
- `--incognito` prevents the "restore pages?" bubble after a power cut.
- `--password-store=basic` prevents the keyring unlock prompt that otherwise appears on autologin and covers the page.
- `--class=kiosk-d1` / `--class=kiosk-d2` gives each window a distinct identity.
- URL `http://127.0.0.1:8000/?display=1` (student) or `?display=2` (public).

Assign windows to outputs with labwc window rules: `kiosk-d1` (student, left monitor) → `MoveToOutput output="HDMI-A-2"`, `kiosk-d2` (public, right monitor) → `HDMI-A-1`. The rules only move the window; `--kiosk` makes it fullscreen. Do not add `ToggleFullscreen`: every boot test with it came up grey or windowed. `--class` sets the Wayland app_id only with `--kiosk` or a normal window, not with `--app`. Do not match on title: the page title is the same for both displays until JavaScript runs. Do not rely on launch order. [labwc configuration reference](https://labwc.github.io/labwc-config.5.html)

Python restarts need no browser action. **Monitor reconnection** is manual for Friday: over SSH, `pkill chromium` as `kioskapp`; the loops relaunch and the window rules reapply. Automatic hotplug handling is deferred.

## 3. Readers and fault recovery

- Use the OMNIKEY's `/dev/input/by-id/…-event-kbd` link. Only if no such link exists, add a udev rule matching its vendor/product and serial number that creates `/dev/kiosk-student-reader`.
- Keep the OMNIKEY name check, exclusive grab, PN532 SPI wiring, and GPIO5 chip select.
- **Recovery = exit and let systemd restart.** In hardware mode, when a `ReaderFault` is handled and no operation is pending, end `run()` and exit non-zero. systemd restarts five seconds later. The process exit closes and releases both devices, and the new process reopens them, so cleanup always finishes before the next open and there is never a second reader session. If the reader is still missing, `open_readers` fails and the cycle repeats every five seconds. The displays briefly show "connection lost" — acceptable for a supervised test.
  - This is safe because acquisition only runs when `IDLE` with `pending_op` empty, so a reader fault cannot interrupt a backend write. Any write in progress is also recorded on disk (section 4).
- Remove the raw UID and student-number prints (`kiosk/readers.py`, `read_card_async`). Keep non-identifying progress messages.
- Do not change the deferred same-card policy.

## 4. Real backend writes and power-loss recovery

### Backend client

- Implement in-process with `aiohttp.ClientSession` (already a dependency). The `--backend <url>` flag selects the real client. Without it, the existing simulated backend stays for the desktop demo.
- Endpoints, request/response fields, authentication, and the recovery lookup are defined in [ops-api.md](ops-api.md).
- Emit `BackendOnline` only after a real health check succeeds. A `BackendError` sets the machine offline, so keep re-checking every few seconds while offline and emit `BackendOnline` when it passes.
- The HTTP timeout must be shorter than the session timer, so most failures arrive as `BackendError` rather than through the session timeout.

### Durable pending-operation record

Process restarts (reader-fault exits, crashes, power loss) erase the machine's in-memory `OUTCOME_UNKNOWN` hold. A file on disk keeps it.

- Before sending a write, write one JSON file in `/var/lib/kiosk/` (write to a temporary file, `fsync`, then `os.replace`). If that fails, do not send; report `BackendError(..., FailureKind.NOT_SENT)`.
- Contents, kept minimal: operation name, a new `uuid4` request ID that is also sent to the backend, and a timestamp. Never use session IDs as request references: they restart at 0 every time the process starts.
- Delete the file only after an authoritative result for that operation.
- **On startup:** if the file exists, start with `Context(pending_op=<op>)`. The existing `_resting_state` then holds `OUTCOME_UNKNOWN`; no state-machine changes are needed.
- To clear the hold: call `GET /api/v1/kiosk/requests/{request_id}`. A stored result settles it. A 404 received after the original request's timeout window means nothing was committed. If the lookup fails on the network, stay held and retry. As a last resort, an operator checks ops directly, deletes the file, and runs `systemctl restart kiosk`. Never resend the write automatically. Never infer success or failure from a restart or a healthy connection.

### Screens and power

- The "Demo — no real access changes" banner in `kiosk/web/index.html` is hard-coded. With real writes it becomes false. Drive it from the mode (for example a flag in the display payload): show it in simulated mode only. A simulated success never counts as backend integration.
- Test the full sequence: power restored → Pi boots → Python starts → desktop logs in → both fullscreen pages. Configure each monitor's own power-restore setting; the Pi cannot turn the monitors on.
- The Pi has no real-time clock. After a long outage, TLS to the backend can fail until the clock syncs; the kiosk shows unavailable until then.
- Never reboot automatically for backend outages or unresolved results.

Deferred: hardware watchdog, recovery from a fully frozen OS, UPS, read-only overlay, automatic monitor-hotplug handling.

## 5. Schedule and acceptance

### Tuesday: configuration, startup, backend inputs

- Inventory and back up the Pi; create the `kioskapp` account; deploy to `/opt/kiosk`; find the by-id path.
- `kiosk.service` as above; exit-on-reader-fault; remove identifier prints; desktop autologin.
- Confirm startup with no keyboard or terminal session.
- Ops side ([ops-api.md](ops-api.md)): kiosk and node tokens, a test environment, and the training-level stub until the dashboard endpoint lands. Prepare two test students: one with training, one without.

### Wednesday: screens, recovery, backend client

- Browser autostart and window rules; verify both screen assignments through three consecutive reboots.
- Kill Python and each browser separately; verify automatic recovery.
- Unplug and replug the OMNIKEY and each monitor; verify recovery (monitors via the manual SSH step).
- Boot without network; local screens must still appear (offline status).
- Backend client, health check, durable record, and startup hold, tested against the backend's test environment or a local stub.

### Thursday: integration and endurance

- Two-hour unattended soak with both screens up and the reader waiting, plus at least 100 counted scan cycles with alternating test cards. The earlier PN532 RF failure appeared after about a minute; record any repeat.
- `journalctl -u kiosk | grep -E '[0-9]{9}'` returns no student numbers; check for UIDs too.
- Pull power and restore it; both screens appear within about 2 minutes (desktop at ~68 s, plus the 30-second browser delay and Chromium startup). The original 90-second target is not met; trimming boot services is deferred.
- Interrupt a write after the backend commits but before the reply (for example, drop the network). The hold must survive a restart and must not resend.
- End to end through ops: one test card activated at the kiosk is allowed by a node, and the untrained student's card is denied (`INSUFFICIENT_TRAINING` or `MISSING_INDUCTION`). Node code stays outside this repo.

### Friday: supervised demonstration

- Use the tested, pinned revision; no automatic pulls at boot.
- SSH runbook: status, logs, stop/restart, clearing a pending hold, restoring the previous revision.
- Report appliance acceptance separately from backend/node integration and from deferred identity assurance.

Deliverables: deployment templates under `deploy/` (unit file, labwc autostart, window rules, env-file example without secrets) and a short operating guide covering installation, monitor mapping, reader identification, recovery, clearing a hold, and rollback.
