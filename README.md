# Makerspace Access Kiosk

A self-service kiosk that gives access to the 3D-Western makerspace machines and tools. A student scans their campus card and if their training is on file, the kiosk dispenses a reusable RFID **makerspace card** linked to them. Tools in the space unlock only for a card whose owner is trained on that tool. On the way out, the student drops the card back in the kiosk and the link is removed.

The kiosk owns the card lifecycle — dispense, link, unlink, return — and nothing else. Tool readers and the training database belong to the backend.

## How it works

**Checkout**

1. Student scans their campus card at the student-card reader (an OMNIKEY 5427 that types the student number as keyboard input).
2. The kiosk asks the backend whether that student is trained. Not trained → a QR code to the training signup page. No club account → a QR code to account signup.
3. If trained, the motorised iris on the dispense box opens. The student takes one card and taps it on the makerspace-card reader, which links the card to them in the backend. The iris closes.

**Return**

A linked makerspace card tapped at the reader — by anyone, at any time — unlinks it and unlocks the return drawer to drop it into. No student-card scan is needed to return a card, so cards can be handed back for someone else (see [ADR-0004](docs/adr/0004-single-shared-makerspace-card-reader.md)).

**Offline behaviour**

The kiosk runs on WiFi and treats backend blips as routine. Checkout **fails closed** (no training check, no card), returns **stay open** — the drawer still accepts cards and the unlink is queued in a local outbox, retried until delivered. A nightly backend-side reset unlinks anything that slipped through (see [ADR-0002](docs/adr/0002-offline-failure-policy.md)).

## Architecture

One Python asyncio process on a Raspberry Pi 5 owns everything: both card readers (exclusively grabbed as evdev devices so scans can't leak keystrokes anywhere else), the dispense-box iris, the return drawer, and two output-only displays rendered by Chromium in kiosk mode from a locally served web page ([ADR-0003](docs/adr/0003-python-core-web-ui-scan-driven.md)).

The core of the design is a **pure state machine**:

```
handle(state, context, event) -> (new_state, new_context, [effects])
```

- **Events** are facts that already happened: a card was scanned, the backend answered, a motor finished or jammed, a timeout fired.
- **Effects** are instructions handed back for execution: move a motor, call the backend, start a timeout, raise a staff alert.
- The machine does no I/O and never sees a clock. The controller executes effects and feeds their outcomes back in as new events. Displays are never commanded directly — the controller broadcasts a full state snapshot over a websocket on every transition, and each display renders it.

This makes every flow — including motor jams and offline edge cases — unit-testable with plain function calls, no hardware and no mocks of the machine itself.

```
kiosk/            # the Python core
├── events.py     # event, state, and effect vocabularies
└── machine.py    # pure transition function + session context
tests/            # pytest suite, one test per transition
docs/
├── adr/          # architecture decision records
└── agents/       # agent workflow docs
CONTEXT.md        # domain glossary — the project's ubiquitous language
TODO.md           # open questions awaiting decisions
```

## Hardware (v1)

| Part | Role |
|---|---|
| Raspberry Pi 5 | runs the single Python core + both displays |
| OMNIKEY 5427 | student-card reader (keyboard wedge, outputs student number) |
| 13.56 MHz RFID reader | single shared makerspace-card reader for link and return |
| Iris-diaphragm dispense box | motorised enclosure holding the card pool |
| Locking return drawer | motorised drawer that collects returned cards |
| 2 × 15.6" USB-C/HDMI displays | output-only screens (front + return side), no touch |

> [!NOTE]
> Motor control is an abstract protocol with mock drivers for now — the mechanical design (iris vs. single-vend dispenser) is still being decided, so v1 code runs fully against fakes.

## Development

Requires Python 3.13 (the Pi's version).

```sh
python -m venv .venv
.venv/Scripts/activate        # Windows; use bin/activate elsewhere
pip install -e .
pip install --group dev
```

Quality gates — all three must pass before anything is considered done:

```sh
ruff format
ruff check
pyright
pytest
```

The state machine develops test-first: transitions are written as failing tests from the design's transition table, then implemented until green.

## Status

Early development. The event/state/effect vocabularies and the happy checkout path of the state machine are implemented and tested; returns, offline handling, jam escalation, the web UI, the backend client, and Pi provisioning are in progress. The backend REST contract is a proposal pending review with the backend team.
