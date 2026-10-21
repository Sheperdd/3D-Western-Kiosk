# Student-card kiosk — Requirements and SDLC plan

**Update, 2026-10-20:** tap-out and daily registration ([ADR-0006](adr/0006-tap-out-and-daily-registration.md)). R4, R5, R6, and R8 and their acceptance rows are rewritten. The kiosk code changes for this are **pending**: the section 7 transition table describes the target, and the current code still returns `ACTIVATED`/`ALREADY_ACTIVE`.

Updated 2026-10-13 for reader fault handling, display readiness, and shared diagnostics. **Current phase: the controller collects both identifiers before simulated backend processing; real backend integration and broader reader validation remain open.** This replaces the card-lending implementation plan. The requirements below describe the intended student-only v1; core test coverage is not evidence that the integrated kiosk is delivered.

## 1. Purpose, scope, and current state

Students tap their existing student cards to check in to and out of the makerspace, which grants access to participating tools while they are checked in. They do not borrow a second card. Check-in registers the card UID to a student number for that visit and activates the visit; check-out or midnight ends both.

The project delivers the kiosk and agrees its interface with the backend team. The backend/tool team owns accounts, training, eligibility policy, persistent card associations, visit records, daily expiry, and tool access enforcement. The kiosk neither controls tool power nor unlocks entrance doors.

V1 serves students only. Founder enrolment and access require a later requirements discussion; earlier ideas about personal founder RFID cards and backend provisioning remain provisional. Card dispensing, returns, iris and drawer motors, stock tracking, non-return flags, and the unlink outbox are outside current v1. Occupancy counting remains deferred.

The events, pure state machine, and tests in `kiosk/` and `tests/` model the student-card flows described in section 7. Motor, stock, return, and temporary-link behavior has been removed. The controller and shared readers support repeated scans after result feedback and cleanup, assuming students take their cards back. Both dummy displays render current state and availability. The backend is simulated; verified same-card identity and production integration remain open. [ADR-0005](adr/0005-student-card-registration-and-daily-activation.md) records the scope change.

## 2. Confirmed requirements

| ID | Requirement |
|---|---|
| R1 | Registration is fully self-service and uses one physical student-card presentation. The PN532 first reads the hexadecimal UID; its RF field is then disabled so the OMNIKEY can read the student number. Both identifiers refer to the student's existing card, not a separate loan card. |
| R2 | Before registering a UID, the backend must confirm an existing account, completed general induction, and eligibility under its access policy. The backend owns additional restrictions and supplies the denial reason. |
| R3 | Successful registration also activates the visit. The kiosk displays success only after backend confirmation of activation. |
| R4 | Every kiosk presentation must supply both the UID and student number before backend processing starts. The backend first checks whether that UID has an active visit (R5); otherwise the presentation is a check-in, with registration and eligibility checks (R1–R3). Tool readers are unchanged. |
| R5 | A tap with a card that has an active visit checks the student out: the backend ends the visit and its registration, and the kiosk confirms it. Check-out requires no eligibility check. A later tap checks in again. There is no double-tap guard; a held card toggles the visit (accepted, see ADR-0006). |
| R6 | A replacement student card is registered automatically after successful identification and eligibility checks. It replaces the UID on the student's active visit and permanently revokes the old card. |
| R7 | One activation is recognised across all participating tools without separate makerspace check-ins. Each tool still enforces its own training requirements. General induction does not grant permission to use every tool. |
| R8 | The backend expires visits and their registrations at 00:00 America/Toronto each day, following local daylight-saving changes. This is the daily UID wipe; it needs no job. Revoked cards stay revoked. This is a daily reset, not an opening-hours restriction; eligible students may check in again immediately. |
| R9 | An unknown student number produces an account-signup QR. Save no association; the student signs up and presents their card again. |
| R10 | Missing general induction produces a training-signup QR. Do not register or activate the card; the student returns after the backend records eligibility. |
| R11 | If the backend is unavailable, refuse registration and activation and show an offline message. Never report success without confirmation. Recovery from an uncertain write outcome must be agreed with the backend team. |
| R12 | Retain two output-only displays. Display 1 guides the current student through registration or activation, including prompts, QR codes, and results. Display 2 shows general instructions and system status, without the current student's personal information. These are the agreed roles for now; the previous checkout/return split no longer applies. |
| R13 | Incomplete, delayed, repeated, or conflicting reader output must never associate one student's number with another card's UID. The mechanism for reliably correlating readings is not yet decided. |

