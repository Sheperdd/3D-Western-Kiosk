# Kiosk display content

**Update, 2026-10-20:** tap-out ([ADR-0006](adr/0006-tap-out-and-daily-registration.md)). The tables below show the **target** copy: check in or out, a `CHECKED_OUT` result, `REGISTERED_AND_ACTIVE` as the everyday check-in, and no `ACTIVATED`/`ALREADY_ACTIVE`. `kiosk/web/app.js` has not been updated yet.

**Implementation update, 2026-10-13:** Both dummy displays render state/outcome messages, public guidance, and connection failures. They show readiness only after reader cleanup and rearming. Success/assistance, QR, and retry result durations are 10, 30, and 6 seconds respectively, owned by the controller. The minimum-display-time proposal below is deferred: the prototype simulates a 2.5-second activation response and keeps registration fast. It publishes results immediately. Training/machine details remain unavailable and QR destinations remain non-scannable placeholders.

The content proposal began on 2026-10-08. Production copy, training labels, URLs, help details, and non-success result durations still need final review. The training and machine-access sections below describe the intended backend-backed display; the current UI labels those details unavailable.

## Display roles

- **Display 1 — current student:** one large instruction or result, one short explanation, training level and accessible machines on successful results, and a QR code when the student must use their phone. The screen is output-only; no buttons or typed input.
- **Display 2 — everyone waiting:** general makerspace instructions, conduct guidance, and kiosk availability. Do not show the current student's identifiers, training level, machine permissions, registration status, denial reason, or signup/training result.

Neither display shows student identifiers: no name, student number (including masked numbers), or physical card UID. Training and machine access are student-specific information, so keep them on display 1 and clear them when the interaction ends.

## Display 1: waiting and processing

| Situation / current state | Heading | Supporting text | When it ends |
|---|---|---|---|
| Starting up | Starting kiosk | Please wait while the kiosk gets ready. | Startup checks finish. This is a presentation distinction from a confirmed outage. |
| Ready / collecting identifiers (`IDLE`, acquisition available or in progress) | Tap your card to check in or out | Hold your student card over the readers until this screen says you can remove it. | Both identifiers arrive, collection expires, or a reader fault occurs. No separate reading-card screen. |
| `ACTIVATING` | Checking your card | Card read. You can remove your card now. | Backend response, error, or timeout. Whether this is a check-in or check-out is not yet known. |
| `AWAITING_IDENTITY` | Checking your card details | You can remove your card. Please wait. | Verified identity, timeout, cancellation, or error. Both raw values have already been collected; this is not a request for another tap. |
| `REGISTERING` | Setting up your card | You can remove your card. Please wait. | Backend result, error, or session timeout. Registration versus replacement is not yet known. |
| `REARMING` (display only) / reader cleanup | Getting ready for the next card | Please wait before presenting another card. | Cleanup is complete, both systems are ready, and no backend outcome is unresolved. |

### Deferred proposal: minimum checking display time

The following presentation delay is not implemented. Current behavior is described in the implementation update above.

