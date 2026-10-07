# Student-card kiosk — Requirements and SDLC plan

Updated 2026-10-07 for collect-both-before-backend ordering. **Current phase: the controller collects both identifiers before simulated backend processing; real backend integration and broader reader validation remain open.** This replaces the card-lending implementation plan. The requirements below describe the intended student-only v1; core test coverage is not evidence that the integrated kiosk is delivered.

## 1. Purpose, scope, and current state

Students register their existing student cards and activate daily access to participating makerspace tools. They do not borrow a second card. Registration associates a card UID with a student number; activation grants a temporary visit. These are separate concepts.

The project delivers the kiosk and agrees its interface with the backend team. The backend/tool team owns accounts, training, eligibility policy, persistent card associations, visit records, daily expiry, and tool access enforcement. The kiosk neither controls tool power nor unlocks entrance doors.

V1 serves students only. Founder enrolment and access require a later requirements discussion; earlier ideas about personal founder RFID cards and backend provisioning remain provisional. Card dispensing, returns, iris and drawer motors, stock tracking, non-return flags, and the unlink outbox are outside current v1. Occupancy counting remains deferred.

The events, pure state machine, and core tests in `kiosk/` and `tests/` now model the student-card flows described in section 7. Motor, stock, return, and temporary-link behavior has been removed from that core. The controller and shared hardware reader operations support repeated scans after result feedback and cleanup, assuming students take their cards back. The backend is simulated; verified same-card identity and displays remain open. The old [M1 roadmap](m1-roadmap.md) is historical, not the next work queue. [ADR-0005](adr/0005-student-card-registration-and-daily-activation.md) records the scope change.

## 2. Confirmed requirements

| ID | Requirement |
|---|---|
| R1 | Registration is fully self-service and uses one physical student-card presentation. The PN532 first reads the hexadecimal UID; its RF field is then disabled so the OMNIKEY can read the student number. Both identifiers refer to the student's existing card, not a separate loan card. |
| R2 | Before registering a UID, the backend must confirm an existing account, completed general induction, and eligibility under its access policy. The backend owns additional restrictions and supplies the denial reason. |
| R3 | Successful registration also activates the visit. The kiosk displays success only after backend confirmation of activation. |
| R4 | Every kiosk presentation, including a returning visit, must supply both the UID and student number before backend processing starts. The backend resolves the registered card and checks current eligibility before activation. Tool readers are unchanged. |
| R5 | An eligible student whose visit is already active receives an “already active” confirmation. Repeated taps do not end the visit or remove registration. |
| R6 | A replacement student card is registered automatically after successful identification and eligibility checks. It replaces the previous UID association, invalidates the old card's access, and activates the replacement in the same interaction. |
| R7 | One activation is recognised across all participating tools without separate makerspace check-ins. Each tool still enforces its own training requirements. General induction does not grant permission to use every tool. |
| R8 | The backend expires activations at 00:00 America/Toronto each day, following local daylight-saving changes. Registration persists. This is a daily reset, not an opening-hours restriction; eligible students may immediately reactivate. |
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
| Returning student | One presentation supplies both identifiers before eligibility/activation processing. Missing either identifier starts no backend operation. | R4 |
| Already-active student / repeated taps | Confirm the eligible active visit without checkout, unlinking, or duplicate visit creation. | R5 |
| No account | Show signup QR; create no association or activation; rescan after signup. | R9 |
| Missing induction | Show training QR; create no association or activation. | R10 |
| Other eligibility denial | Do not grant activation; display the backend decision using the agreed reason mapping. | R2, R4 |
| Replacement card | Verify identity and eligibility; invalidate the old UID, register the new UID, and confirm activation. A denied attempt must not be presented as successful replacement. | R6 |
| Multiple tools | One visit is recognised across participating tools; a tool denies a student lacking its specific training. Verify with the backend/tool team. | R7 |
| Daily reset | At local midnight, activation expires but registration remains; a subsequent eligible tap reactivates. Include dates across daylight-saving changes. | R8 |
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

Display roles are agreed for now: current-student interaction on display 1; general instructions/system status on display 2. Detailed layouts and permitted student information on display 1 remain design/privacy decisions.

The [two-reader bring-up guide](reader-testing.md) follows the USB OMNIKEY and SPI-connected PN532 arrangement recorded in section 6, including UID-first RF handover, interruption trials, and unresolved same-card assurance. Use it alongside the current combined Pi script for hardware validation.

The [open-question list](../TODO.md) tracks UID conflicts, lost-card revocation, staff support, privacy and log retention, timing targets, stakeholders, and deferred founder access. Hardware planning is in the [buylist](buylist.txt); it is not a purchase approval or an inventory of equipment already owned.

## 6. Reader experiment: evidence and current limitations