Shane reports the UID-first arrangement works with one presentation. This is evidence of feasibility, not completed multi-card, endurance, or misassociation testing. See section 6 for the experiment and its limits.

## 3. Acceptance criteria

These are acceptance scenarios for the integrated system. The revised core suite covers its transition decisions for these flows; hardware, backend, and display evidence is still required where indicated.

| Scenario | Required outcome | Requirements |
|---|---|---|
| Eligible first registration | One presentation yields both identifiers; confirmed registration and activation produce success. | R1–R3 |
| Check-in | One presentation supplies both identifiers before any backend processing. Missing either identifier starts no backend operation. A card without an active visit is registered and activated after eligibility checks. | R4 |
| Check-out | A tap with an active card ends the visit; tools then refuse the card. A suspended student or a dashboard outage does not block check-out. A following tap checks in again without a duplicate visit. | R5 |
| No account | Show signup QR; create no association or activation; rescan after signup. | R9 |
| Missing induction | Show training QR; create no association or activation. | R10 |
| Other eligibility denial | Do not grant activation; display the backend decision using the agreed reason mapping. | R2, R4 |
| Replacement card | Verify identity and eligibility; revoke the old UID, move the active visit to the new UID, and confirm. The old card stays refused on later days. A denied attempt must not be presented as successful replacement. | R6 |
| Multiple tools | One visit is recognised across participating tools; a tool denies a student lacking its specific training. Verify with the backend/tool team. | R7 |
| Daily reset | At local midnight, the visit and its registration expire with no job running; the next tap is a check-in that registers again. Revoked cards stay refused. Include dates across daylight-saving changes. | R8 |
| Backend outage / lost response | No false success or offline activation. Verify recovery and uncertain outcomes against the agreed contract. | R11 |
| Reader interruptions and ambiguity | Missing or delayed output, repeats, different arrival orders, and conflicting identifiers cannot create an incorrect association or replacement. | R13 |
| Interrupted UID-first session | Remove card A after its UID is read, then present card B. Never register A's UID to B's student number. Discard expired/cancelled session data and reject stale reader or backend results. A timeout alone does not prove same-card identity. | R13 |
| Reader field command failure | A PN532 field-on or field-off timeout must not produce registration/activation success or silently allow uncertain reader state to continue pairing identifiers. Exercise recovery once its policy is designed. | R11, R13 |
| Hardware coverage | Repeat one-presentation registration across multiple student cards, reader restarts, and back-to-back users. Record successes and failures before accepting the arrangement. | R1, R13 |
| Displays | Verify display 1's prompts, QR flows, success and denial feedback; verify display 2's general instructions and system status without student-specific information. Check offline feedback on both. | R12 |

## 4. Software development life cycle

1. **Requirements gathering — baseline recorded, remaining decisions open.** Review this baseline with makerspace stakeholders and the backend/tool team. Resolve the [open questions](../TODO.md), name acceptance owners, and agree measurable response-time and reliability targets. Exit: approved student-v1 requirements and documented decisions for unresolved flows.
2. **Backend agreement and hardware validation — continue alongside core redesign.** Agree registration, replacement, activation, eligibility, daily expiry, failure, and retry semantics. The UID-first reader arrangement has demonstrated feasibility. Broader hardware testing and same-card correlation remain open; they need not block replacing obsolete lending states and tests, but unresolved misassociation risks block production registration acceptance.
3. **Design.** Define the revised interaction/state model, layouts for the agreed display roles, reader handling, and recovery behaviour from the approved requirements. Review what can be reused from the existing pure state machine and what belongs only to lending. Retain the Python/web UI direction from ADR-0003 where applicable; do not carry forward obsolete motor or return assumptions.
4. **Implementation.** Shane implements the agreed student flows with mentor support unless he explicitly delegates code changes. The core migration in section 7 was explicitly delegated and is implemented. Continue with its integration tasks. The core uses provisional internal backend outcomes; these do not establish an agreed network contract. Historical M1 tasks and old proposed REST paths are not current instructions.
5. **Verification.** Map tests and integration evidence to the acceptance table. Include real-reader trials, backend denial/outage cases, replacement, reset, repeated taps, and mixed-user scans. Tool enforcement and expiry require backend/tool-team participation.
6. **Supervised pilot.** Observe students using the fully self-service flow; routine registration must not require staff to approve or pair cards. Agree duration, monitoring, support, stop/rollback criteria, and sign-off beforehand. Track failures against approved targets before unattended release.

