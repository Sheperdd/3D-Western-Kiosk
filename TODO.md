# Open requirements and decisions

Updated 2026-10-19. The agreed baseline is [docs/plan.md](docs/plan.md). These items are unresolved, not permission to invent defaults during implementation.

## Resolve for student v1

- **Display details — Shane / makerspace stakeholders:** review the implemented dummy screens on the actual monitors. Confirm production copy, help contacts, QR destinations, training labels, and backend-provided machine access; see [display content](docs/display-spec.md).
- **Reader correlation — kiosk and hardware teams:** establish how the student-number and UID readings are proven to belong to the same presentation. Cover missing/delayed output, arrival order, repeat reads, disconnects, back-to-back users, and both readers firing during a repeat visit. Temporal proximity alone is not an agreed solution. Investigation is deferred for now; see [the options and next experiment](#same-card-identity-options--investigation-deferred).
- **Hardware evidence — hardware team:** expand the one-card trial to multiple student cards and repeated presentations. Record reader models/settings, identifier formats, consistency across restarts, and compatibility with tool readers. Decide what evidence meets the reliability target.
- **Backend contract — backend/tool team and Shane:** agree operations and responses for eligibility, registration plus activation, replacement plus activation, already-active visits, and daily expiry. Define authentication, denial reasons, conflicts, concurrency, retries, partial completion, and recovery when a response is lost. No endpoint paths or payload schemas are agreed yet.
- **UID conflict — backend team / stakeholders:** decide what happens when a scanned UID is already registered to a different account. Automatic replacement of one's own old card does not settle cross-account conflicts.
- **Replacement and revocation — backend/tool team / stakeholders:** agree how lost cards are revoked before replacement and how invalidation propagates to tools. Define handling of existing activation during replacement and eligibility changes during an active visit. Midnight expiry behaviour for a tool already in use belongs to the tool team and needs agreement.
- **Support and recovery — makerspace operators:** define staff assistance, unreadable/forgotten-card guidance, reader/backend outage handling, restart recovery, escalation channels, and authorised servicing. Loaner-card dispensing is not part of current v1.
- **Privacy and records — stakeholders / backend team:** screens show no student identifiers. Agree diagnostic logging, local retention, retention periods, and who may access records. No local identity database or offline eligibility cache is assumed.
- **Targets and acceptance — stakeholders and delivery teams:** name who approves requirements and signs off the pilot; agree response times, scan reliability, accessibility/usability criteria, pilot duration, monitoring, support, and stop/rollback criteria.
- **Deployment — kiosk/hardware team and campus IT:** confirm available Pi equipment, display/enclosure arrangement, network access, and servicing arrangements. Carry forward applicable appliance/recovery constraints during design; old provisioning details are not a new approved deployment specification.

## Same-card identity options — investigation deferred

**2026-10-19 decision:** Shane is deferring this investigation to continue other kiosk work toward Friday, 2026-10-23. No approach below has been selected or validated. The pairing issue remains unresolved; this scheduling decision does not establish same-card evidence or change the current requirement for verified identity before registration/replacement.

The current sequence observes a UID from the PN532 followed by a student number from the OMNIKEY. Their arrival in the same session, or close together in time, does not prove that they came from the same physical card. Card A could supply the UID and card B the student number.

### Options to investigate, in recommended order

1. **Read both values through the OMNIKEY in one card operation.** HID documents configurable keyboard output containing multiple data fields, including a CSN [card serial number] and card data. Investigate whether the actual student cards and reader configuration expose the required UID and student number together. An illustrative record is `UID=04AABBCCDD;STUDENT=000123456<Enter>`; this is not an agreed format. Accept only complete records from that card operation and discard incomplete ones. If validated, the PN532 may no longer be needed at the kiosk. Verify that the OMNIKEY identifier matches the identifier used by the tool readers; the label “CSN” alone does not establish that it is the UID currently read by the PN532.

2. **Keep both readers and compare a shared identifier.** Have the OMNIKEY supply its UID alongside the student number from the same card operation, then require `PN532 UID == OMNIKEY UID`. Reject the whole attempt if either value is missing or the identifiers differ. This can detect the PN532 reading card A while the OMNIKEY reads card B, provided both expose the same underlying identifier with consistent formatting. Availability depends on the card technology: some technologies have no CSN or use randomized serial numbers. If the OMNIKEY can supply both required values reliably, reassess whether the PN532 adds useful assurance.

3. **Physically constrain the card if no shared identifier is available.** Investigate a single-card slot or holder that keeps one card positioned throughout both reads, with withdrawal detection cancelling the attempt and discarding both values. Validate the slot, sensing, reading area, and swap/multiple-card cases. A simple presence sensor proves only that something is present, not which card it is. A loose tray or an instruction to keep the card still reduces mistakes but does not enforce the association. This is an engineering fallback, not established proof for the current hardware.

### Checks that are insufficient on their own

- A shorter timeout, matching session IDs, or closely spaced readings does not establish physical identity.
- Reading the PN532 UID again afterward catches some mistakes but leaves a swap gap: `UID A → student number B → UID A` is still possible if cards change between reads.
- Merely combining two values into one software record does not establish that the hardware obtained them from the same card operation.

### Next experiment when resumed

1. Save the OMNIKEY's existing working configuration before changing it.
2. Inspect its firmware, enabled card technology, and the field/configuration currently producing the student number.
3. Test whether it can output that field together with a serial number from the same card operation.
4. Compare the serial number with the PN532 UID across several cards and repeated presentations, including removal/re-presentation and restarts. Check byte order, hexadecimal versus decimal formatting, and leading zeros without assuming different identifiers can be converted into one another.
5. Check compatibility with the tool readers' identifier and exercise incomplete reads, swaps, and multiple-card presentations before accepting an approach. Record results using card aliases rather than real student identifiers.

The reader configuration has not yet been inspected for this capability. The open question is whether both required identifiers are available from the same chip/card operation on the actual student cards.

**Reference:** [HID OMNIKEY 5x27CK Keyboard Wedge Configuration and Custom Report User Guide, revision E.5 (manufacturer guide hosted by Satin)](https://www.satin.fr/dl/omnikey-5427ck-userguide.pdf), printed page 28 for multiple output fields and page 36 for CSN/card-data definitions and technology limitations. These documented capabilities support investigation; they do not confirm compatibility with the kiosk's cards or installed firmware.

## `kiosk_requests` retention and clean-up

Every kiosk call stores one row in `kiosk_requests`. That's every `/activate` and `/register`, including answers that change nothing, like `UNREGISTERED` or a denial. Ops needs the row for two things:

- **Replay:** if the same `request_id` arrives again, ops returns the stored answer instead of writing twice.
- **Recovery:** the kiosk's `GET /kiosk/requests/{id}` lookup after a lost reply.

Nothing ever deletes these rows, so the table only grows. Size isn't the problem: a few hundred scans a day of small rows is nothing for years. There are two real problems.

**1. Privacy.** Each row holds a UID and a student number. Keeping them forever is a retention policy you made by accident. The TODO "Privacy and records" item says retention still needs agreeing. These rows are only needed for minutes, until the kiosk gets its answer.

**2. The trap: a clean-up can break recovery.** The lookup rule says a 404 means nothing was committed, which is only true while rows are kept. Here's how it goes wrong:

1. The kiosk sends an activation. Ops commits it, but the reply is lost.
2. The kiosk is powered off for 10 days.
3. A clean-up job deletes rows older than 7 days.
4. The kiosk boots, looks up the request and gets a 404. It concludes nothing was written, but ops did write.

That's a wrong answer that looks right.

**Fix, once you add a clean-up:**
- Ops deletes rows older than a set retention period, say 30 days, in one `DELETE … WHERE created_at < now - 30 days`. Use a cron entry or run it on startup.
- The kiosk's pending file already has a timestamp. A 404 counts as "nothing committed" only if the record is younger than the retention period. Older than that means operator help.
- Write the retention period in `ops-api.md` so both sides use the same number.

For Friday, do nothing: no clean-up means the trap can't happen. Add the clean-up and the age check together, never the clean-up alone.

You could also store a hash of the request body instead of the raw UID and student number. Replay comparison still works, and the privacy issue mostly goes away.

## Deferred beyond student v1

- **Founder access:** fully define enrolment, identity, training/eligibility, card provisioning, replacement, and activation. Keeping RFID cards for founders is a future direction; earlier choices about personal cards and backend provisioning are provisional, not a v1 commitment.
- **Occupancy counting:** remains outside v1. An active visit is not proof that the student is physically present.
- **Loan cards and lending hardware:** no current requirement for dispensing, returns, stock, motors, or non-return flags. This scope decision does not mean existing equipment has been discarded.

## Resolved baseline

See the [confirmed requirements](docs/plan.md#2-confirmed-requirements) and [implemented behavior and next work](docs/plan.md#7-core-migration-implemented-and-next-work).
