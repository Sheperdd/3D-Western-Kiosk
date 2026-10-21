# Student-card kiosk — Requirements and SDLC plan

**Update, 2026-10-21 (gatekeeper):** the kiosk now talks to the access gatekeeper on the makerspace PC with one tap call ([ADR-0007](adr/0007-kiosk-talks-to-gatekeeper.md), [kiosk-api.md](kiosk-api.md)). Sections 1-3 and 5 are rewritten for it. Section 7 still describes the pre-gatekeeper core and is replaced in phase 2 of the [integration plan](gatekeeper-integration-plan.md).

**Update, 2026-10-21:** the check-in/check-out flow from [ADR-0006](adr/0006-tap-out-and-daily-registration.md) is implemented in the core, fake backend, dummy displays, and tests. The section 7 transition table describes the current core; `CHECKED_OUT` replaces `ACTIVATED`/`ALREADY_ACTIVE`. Real backend integration, midnight expiry, and same-card verification remain pending.

Updated 2026-10-13 for reader fault handling, display readiness, and shared diagnostics. **Current phase: the controller collects both identifiers before simulated backend processing; real backend integration and broader reader validation remain open.** This replaces the card-lending implementation plan. The requirements below describe the intended student-only v1; core test coverage is not evidence that the integrated kiosk is delivered.

## 1. Purpose, scope, and current state

Students tap their existing student cards to check in to and out of the makerspace, which grants access to machine stations while they are checked in. They do not borrow a second card. Each tap goes to the access gatekeeper, which links the card to the student number (permanently), checks orientation, and opens or closes the visit; the nightly reset closes visits left open.

The project delivers the kiosk against the gatekeeper's kiosk API. The platform (main backend and gatekeeper) owns accounts, orientation, certifications, card links, visit records, the nightly reset, and station enforcement. The kiosk neither controls machine power nor unlocks entrance doors.

V1 serves students only. Founder enrolment and access require a later requirements discussion; earlier ideas about personal founder RFID cards and backend provisioning remain provisional. Card dispensing, returns, iris and drawer motors, stock tracking, non-return flags, and the unlink outbox are outside current v1. Occupancy counting remains deferred.

The events, pure state machine, and tests in `kiosk/` and `tests/` model the student-card flows described in section 7. Motor, stock, return, and temporary-link behavior has been removed. The controller and shared readers support repeated scans after result feedback and cleanup, assuming students take their cards back. Both dummy displays render current state and availability. The backend is simulated; verified same-card identity and production integration remain open. [ADR-0005](adr/0005-student-card-registration-and-daily-activation.md) records the scope change.

## 2. Confirmed requirements

| ID | Requirement |
|---|---|
| R1 | Check-in is fully self-service and uses one physical student-card presentation. The PN532 first reads the hexadecimal UID; its RF field is then disabled so the OMNIKEY can read the student number. Both identifiers refer to the student's existing card, not a separate loan card. |
| R2 | The gatekeeper decides check-in: an existing account that is active, a verified email, and usable orientation (staff included). It supplies the result, the reason code, and the wording. |
| R3 | The kiosk displays a check-in or check-out only after the gatekeeper answers `CHECKED_IN` or `CHECKED_OUT`. |
| R4 | Every kiosk presentation must supply both the UID and the student number before anything is sent. The kiosk sends exactly one tap per presentation (`POST /v1/kiosk/tap`, number as an integer, `X-Device-Key` header). Stations are unchanged by the kiosk. |
| R5 | A tap by a student with an open visit checks them out, whichever of their cards was used; check-out needs no eligibility check. A later tap checks in again. The gatekeeper ignores the same card on the same kiosk within `tapDebounceSeconds` (default 3 s, `IGNORED_DUPLICATE`); the kiosk shows that answer's message again. A card held longer than that still toggles (accepted for now; card-removal detection is follow-up work). |
| R6 | A new or replacement card is linked automatically by its first accepted tap. Older cards stay linked; the kiosk revokes nothing. Lost-card blocking is an admin and platform matter (not yet enforced at the kiosk, see ADR-0007). |
| R7 | One open visit is recognised by every station. Each station still checks the certifications its machine requires; orientation does not grant use of every machine. |
| R8 | The gatekeeper closes visits still open at its nightly reset (`nightlyResetTime`, default 03:00 America/Toronto). Card links are permanent; there is no daily UID wipe. The reset is not an opening-hours restriction; students may check in again immediately. |
| R9 | `DENIED` with `UNKNOWN_STUDENT` shows the account-signup QR with the gatekeeper's message. The student signs up and taps again. |
| R10 | `DENIED` with `ORIENTATION_REQUIRED` shows the orientation QR with the gatekeeper's message. `ORIENTATION_NOT_CONFIGURED` and every other reason show the message without a QR. |
| R11 | If the gatekeeper is unreachable or has not synced yet (`/healthz` without `hasSnapshot: true`), refuse taps and show an offline or starting-up message. Never report success without a `200` result. A tap with no reply is resent once immediately; after that the kiosk shows "Couldn't reach the system, please tap again" and returns to ready. |
| R12 | Retain two output-only displays. Display 1 guides the current student: prompts, QR codes, the gatekeeper's message and notices, and the student's first name. Display 2 shows general instructions and system status without personal information. |
| R13 | Incomplete, delayed, repeated, or conflicting reader output must never send one student's number with another card's UID. The gatekeeper relinks a UID to whatever number it receives, so the kiosk is the only guard. The mechanism for reliably correlating readings is not yet decided. |