## 5. Dependencies and unresolved decisions

The backend team must provide the authoritative operations and decisions above; endpoint names, payload schemas, authentication, concurrency, and uncertain-outcome recovery are **not agreed**. The kiosk cannot determine access from a UID alone without that integration.

Use the [backend agreement meeting document](backend-agreement.md) with the Backend VP. It compares the reviewed `ops-backend` checkout with the student-card requirements, names the affected routes/services/models, and provides a worksheet for operation guarantees and owners. Confirm the deployed revision and external clients in the meeting.

The OMNIKEY and UID reader must reliably supply the expected identifiers from the same presentation. The observed OMNIKEY output is nine digits followed by Enter; the PN532 returns UID bytes displayed as uppercase hexadecimal, with leading zeros preserved. These observations are not a universal card-format specification. Correlation rules, collision/conflict handling, and broader card compatibility require validation. A successful sequence or short time window does not prove both identifiers came from the same physical card. No mathematical student-number-to-UID conversion has been established. Reading a matching UID from the OMNIKEY as well remains an unverified option, not a requirement or demonstrated capability for these cards.

Display roles and current rendering are described in [display content](display-spec.md). Screens show no student identifiers; production copy, training labels, and backend-owned machine-access details still need agreement.

The [two-reader bring-up guide](reader-testing.md) follows the USB OMNIKEY and SPI-connected PN532 arrangement recorded in section 6, including UID-first RF handover, interruption trials, and unresolved same-card assurance. Use it alongside the current combined Pi script for hardware validation.

The [open-question list](../TODO.md) tracks UID conflicts, lost-card revocation, staff support, privacy and log retention, timing targets, stakeholders, and deferred founder access. The [reader guide](reader-testing.md) records the tested hardware arrangement, not a purchase approval or a complete equipment inventory.

## 6. Reader experiment: evidence and current limitations

- Raspberry Pi 4, Raspberry Pi OS/Debian trixie, Python 3.13.5; development via VS Code Remote SSH.
- Student-number reader: HID OMNIKEY 5427 G2 over USB, detected as OMNIKEY 5427 CK in keyboard mode. Linux input events supply digits and Enter. `/dev/input/event4` was the observed path, not a stable device identity.
- UID reader: Elechouse NFC Module V3 / PN532 over SPI; firmware 1.6 reported and repeated UID reads were stable on the tested card. SPI switch configuration was 1 OFF, 2 ON. Wiring used 3.3 V, ground, SPI MOSI/MISO/SCLK, and software chip select GPIO5 (physical pin 29), not CE0. Python uses Adafruit Blinka and `adafruit-circuitpython-pn532` in a virtual environment, plus `evdev` for the OMNIKEY.
- Simultaneous operation and the student-number-first sequence did not reliably deliver both readings without removing and presenting the card again. This led to trying separated taps, but that is no longer the selected interaction.
- Working reported sequence: enable PN532 RF field, obtain UID, disable PN532 RF field, then obtain the OMNIKEY student number while the card stays presented. The OMNIKEY remains powered and its RF field is not switched by the script. No physical power switching is involved.
- The helper sends PN532 `RFConfiguration` (`0x32`), item `0x01`, with `0x03` for on and `0x02` for off, retaining external-field checking. `0x01`/`0x00` were discussed as alternatives that disable that check; there is no confirmation they became the working configuration. Do not assume this workaround eliminates all RF interaction.
- A three-second pause after the student number was discussed during the experiment. The current probe retains a two-second pause between attempts; neither is a card-removal detector or a production timing requirement. Both entry points discard queued OMNIKEY input before each UID attempt, never after RF-off.
- An intermittent failure was reported after about a minute: field-on received no confirmation, followed by field-off cleanup also receiving no confirmation. Debug logging was suggested. Shane later reported successful one-tap operation, but no root cause or endurance evidence was supplied; do not label this failure fixed.
- The workspace's `tools/student_number_probe.py` is a combined PN532/OMNIKEY diagnostic using the same `read_card_async` path as the controller. Its regression tests are in `tests/test_readers.py`. Preserve any newer, separate Pi experiments before updating their driver logic.
- These probes print identifiers only. No backend registration, replacement, activation, or production integration was demonstrated. Keep actual student identifiers out of committed examples and logs.