- Raspberry Pi 4, Raspberry Pi OS/Debian trixie, Python 3.13.5; development via VS Code Remote SSH.
- Student-number reader: HID OMNIKEY 5427 G2 over USB, detected as OMNIKEY 5427 CK in keyboard mode. Linux input events supply digits and Enter. `/dev/input/event4` was the observed path, not a stable device identity.
- UID reader: Elechouse NFC Module V3 / PN532 over SPI; firmware 1.6 reported and repeated UID reads were stable on the tested card. SPI switch configuration was 1 OFF, 2 ON. Wiring used 3.3 V, ground, SPI MOSI/MISO/SCLK, and software chip select GPIO5 (physical pin 29), not CE0. Python uses Adafruit Blinka and `adafruit-circuitpython-pn532` in a virtual environment, plus `evdev` for the OMNIKEY.
- Simultaneous operation and the student-number-first sequence did not reliably deliver both readings without removing and presenting the card again. This led to trying separated taps, but that is no longer the selected interaction.
- Working reported sequence: enable PN532 RF field, obtain UID, disable PN532 RF field, then obtain the OMNIKEY student number while the card stays presented. The OMNIKEY remains powered and its RF field is not switched by the script. No physical power switching is involved.
- The helper sends PN532 `RFConfiguration` (`0x32`), item `0x01`, with `0x03` for on and `0x02` for off, retaining external-field checking. `0x01`/`0x00` were discussed as alternatives that disable that check; there is no confirmation they became the working configuration. Do not assume this workaround eliminates all RF interaction.
- A three-second pause after the student number was discussed for the diagnostic loop. It is not a card-removal detector or an agreed production timing requirement. The probe discards queued OMNIKEY input before waiting for a fresh student scan; production handling of buffered input still needs design.
- An intermittent failure was reported after about a minute: field-on received no confirmation, followed by field-off cleanup also receiving no confirmation. Debug logging was suggested. Shane later reported successful one-tap operation, but no root cause or endurance evidence was supplied; do not label this failure fixed.
- The combined experiment runs on the Pi. The workspace's `tools/student_number_probe.py` remains the simplified OMNIKEY-only script with tests in `tools/test_student_number_probe.py`. Do not mistake it for the final combined Pi script or overwrite Shane's Pi changes. Obtain the current Pi file before adapting its driver logic.
- These probes print identifiers only. No backend registration, replacement, activation, or production integration was demonstrated. Keep actual student identifiers out of committed examples and logs.

## 7. Core migration implemented and next work

Shane explicitly delegated this migration. `kiosk/events.py`, `kiosk/machine.py`, `tests/test_machine.py`, and `tests/test_invariants.py` now implement and test the following internal design. The pure `handle(state, context, event) -> (state, context, effects)` interface is retained. Hardware reads, RF commands, timers, and backend calls remain outside it. Never read `kiosk_test.py`; preserve unrelated work and the gitignored explanation notes.

### Internal transitions

Collect-both routing attempts `ActivateUid` only after a complete `CardRead`. Its payload remains a UID; the ordering change does not establish a network schema. The backend must resolve the registered holder, check current eligibility, and activate or confirm an already-active visit. `UNREGISTERED` is a no-write routing result, distinct from `UNKNOWN_STUDENT`.

| Current state | Fact received | Decision |
|---|---|---|
| `IDLE` | Complete valid `CardRead` while both systems are ready | `ACTIVATING`; retain the observed pair separately from verified identity, start the backend session deadline, and request `ActivateUid`. |
| `IDLE` | Incomplete collection (`BadScan` with the current session ID) | `RESULT` with `READ_AGAIN`; no backend operation. |
| `ACTIVATING` | Matching `IdentityConfirmed` arrives early | Hold its verified pair while waiting for the UID decision. |
| `ACTIVATING` | `ACTIVATED` or `ALREADY_ACTIVE` | `RESULT`; confirm the backend outcome. Both reader values were collected before activation started. |
| `ACTIVATING` | `UNREGISTERED` | `AWAITING_IDENTITY`, or immediately `REGISTERING` if the verified pair is already available. |
| `AWAITING_IDENTITY` | Matching `IdentityConfirmed` | `REGISTERING`; request `RegisterAndActivate`. |
| `REGISTERING` | `REGISTERED_AND_ACTIVE` or `REPLACED_AND_ACTIVE` | `RESULT`; success confirms the entire operation, including old-UID invalidation for replacement. |
| Either backend wait | Account, induction, other policy denial, or UID conflict | `RESULT`; retain the outcome/reason code for display 1, clear identifiers, and issue no follow-up write. |
| `AWAITING_IDENTITY` | Bad/conflicting data or session expiry | `RESULT` with `READ_AGAIN` or `SESSION_EXPIRED`; no registration request. Cancellation instead ends the interaction. |
| Any active interaction | Backend outage or reader fault | Cancel acquisition and clear identifiers. Block on the unavailable system, or enter `OUTCOME_UNKNOWN` if a write could be outstanding. |
| Backend wait | Lost response, cancellation, expiry, or contradictory capture | `OUTCOME_UNKNOWN`; retain the original operation reference without reporting success or retrying. |
| `OUTCOME_UNKNOWN` | Authoritative valid result for the original operation | Clear the pending operation and return to the available resting state. Do not display the departed student's result or continue registration. |
| `RESULT` | Matching result timeout/cancellation | Clear feedback and return to a resting state that respects current backend/reader availability. |

