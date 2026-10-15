# Open requirements and decisions

Updated 2026-10-13. The agreed baseline is [docs/plan.md](docs/plan.md). These items are unresolved, not permission to invent defaults during implementation.

## Resolve for student v1

- **Display details — Shane / makerspace stakeholders:** review the implemented dummy screens on the actual monitors. Confirm production copy, help contacts, QR destinations, training labels, and backend-provided machine access; see [display content](docs/display-spec.md).
- **Reader correlation — kiosk and hardware teams:** establish how the student-number and UID readings are proven to belong to the same presentation. Cover missing/delayed output, arrival order, repeat reads, disconnects, back-to-back users, and both readers firing during a repeat visit. Temporal proximity alone is not an agreed solution.
- **Hardware evidence — hardware team:** expand the one-card trial to multiple student cards and repeated presentations. Record reader models/settings, identifier formats, consistency across restarts, and compatibility with tool readers. Decide what evidence meets the reliability target.
- **Backend contract — backend/tool team and Shane:** agree operations and responses for eligibility, registration plus activation, replacement plus activation, already-active visits, and daily expiry. Define authentication, denial reasons, conflicts, concurrency, retries, partial completion, and recovery when a response is lost. No endpoint paths or payload schemas are agreed yet.
- **UID conflict — backend team / stakeholders:** decide what happens when a scanned UID is already registered to a different account. Automatic replacement of one's own old card does not settle cross-account conflicts.
- **Replacement and revocation — backend/tool team / stakeholders:** agree how lost cards are revoked before replacement and how invalidation propagates to tools. Define handling of existing activation during replacement and eligibility changes during an active visit. Midnight expiry behaviour for a tool already in use belongs to the tool team and needs agreement.
- **Support and recovery — makerspace operators:** define staff assistance, unreadable/forgotten-card guidance, reader/backend outage handling, restart recovery, escalation channels, and authorised servicing. Loaner-card dispensing is not part of current v1.
- **Privacy and records — stakeholders / backend team:** screens show no student identifiers. Agree diagnostic logging, local retention, retention periods, and who may access records. No local identity database or offline eligibility cache is assumed.
- **Targets and acceptance — stakeholders and delivery teams:** name who approves requirements and signs off the pilot; agree response times, scan reliability, accessibility/usability criteria, pilot duration, monitoring, support, and stop/rollback criteria.
- **Deployment — kiosk/hardware team and campus IT:** confirm available Pi equipment, display/enclosure arrangement, network access, and servicing arrangements. Carry forward applicable appliance/recovery constraints during design; old provisioning details are not a new approved deployment specification.

## Deferred beyond student v1

- **Founder access:** fully define enrolment, identity, training/eligibility, card provisioning, replacement, and activation. Keeping RFID cards for founders is a future direction; earlier choices about personal cards and backend provisioning are provisional, not a v1 commitment.
- **Occupancy counting:** remains outside v1. An active visit is not proof that the student is physically present.
- **Loan cards and lending hardware:** no current requirement for dispensing, returns, stock, motors, or non-return flags. This scope decision does not mean existing equipment has been discarded.

## Resolved baseline

See the [confirmed requirements](docs/plan.md#2-confirmed-requirements) and [implemented behavior and next work](docs/plan.md#7-core-migration-implemented-and-next-work).