## 7. Core migration implemented and next work

Shane explicitly delegated this migration. `kiosk/events.py`, `kiosk/machine.py`, `tests/test_machine.py`, and `tests/test_invariants.py` now implement and test the following internal design. The pure `handle(state, context, event) -> (state, context, effects)` interface is retained. Hardware reads, RF commands, timers, and backend calls remain outside it. Never read `kiosk_test.py`; preserve unrelated work and the gitignored explanation notes.

### Internal transitions

Collect-both routing attempts `ActivateUid` only after a complete `CardRead`. Per [ops-api.md](ops-api.md) it carries the UID and the observed student number. The backend checks the student out if that UID has an active visit (`CHECKED_OUT`); otherwise it returns `UNREGISTERED` and the kiosk continues to registration, which is the everyday check-in. `UNREGISTERED` is a no-write routing result, distinct from `UNKNOWN_STUDENT`.

| Current state | Fact received | Decision |
|---|---|---|
| `IDLE` | Complete valid `CardRead` while both systems are ready | `ACTIVATING`; retain the observed pair separately from verified identity, start the backend session deadline, and request `ActivateUid`. |
| `IDLE` | Incomplete collection (`BadScan` with the current session ID) | `RESULT` with `READ_AGAIN`; no backend operation. |
| `ACTIVATING` | Matching `IdentityConfirmed` arrives early | Hold its verified pair while waiting for the UID decision. |
| `ACTIVATING` | `CHECKED_OUT` | `RESULT`; confirm the check-out. Both reader values were collected before the request started. |
| `ACTIVATING` | `UNREGISTERED` | `AWAITING_IDENTITY`, or immediately `REGISTERING` if the verified pair is already available. |
| `AWAITING_IDENTITY` | Matching `IdentityConfirmed` | `REGISTERING`; request `RegisterAndActivate`. |
| `REGISTERING` | `REGISTERED_AND_ACTIVE` or `REPLACED_AND_ACTIVE` | `RESULT`; success confirms the entire operation, including old-UID invalidation for replacement. |
| Either backend wait | Account, induction, other policy denial, or UID conflict | `RESULT`; retain the outcome/reason code for display 1, clear identifiers, and issue no follow-up write. `ActivateUid` accepts only `DENIED` and `UID_CONFLICT` here; account and induction denials come from registration. |
| `AWAITING_IDENTITY` | Bad/conflicting data or session expiry | `RESULT` with `READ_AGAIN` or `SESSION_EXPIRED`; no registration request. Cancellation instead ends the interaction. |
| Any active interaction | Backend outage or reader fault | Cancel acquisition and clear identifiers. Block on the unavailable system, or enter `OUTCOME_UNKNOWN` if a write could be outstanding. |
| Backend wait | Lost response, cancellation, expiry, or contradictory capture | `OUTCOME_UNKNOWN`; retain the original operation reference without reporting success or retrying. |
| `OUTCOME_UNKNOWN` | Authoritative valid result for the original operation | Clear the pending operation and return to the available resting state. Do not display the departed student's result or continue registration. |
| `RESULT` | Matching result timeout/cancellation | Clear feedback and return to a resting state that respects current backend/reader availability. |

`RESULT` carries an outcome instead of one state per screen. `UNKNOWN_STUDENT` and `MISSING_INDUCTION` render signup/training instructions with explicitly non-scannable placeholders until approved QR URLs exist. Other denial reason mappings and UID-conflict policy remain backend/stakeholder decisions.

### Controller and backend obligations