`RESULT` carries an outcome instead of one state per screen. `UNKNOWN_STUDENT` selects the account-signup QR and `MISSING_INDUCTION` selects the training QR; QR URLs and display rendering are not implemented. Other denial reason mappings and UID-conflict policy remain backend/stakeholder decisions.

### Controller and backend obligations

- Start with `KioskState.OFFLINE` and `Context()`. Both readiness flags default to false. Only emit `BackendOnline` and `ReaderReady(0)` after verifying readiness. During a running interaction, reader health events carry its current session ID. Health messages must describe current verified state, not a delayed command acknowledgement.
- Allocate increasing, non-reused session IDs for completed acquisition attempts only when the machine is idle and ready. Duplicate or conflicting reads within an attempt retain its ID. Discard old buffered input before the next UID acquisition. Shane chose to assume card removal during result feedback rather than detect it; a held card can therefore be processed in another session. The core retains the last ID after cleanup and ignores older scoped events.
- A single `read_card_async` operation owns both devices: discard queued OMNIKEY input before each UID attempt, obtain the UID and RF-off acknowledgement, then parse a complete student number. Never drain after RF-off; the new number may already be buffered. Waiting for a card is separate from the bounded student-number wait. Emit `CardRead` only after both values arrive. Missing/invalid input starts no backend operation. Pre-session failures use the current session ID.
- `IdentityConfirmed` is a trusted assertion that the UID and student number belong to the same physical card. Correlation tokens and timing do not establish that fact. Its hardware mechanism is still unresolved; the tests supply synthetic confirmed events and are not physical pairing evidence. Do not turn raw OMNIKEY digits into this event merely because a UID was recently read.
- Serialize events through `handle`. Start timers and schedule I/O without blocking it. Execute each backend operation at most once per `(session_id, op)` and echo that reference in results/errors. Readiness loss or cancellation revokes scan admission, including already queued results; shutdown awaits acquisition cleanup before devices close. Rearm only when idle, backend/reader ready, no write remains unresolved, and the previous acquisition has finished cleanup and its queued result has been handled or discarded. Normal result feedback supplies the pause before rearming; the controller prints `Ready for next card.` There is no separate capture effect or card-removal detector. Do not automatically retry writes.
- `RegisterAndActivate` is one logical request for eligible registration or replacement plus activation. Its backend implementation, concurrency semantics, and atomicity are not agreed. Success means the whole operation is confirmed. Denial and `UNREGISTERED` mean no write occurred; partial completion or an unconfirmed outcome must not be mapped to either success or a clean denial.
- `BackendError` defaults to `FailureKind.UNKNOWN`. Use `NOT_SENT` only when the controller knows the request was never sent. Connectivity or reader recovery cannot clear an unresolved operation. A delayed authoritative result can settle the original operation, but obtaining that result when the response is permanently lost still needs a backend recovery contract.
- The core is in memory only. Restart recovery, durable operation references, idempotency across processes, and readiness after a crash remain integration work. A health probe or a restart is not evidence that a previous write was undone. Internal integer session IDs are not a production backend idempotency scheme.
- The controller has separate student-number, backend-session, and feedback durations. The backend-session timer begins only after complete collection and spans activation routing and registration without restarting on phase changes. Timer callbacks carry both session ID and name. No kiosk timer expires registrations or implements the daily access reset.
- Context holds current-student information only while needed; terminal decisions clear UID and student number. Display 1 can consume approved feedback. Display 2 must use general instructions and system health only, never serialize the entire context or raw backend reason content. Detailed UI/privacy rules remain open.

### Next work

1. Agree the actual backend operations, denial mapping, write guarantees, and recovery/retry behavior with the backend/tool team. Keep the core's logical names separate from any eventual endpoint or payload schema.
2. Validate repeated collect-both cycles on the Pi, including different cards, missing numbers, and stale buffered input. Card removal is assumed per Shane's decision; same-card assurance and recovery from RF command failure remain open. The controller uses the shared reader operations with a simulated backend; the combined probe remains a separate diagnostic.
3. Build the two displays around their agreed roles, including signup/training QR codes, backend denials, offline status, reader faults, and unknown outcomes. No student-number input or staff approval step is required for routine enrollment.
4. Run the section 3 acceptance scenarios with real readers and the backend. Backend/tool tests must establish old-card invalidation, no duplicate visits, midnight expiry across daylight-saving changes, and tool-specific training enforcement. The core tests verify request/result handling, not those remote behaviors.
5. Use the focused pytest suite plus Ruff and Pyright as the core development baseline. Tests cover collection before activation, buffered/handover input, invalid and missing numbers, confirmation before/after the backend reply, replacement, denials, repeated input, cancellation, expiry, stale results, mixed identifiers, reader faults, and uncertain writes. The invariant sweep uses reachable contexts and verifies coverage of every current state and event type.

This is a starting point for integration and continued development. Backend contract gaps, same-card assurance, timing values, production recovery, and broader hardware validation remain open.
