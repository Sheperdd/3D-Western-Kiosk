# Makerspace Access Kiosk

A student-card registration and daily tool-access kiosk for 3D-Western. Students use their existing campus cards instead of borrowing separate RFID cards.

**Status:** the controller collects the UID and student number before starting simulated backend processing, then rearms after result feedback and reader cleanup. Both dummy displays render controller state through the local web app. Card removal is assumed, not detected. Real backend integration and validated same-card identity remain pending. Start with [the implemented transitions and next work](docs/plan.md#7-core-migration-implemented-and-next-work), [glossary](CONTEXT.md), and [open questions](TODO.md).

## Intended student flow

1. **First registration:** present one student card to two adjacent readers. The PN532 reads the hexadecimal UID and disables its RF field; the OMNIKEY then reads the student number. The backend verifies the account, general induction, and eligibility before registering the association and activating the visit. Reliable same-card assurance remains to be established before production registration.
2. **Repeat visits:** keep the card presented until both the UID and student number are collected, then begin backend processing. The backend checks current eligibility and activates access. If already active, the kiosk confirms that status; it does not check the student out.
3. **Replacement card:** registration replaces the old UID association after verification, invalidates the old card's access, and activates the replacement.
4. **Daily reset:** activation expires at midnight in America/Toronto. Registration remains, and an eligible student may immediately reactivate. One activation covers all participating tools; each tool still checks its own training requirements.

No account means an account-signup QR and a rescan after signup. Missing induction means a training-signup QR, with no registration or activation. Backend unavailability prevents registration and activation; success requires backend confirmation.

One-presentation registration has been tested on one card. Broader reliability and safe pairing of the two reader outputs remain validation tasks.

## Responsibilities and hardware

The kiosk handles student interaction and calls the agreed backend interface. The backend/tool team owns accounts, training, eligibility, persistent associations, visit records, daily expiry, and tool enforcement. Entrance-door control is outside scope.

The current hardware plan retains a Raspberry Pi 4 (4 GB or more), the OMNIKEY 5427, a UID reader, and two output-only displays: display 1 guides the current student's registration or activation; display 2 shows general instructions and system status without student-specific information. See the [buylist](docs/buylist.txt) for planning details. The retained architecture direction is a Python core with a Chromium web UI; it is not all implemented.

V1 has no card dispensing, returns, motors, stock tracking, or non-return flags. Founder access is deferred for further requirements gathering. [ADR-0005](docs/adr/0005-student-card-registration-and-daily-activation.md) explains the change; the old [M1 roadmap](docs/m1-roadmap.md) is historical.

## Development

Requires Python 3.13 or later, as declared in `pyproject.toml`.

```sh
python -m venv .venv
.venv/Scripts/activate        # Windows; use bin/activate elsewhere
pip install -e .
pip install --group dev
```

Checks for implementation work:

```sh
ruff format --check kiosk tests
ruff check kiosk tests
pyright
pytest tests/test_machine.py tests/test_invariants.py
```

Run checks in the activated virtual environment. If Pyright cannot locate its interpreter, pass `--pythonpath .venv/Scripts/python.exe` on Windows (or `.venv/bin/python` on the Pi).

The pure state machine uses `handle(state, context, event)` to return a new state, context, and effects without I/O. A complete `CardRead` starts backend activation; an unregistered UID proceeds to registration only with a separately confirmed identity pair. Raw observed numbers cannot authorize registration or replacement. Results and timers are scoped to the interaction. Lost write responses hold the machine in `OUTCOME_UNKNOWN`; reconnection alone does not release that hold.

Run `python -u -m kiosk --device /dev/input/eventX` on the Pi using the identified OMNIKEY path. Hold the card through the student-number beep, then take it back. Both identifiers print before the simulated backend result. After the outcome-specific result display, `Ready for next card.` marks automatic rearming; no restart is needed. Missing student-number input expires after `STUDENT_NUMBER_TIMEOUT` (currently 10 seconds) with no backend call, then follows the same feedback/rearm flow. The controller waits for reader cleanup and backend/reader readiness before acquiring again. Card removal is assumed: a held card may be processed again. Raw identifier prints remain for local testing and must be removed or gated before production.

## Dummy displays

Run `python -m kiosk` and open both pages on the kiosk computer:

- Student display: <http://127.0.0.1:8000/?display=1>
- Public guidance: <http://127.0.0.1:8000/?display=2>

The desktop demo waits 10 seconds after starting the web server before sending one simulated card scan, leaving the ready screen visible during the pause. Keep the pages open and restart the process to replay it; refreshing a page does not restart the interaction. The displays poll every 250 ms and recover automatically after a connection failure. Python owns state transitions and result durations: success/assistance 10 seconds, signup/training 30 seconds, retry 6 seconds. Activation simulates 2.5 seconds of backend latency; there is no guaranteed minimum visible checking time.

Every controller state and final outcome has student-facing copy. The public display only shows general guidance and availability. Neither displays student identifiers. Success screens show unavailable training/machine details until the backend supplies them. Signup and induction screens have clearly labelled, non-scannable placeholders until approved URLs are available. All screens are visibly marked as a demo.

The UI uses plain HTML, CSS and JavaScript with no build step or external assets. Run its rendering and polling tests with Node.js 18 or newer:

```sh
node --test tests/test_display_ui.cjs
```

Review the wording and check readability on the actual kiosk monitors before deployment. The tests cover the core's decisions using synthetic events. They do not establish physical same-card assurance, backend persistence, replacement invalidation, midnight expiry, or tool enforcement. The internal event/effect names are provisional and do not specify network endpoints. See [plan section 7](docs/plan.md#7-core-migration-implemented-and-next-work) for controller obligations and integration work. Shane normally writes implementation with mentor support; this core migration and the dummy frontend were explicitly delegated.
