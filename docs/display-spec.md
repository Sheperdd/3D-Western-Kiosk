# Kiosk display content

Draft for discussion with Shane, 2026-10-08. This defines content and behavior, not an implemented UI. Confirmed: QR screens last 30 seconds; success screens last 10 seconds; neither display shows student identifiers; display 1 shows the student's training level and accessible machines; display 2 includes general makerspace instructions and conduct guidance. Exact copy, other durations, training labels, URLs, and support details remain proposals.

## Display roles

- **Display 1 — current student:** one large instruction or result, one short explanation, training level and accessible machines on successful results, and a QR code when the student must use their phone. The screen is output-only; no buttons or typed input.
- **Display 2 — everyone waiting:** general makerspace instructions, conduct guidance, and kiosk availability. Do not show the current student's identifiers, training level, machine permissions, registration status, denial reason, or signup/training result.

Neither display shows student identifiers: no name, student number (including masked numbers), or physical card UID. Training and machine access are student-specific information, so keep them on display 1 and clear them when the interaction ends.

## Display 1: waiting and processing

| Situation / current state | Heading | Supporting text | When it ends |
|---|---|---|---|
| Starting up | Starting kiosk | Please wait while the kiosk gets ready. | Startup checks finish. This is a presentation distinction from a confirmed outage. |
| Ready / collecting identifiers (`IDLE`, acquisition available or in progress) | Activate your makerspace visit | Hold your student card over the readers until this screen says you can remove it. | Both identifiers arrive, collection expires, or a reader fault occurs. No separate reading-card screen. |
| `ACTIVATING` / minimum checking display time | Checking your access | Card read. You can remove your card now. | Normal result after the minimum checking display time; errors and timeouts interrupt immediately. |
| `AWAITING_IDENTITY` | Checking your card details | You can remove your card. Please wait. | Verified identity, timeout, cancellation, or error. Both raw values have already been collected; this is not a request for another tap. |
| `REGISTERING` | Setting up your card | You can remove your card. Please wait. | Backend result, error, or session timeout. Registration versus replacement is not yet known. |
| Rearming / reader cleanup | Getting ready for the next card | Please wait before presenting another card. | Cleanup is complete, both systems are ready, and no backend outcome is unresolved. |