After both identifiers arrive, send the backend request immediately and show “Checking your access” for a minimum of **2.5 seconds** (the chosen value within Shane's agreed 2–3 seconds). If the response takes longer, show the result as soon as it arrives; do not add another 2.5 seconds. This is a presentation delay, not a delay before sending the request or processing its response.

For a fast normal result, keep the checking screen visible for the remaining minimum time before revealing the result. Begin the full result duration only when the result is presented: 10 seconds for success or 30 seconds for a QR screen. Keep scan admission closed through both periods. Display 2 remains “In use.” Offline, reader faults, cancellation, and unknown-outcome conditions interrupt the wait immediately and discard any obsolete pending display result.

Apply the minimum once per interaction, not once for every backend step in a registration flow. Process identity and registration transitions promptly; their processing screens may replace the initial checking label without restarting the minimum. Show “Remove your card” on each result too.

The current hardware path never emits `IdentityConfirmed`; therefore the eventual registration screens describe the intended verified flow, not a currently working physical registration feature.

## Display 1: result messages

`RESULT` alone does not identify the screen; use its outcome. The table gives the implemented durations: QR screens use 30 seconds, success/assistance screens 10 seconds, and retries 6 seconds. Production review of failure/retry timings remains open.

| Outcome | Heading | Supporting text / action | Duration |
|---|---|---|---|
| `REGISTERED_AND_ACTIVE` | You're checked in | Remove your card. Your training and machine access are shown below. Tap again when you leave. | 10 seconds; confirmed |
| `REPLACED_AND_ACTIVE` | Replacement card activated | Remove your card. Your previous card no longer works for makerspace access. Your training and machine access are shown below. | 10 seconds; confirmed |
| `CHECKED_OUT` | You're checked out | Remove your card. Tap again to check back in. No training or machine details. | 6 seconds; proposed, tune on the monitor |
| `UNKNOWN_STUDENT` | Create your makerspace account | Remove your card. Scan the QR code with your phone to sign up, then return and present your card again. | 30 seconds; confirmed |
| `MISSING_INDUCTION` | General induction required | Remove your card. Scan the QR code for training instructions. Return after your training has been recorded. | 30 seconds; confirmed |
| `DENIED` | Unable to activate your visit | Remove your card. Contact the makerspace team for help. An approved reason may replace this generic explanation. | 10 seconds |
| `UID_CONFLICT` | This card needs assistance | Remove your card. Contact the makerspace team to resolve the card registration. | 10 seconds |
| `READ_AGAIN` | We couldn't read your card completely | Remove your card. Wait for the ready screen, then hold it over the readers again. | 6 seconds |
| `SESSION_EXPIRED` | We couldn't complete this attempt | Remove your card. Wait for the ready screen, then try again. If this repeats, contact the makerspace team. | 6 seconds |

`UNREGISTERED` is an internal routing result, not a student-facing failure screen. It leads to identity verification and registration when supported.

For each QR screen, show a descriptive label (“Create an account” or “General induction”) and the approved short URL as an alternative. QR codes point to approved account/training pages; do not put card identifiers into their URLs. Destination URLs are still unconfirmed. Never display a placeholder QR as though it works.

Result screens finish automatically; the next scan starts only after the controller admits it. Under the current interaction model a QR screen occupies the kiosk for its entire duration. There is no touch-to-dismiss or scan-to-dismiss behavior. Card removal is assumed, so keeping a card on the readers can start another attempt once the result expires.

### Training and machine access on successful results

Below the result heading and remove-card instruction, show:

- **Your training level:** the backend-confirmed level using the makerspace's agreed label.
- **Machines you can access:** a readable list of machine names the backend confirms this student may currently access.
- **Reminder:** Follow each machine's operating instructions. Access is checked again at the machine.

Use this summary for `REGISTERED_AND_ACTIVE` and `REPLACED_AND_ACTIVE`. Never show it for `CHECKED_OUT`; the student no longer has access. General induction and tool training remain distinct: the kiosk must not infer a machine list from a numeric level or assume that induction permits every machine. The backend owns that decision, including equipment availability. Exact level names and the response fields still need agreement with the backend team.

Missing information is not an empty permission list. If the level or machine list is unavailable, show “Training level unavailable” or “Machine access details unavailable” for that field; do not guess or reuse the previous student's data. A confirmed empty list shows “No machines currently available to you. Contact the makerspace team for guidance.” A successful visit can still be shown when these optional details are unavailable.

Keep the list readable without touch input. Confirm the machine inventory and screen size before deciding whether it needs grouping or additional pages. Do not silently truncate it or shrink it into unreadable text. Do not show a “Machines you can access” list on denied, incomplete, offline, or uncertain results.

## Display 1: unavailable or uncertain

| State | Heading | Supporting text | Exit condition |
|---|---|---|---|
| `OFFLINE` after startup | Kiosk temporarily unavailable | We can't connect to the access service. Please try later or contact the makerspace team. | Verified backend and reader readiness. |
| `READER_ERROR` | Card reader unavailable | We can't read cards right now. Please contact the makerspace team. | Verified reader recovery and backend readiness. |
| `OUTCOME_UNKNOWN` | Result not confirmed | Remove your card. We couldn't confirm your check-in or check-out. Please contact the makerspace team; don't scan again yet. | An authoritative response resolves the outstanding operation. |

These screens do not auto-clear on a display timer. Do not turn an unknown outcome into “failed,” “success,” or “try again”: a backend write may have completed. If a late response resolves an abandoned interaction, follow the existing core behavior and return to availability without showing that student's old success result.

Support instructions need an agreed contact or route. “Contact the makerspace team” is draft wording; this specification does not assume a staffed desk or invent a phone number.

## Display 2: makerspace instructions and conduct

Use a persistent heading, **Using the makerspace**, with short sections that remain visible independently of the current student's result. Start with a static layout; there is no need for a rotating slideshow unless the agreed content cannot fit legibly.

**Check in and out**

1. Present your student card to check in.
2. Hold it in place until the other screen says to remove it.
3. Use your card at tools you are trained to use.
4. Tap your card again when you leave to check out.

**Work responsibly**

- Use only machines you are trained and authorised to use.
- Follow posted machine instructions and required protective-equipment rules.
- Ask the makerspace team if you are unsure how to proceed.
- Use your own card; do not lend it to someone else.

**Share the space**

- Respect other users and give people room to work.
- Keep walkways and shared work areas clear.
- Clean your workspace and return shared tools when finished.
- Report damaged equipment or unsafe conditions to the makerspace team.

These are proposed general messages for the makerspace team to review, not a replacement for machine training or local safety procedures. Add approved help/contact details and any local booking, material, or cleanup rules once supplied; do not invent them.

A small, persistent availability area changes with the interaction while the general guidance stays visible:

| Kiosk situation | Public status |
|---|---|
| Startup | Starting up — please wait |
| Ready / brief identifier collection before a complete pair | Ready for the next student |
| Processing, showing any result, or cleaning up | In use — please wait |
| Offline or reader fault | Kiosk temporarily unavailable |
| Outcome unknown | Kiosk temporarily unavailable |

The "In use" message reads "Give the person checking in or out space. Wait for the ready message."

Display 2 never announces the current student's training level or machine access, whether they checked in or out, or that they lack an account, lack training, have been denied, or have replaced a card. Do not mirror display 1's result text onto it.

## Presentation rules

- Use large readable text, strong contrast, and a clear heading plus action. Use icons alongside text; colour alone must not distinguish success from failure.
- Avoid flashing or progress percentages without measurable progress. A simple waiting indicator is enough.
- Display approved messages for known backend reason codes. Do not render raw exceptions, technical states, arbitrary backend text, or the complete controller context.
- Show no student identifiers. Clear display 1's training and machine-access summary when its result ends or is interrupted. Display 2 receives only general guidance and public status.
- Label a simulated build visibly as **Demo — no real access changes**. The current backend cannot grant an actual visit.

## Display data and remaining work

The controller publishes state, outcome, and actual readiness after cleanup/rearming. The core remains `IDLE` through brief identifier collection; when it is idle but acquisition is unavailable, the student display uses `REARMING` and the public display stays “In use.” This adds no core state or physical presence detector.

`/api/display/1` returns `state` and nullable `outcome`; `/api/display/2` returns only `status`. No positional label arrays, student identifiers, or raw backend reasons are sent. Browser refreshes do not restart controller timers.

Remaining integration work is the backend-owned training/machine summary, approved QR destinations, support contact, and same-card confirmation. Clear any future summary fields on expiry or interruption. The minimum checking display delay remains deferred.

## Decisions awaiting Shane

- Confirm the remaining failure/retry result durations.
- Agree the training-level labels and machine-list content with the backend team.
- Review exact makerspace guidance and contact/support wording with the makerspace team.