Shane reports the UID-first arrangement works with one presentation. This is evidence of feasibility, not completed multi-card, endurance, or misassociation testing. See section 6 for the experiment and its limits.

## 3. Acceptance criteria

These are acceptance scenarios for the integrated system. The revised core suite covers its transition decisions for these flows; hardware, backend, and display evidence is still required where indicated.

| Scenario | Required outcome | Requirements |
|---|---|---|
| First check-in with a new card | One presentation yields both identifiers; the gatekeeper answers `CHECKED_IN` with `cardLinked: true`; display 1 shows its message. | R1–R3 |
| Check-in | One presentation supplies both identifiers before any request. Missing either identifier sends nothing. A student with no open visit who passes the checks is checked in. | R4 |
| Check-out | A tap by a student with an open visit ends it; stations then refuse their card. A suspended student or a main-backend outage does not block check-out. A following tap checks in again. | R5 |
| Repeat within the debounce | The same card tapped again within 3 s gets `IGNORED_DUPLICATE`; display 1 keeps showing the first answer's message; nothing toggles. | R5 |
| No account | `UNKNOWN_STUDENT`: show the signup QR and message; tap again after signup. | R9 |
| Missing orientation | `ORIENTATION_REQUIRED`: show the orientation QR and message. `ORIENTATION_NOT_CONFIGURED`: message only. | R10 |
| Other denial | `EMAIL_NOT_VERIFIED`, `ACCOUNT_SUSPENDED`, `ACCOUNT_BANNED`, `DATA_STALE` or an unknown reason: no check-in; show the gatekeeper's message. | R2, R4 |
| Replacement card | A student's new card checks them in and is linked; their old card still works until an admin deactivates it. | R6 |
| Multiple machines | One visit is recognised at every station; a station denies a student lacking its machine's certifications. Verify with the platform team. | R7 |
| Nightly reset | A visit still open at `nightlyResetTime` is closed; the next tap is a check-in. A visit left open past the reset is closed as "forgot" at the next tap. | R8 |
| Gatekeeper outage / lost reply | No false success. Unsynced gatekeeper → starting-up screen. No reply → one immediate resend, then "please tap again". Wrong key (`401`) → "Kiosk not set up". Bad request (`422`) → read again. | R11 |
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

The interface is the gatekeeper's kiosk API: [kiosk-api.md](kiosk-api.md), bound by the platform's [gatekeeper contract](../../makerspace-platform/docs/specs/gatekeeper-contract.md) §1.1 and §4. The kiosk needs a registered `KIOSK` device key and a network path to the gatekeeper on the private reader network. Work order: [gatekeeper-integration-plan.md](gatekeeper-integration-plan.md).

Still open on the platform side (need Troy): refusing a UID already linked to another student (`CARD_CONFLICT`), and keeping deactivated (lost) cards blocked at the kiosk. The [ops backend agreement](backend-agreement.md) and [ops-api.md](ops-api.md) are historical.

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

> **Pre-gatekeeper core, 2026-10-21:** this section describes the two-operation core built for ops-api.md (`ActivateUid`, `RegisterAndActivate`, `IdentityConfirmed`, `OUTCOME_UNKNOWN`). Phase 2 of the [integration plan](gatekeeper-integration-plan.md) collapses it to one tap; rewrite this section then.

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
- Serialize events through `handle`. Start timers and schedule I/O without blocking it. Execute each backend operation at most once per `(tap_id, op)` and echo that reference in results/errors. Readiness loss or cancellation revokes scan admission, including already queued results; shutdown awaits acquisition cleanup before devices close. Rearm only when idle, backend/reader ready, no write remains unresolved, and the previous acquisition has finished cleanup and its queued result has been handled or discarded. Normal result feedback supplies the pause before rearming; the controller prints `Ready for next card.` There is no separate capture effect or card-removal detector. Do not automatically retry writes.
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