After both identifiers arrive, send the backend request immediately and show “Checking your access” for a minimum of **2.5 seconds** (the chosen value within Shane's agreed 2–3 seconds). If the response takes longer, show the result as soon as it arrives; do not add another 2.5 seconds. This is a presentation delay, not a delay before sending the request or processing its response.

For a fast normal result, keep the checking screen visible for the remaining minimum time before revealing the result. Begin the full result duration only when the result is presented: 10 seconds for success or 30 seconds for a QR screen. Keep scan admission closed through both periods. Display 2 remains “In use.” Offline, reader faults, cancellation, and unknown-outcome conditions interrupt the wait immediately and discard any obsolete pending display result.

Apply the minimum once per interaction, not once for every backend step in a registration flow. Process identity and registration transitions promptly; their processing screens may replace the initial checking label without restarting the minimum. Show “Remove your card” on each result too.

The current hardware path never emits `IdentityConfirmed`; therefore the eventual registration screens describe the intended verified flow, not a currently working physical registration feature.

## Display 1: result messages

`RESULT` alone does not identify the screen; use its outcome. QR durations are confirmed at 30 seconds and success durations at 10 seconds to allow time to read the training and machine list. Other durations below remain proposals. The current two-second application timer has not been changed.

| Outcome | Heading | Supporting text / action | Duration |
|---|---|---|---|
| `ACTIVATED` | Your visit is active | Remove your card. Your training and machine access are shown below. | 10 seconds; confirmed |
| `ALREADY_ACTIVE` | Your visit is already active | Remove your card. No further check-in is needed. Your training and machine access are shown below. | 10 seconds; confirmed |
| `REGISTERED_AND_ACTIVE` | Card registered. Visit active. | Remove your card. Your training and machine access are shown below. | 10 seconds; confirmed |
| `REPLACED_AND_ACTIVE` | Replacement card activated | Remove your card. Your previous card no longer works for makerspace access. Your training and machine access are shown below. | 10 seconds; confirmed |
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

Use this summary for `ACTIVATED`, `ALREADY_ACTIVE`, `REGISTERED_AND_ACTIVE`, and `REPLACED_AND_ACTIVE`. General induction and tool training remain distinct: the kiosk must not infer a machine list from a numeric level or assume that induction permits every machine. The backend owns that decision, including equipment availability. Exact level names and the response fields still need agreement with the backend team.

Missing information is not an empty permission list. If the level or machine list is unavailable, show “Training level unavailable” or “Machine access details unavailable” for that field; do not guess or reuse the previous student's data. A confirmed empty list shows “No machines currently available to you. Contact the makerspace team for guidance.” A successful visit can still be shown when these optional details are unavailable.

Keep the list readable without touch input. Confirm the machine inventory and screen size before deciding whether it needs grouping or additional pages. Do not silently truncate it or shrink it into unreadable text. Do not show a “Machines you can access” list on denied, incomplete, offline, or uncertain results.

## Display 1: unavailable or uncertain

| State | Heading | Supporting text | Exit condition |
|---|---|---|---|
| `OFFLINE` after startup | Kiosk temporarily unavailable | We can't connect to the access service. Please try later or contact the makerspace team. | Verified backend and reader readiness. |
| `READER_ERROR` | Card reader unavailable | We can't read cards right now. Please contact the makerspace team. | Verified reader recovery and backend readiness. |
| `OUTCOME_UNKNOWN` | Result not confirmed | Remove your card. We couldn't confirm whether your visit was activated. Please contact the makerspace team; don't scan again yet. | An authoritative response resolves the outstanding operation. |

These screens do not auto-clear on a display timer. Do not turn an unknown outcome into “failed,” “success,” or “try again”: a backend write may have completed. If a late response resolves an abandoned interaction, follow the existing core behavior and return to availability without showing that student's old success result.

Support instructions need an agreed contact or route. “Contact the makerspace team” is draft wording; this specification does not assume a staffed desk or invent a phone number.

## Display 2: makerspace instructions and conduct

Use a persistent heading, **Using the makerspace**, with short sections that remain visible independently of the current student's result. Start with a static layout; there is no need for a rotating slideshow unless the agreed content cannot fit legibly.

**Check in**

1. Present your student card to activate your visit.
2. Hold it in place until the other screen says to remove it.
3. Use your card at tools you are trained to use.

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
| Processing (including the minimum checking display time), showing any result, or cleaning up | In use — please wait |
| Offline or reader fault | Kiosk temporarily unavailable |
| Outcome unknown | Kiosk temporarily unavailable |

Display 2 never announces the current student's training level or machine access, or that they lack an account, lack training, have been denied, or have replaced a card. Do not mirror display 1's result text onto it.

## Presentation rules

- Use large readable text, strong contrast, and a clear heading plus action. Use icons alongside text; colour alone must not distinguish success from failure.
- Avoid flashing or progress percentages without measurable progress. A simple waiting indicator is enough.
- Display approved messages for known backend reason codes. Do not render raw exceptions, technical states, arbitrary backend text, or the complete controller context.
- Show no student identifiers. Clear display 1's training and machine-access summary when its result ends or is interrupted. Display 2 receives only general guidance and public status.
- Label a simulated build visibly as **Demo — no real access changes**. The current backend cannot grant an actual visit.

## Implementation gaps to address after content is agreed

1. The core remains `IDLE` while waiting for a card and collecting identifiers. Keep the ready screen through that brief collection; no reader-progress notification or separate reading-card state is needed for the display. Actual scan admission and cleanup still determine when to show ready versus rearming; `state == IDLE` alone is insufficient. There is no physical presence detector.
2. The current controller prints its progress but does not publish a display model. A frontend needs approved display data, not the entire context or terminal output.
3. Every current result uses the same two-second timeout. Implement the 2.5-second minimum checking display time and agreed outcome-specific result durations under controller ownership. Coordinate result presentation, expiry, and rearming so the checking interval does not consume result time, browser refreshes do not restart timers, and cancelled or superseded results never reappear. Do not block the event loop or defer processing backend responses to create the display delay.
4. The current result data does not supply the training level and machine list required by this draft. Agree backend-owned summary fields and their result-only lifetime; clear them on expiry or interruption without retaining student identifiers for display.
5. Backend payloads, QR destinations, support contact, and same-card confirmation remain unresolved. This screen specification does not create those capabilities.

## Decisions awaiting Shane

- Confirm the remaining failure/retry result durations.
- Agree the training-level labels and machine-list content with the backend team.
- Review exact makerspace guidance and contact/support wording with the makerspace team.

No application code or timers have been changed for this draft.