- Start with `KioskState.OFFLINE` and `Context()`. Both readiness flags default to false. Only emit `BackendOnline` and `ReaderReady(0)` after verifying readiness. During a running interaction, reader health events carry its current session ID. Health messages must describe current verified state, not a delayed command acknowledgement.
- Allocate increasing, non-reused session IDs for completed acquisition attempts only when the machine is idle and ready. Duplicate or conflicting reads within an attempt retain its ID. Discard old buffered input before the next UID acquisition. Shane chose to assume card removal during result feedback rather than detect it; a held card can therefore be processed in another session. The core retains the last ID after cleanup and ignores older scoped events.
- A single `read_card_async` operation owns both devices: discard queued OMNIKEY input before each UID attempt, obtain the UID and RF-off acknowledgement, then parse a complete student number. Never drain after RF-off; the new number may already be buffered. Waiting for a card is separate from the bounded student-number wait. Emit `CardRead` only after both values arrive. Missing/invalid input starts no backend operation. Pre-session failures use the current session ID.
- A `SYN_DROPPED` event during student-number collection means Linux lost input. Abort acquisition with `ReaderFault`; never join digits across that warning. Current recovery requires restarting the reader process, which reopens the device and discards queued input before a fresh attempt.
- `IdentityConfirmed` is a trusted assertion that the UID and student number belong to the same physical card. Correlation tokens and timing do not establish that fact. Its hardware mechanism is still unresolved; the tests supply synthetic confirmed events and are not physical pairing evidence. Do not turn raw OMNIKEY digits into this event merely because a UID was recently read.
- Serialize events through `handle`. Start timers and schedule I/O without blocking it. Execute each backend operation at most once per `(session_id, op)` and echo that reference in results/errors. Readiness loss or cancellation revokes scan admission, including already queued results; shutdown awaits acquisition cleanup before devices close. Rearm only when idle, backend/reader ready, no write remains unresolved, and the previous acquisition has finished cleanup and its queued result has been handled or discarded. Normal result feedback supplies the pause before rearming; the controller prints `Ready for next card.` There is no separate capture effect or card-removal detector. Do not automatically retry writes.
- `RegisterAndActivate` is one logical request for eligible registration or replacement plus activation. Its backend implementation, concurrency semantics, and atomicity are not agreed. Success means the whole operation is confirmed. Denial and `UNREGISTERED` mean no write occurred; partial completion or an unconfirmed outcome must not be mapped to either success or a clean denial.
- `BackendError` defaults to `FailureKind.UNKNOWN`. Use `NOT_SENT` only when the controller knows the request was never sent. Connectivity or reader recovery cannot clear an unresolved operation. A delayed authoritative result can settle the original operation, but obtaining that result when the response is permanently lost still needs a backend recovery contract.
- The core is in memory only. Restart recovery, durable operation references, idempotency across processes, and readiness after a crash remain integration work. A health probe or a restart is not evidence that a previous write was undone. Internal integer session IDs are not a production backend idempotency scheme.
- The controller has separate student-number, backend-session, and feedback durations. The backend-session timer begins only after complete collection and spans activation routing and registration without restarting on phase changes. Timer callbacks carry both session ID and name. No kiosk timer expires registrations or implements the daily access reset.
- Context keeps `observed_student_number` separate from `confirmed_student_number`; only confirmed identity can authorize registration. Terminal decisions clear both and the UID. The display callback receives state, outcome, and actual readiness after acquisition cleanup/rearming. Display 1 receives `state`/`outcome`, including a presentation-only `REARMING` state; display 2 receives only public `status`. Neither receives identifiers or raw backend reasons.

### Next work

1. Agree the actual backend operations, denial mapping, write guarantees, and recovery/retry behavior with the backend/tool team. Keep the core's logical names separate from any eventual endpoint or payload schema.
2. Validate repeated collect-both cycles on the Pi, including different cards, missing numbers, and stale buffered input. Card removal is assumed per Shane's decision; same-card assurance and recovery from RF command failure remain open. The controller uses the shared reader operations with a simulated backend; the combined probe remains a separate diagnostic.
3. Review the implemented dummy displays and finish their production data, approved QR URLs, and help copy; see [display content](display-spec.md). No student-number input or staff approval step is required for routine enrollment.
4. Run the section 3 acceptance scenarios with real readers and the backend. Backend/tool tests must establish old-card invalidation, no duplicate visits, midnight expiry across daylight-saving changes, and tool-specific training enforcement. The core tests verify request/result handling, not those remote behaviors.
5. Run all checks in the [README development instructions](../README.md#development), including controller, reader, startup, and browser tests. Tests cover collection before activation, buffered/handover input, dropped input, invalid and missing numbers, confirmation before/after the backend reply, replacement, denials, repeated input, cancellation, expiry, stale results, mixed identifiers, reader faults, display readiness, and uncertain writes. The invariant sweep uses reachable contexts and verifies coverage of every current state and event type.

This is a starting point for integration and continued development. Backend contract gaps, same-card assurance, timing values, production recovery, and broader hardware validation remain open.
