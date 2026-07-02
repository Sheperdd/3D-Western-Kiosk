# TODO / Open Questions

Running list of decisions and risks to resolve — several need input from higher-ups or the backend team before they can be locked into an ADR.

## To raise with higher-ups

### Iris dispense box can't enforce one-card-per-student

The current dispense design opens an iris diaphragm that exposes the **whole pool** of makerspace cards at once, rather than vending exactly one. Consequences the kiosk cannot directly prevent:

- A student can grab **two** cards, or grab one for a friend.
- A student can take a card and walk off **without** scanning it to link it — leaving an unlinked card loose and the iris open until it times out. (A loose unlinked card can still be returned: tapping it outside a session opens the return drawer — see ADR-0004.)
- The kiosk only learns which card UID left the pool *if/when* the student scans it at the makerspace card reader.

**Current plan (provisional):** rely on tool-level enforcement — an unlinked or extra card unlocks nothing — plus a stock count to detect when more than one card leaves and raise a staff alert. The iris closes on the link scan or on timeout.

**Decision needed:** is tool-level enforcement + stock reconciliation acceptable, or do we need a single-vend mechanism that reads each card's UID as it dispenses (eliminating multi-grab and making linking automatic)? This changes the mechanical design, so resolve before fabrication. Will become an ADR once decided.

### Where should the kiosk's database live?

The backend is the source of truth for training data and card↔student links, but the kiosk still persists *some* local data (the unlink outbox, card stock count, config, logs, possibly a training cache). Open question for the higher-ups / backend team:

- Should the kiosk have its **own local DB on the Pi**, or read/write a **shared DB owned by the backend**?
- Which data is the kiosk allowed to persist locally vs. must it always defer to the backend?

This affects the offline policy (ADR-0002) and the backend API surface, so settle it before building the persistence layer.

### Iris fail-secure interlock (hardware)

A software-controlled iris means software is the only thing keeping the card pool closed. If the iris jams or motor control fails open, the whole pool is exposed.

**Current plan (provisional):** software handles it — auto-retry the close; if still open, treat as a **security incident**: halt all checkouts, put the displays into a loud "out of service" state, and fire an **urgent** staff/admin alert (distinct from routine motor-jam errors) so someone physically secures it quickly.

**Decision needed:** should we add a physical **fail-secure** interlock (e.g. spring-return shutter or secondary lock) so the pool can't stay exposed on a software/motor failure? More mechanical design, but removes software as the single point of failure for a security-relevant enclosure. Relates to the iris-vs-single-vend question above.

**Related requirement:** the iris should physically **default to closed on power loss** (not freeze open), so a power cut mid-checkout doesn't leave the pool exposed. On boot the kiosk drives everything to a secure state and returns to idle (no session recovery), so the fail-secure default is the only thing protecting the pool during the outage itself.

### Returning someone else's card can unlink them mid-session

The makerspace card reader unlinks whatever linked makerspace-card UID is presented and opens the drawer (open-first, then record/queue the unlink). Anyone physically holding another student's card can therefore unlink that student — potentially while they're mid-session at a tool. It requires possession of the card (which already grants that person access), so the exposure is limited, but it's a griefing vector.

**Current plan:** allow it. Note that the decided return flow (ADR-0004) requires **no student-card scan** to return, so the kiosk normally records only *which student the card was linked to*, not who physically returned it — returner identity is generally not captured. Revisit owner-bound returns (require the holder's student card + their makerspace card) or an optional returner student-card scan if abuse becomes a problem.

### Alert channel (infrastructure)

The kiosk needs to notify staff for: out-of-stock dispense box, the iris security incident, return-drawer full, backend-offline, and hardware jams. The delivery channel depends on infra we may not own yet.

**Decision needed:** which channel(s) — email, Slack/Teams, an admin dashboard, an on-device indicator/buzzer, or several tiered by severity (e.g. routine → dashboard, urgent iris incident → push/SMS)? Confirm what's available with the higher-ups / IT.

### Non-return escalation policy

v1 records a soft **non-return flag** on the student's account (no automatic penalty). **Decision needed (makerspace owners):** should repeated non-returns eventually carry a consequence (e.g. block checkout until staff clear it)? If so, define the threshold and the staff clear-flag workflow.

### Displays: revisit open-frame panels for the final enclosure

v1 uses self-contained **portable USB-C/HDMI monitors** (15.6", non-touch) — cheap, easy to wire, good for the prototype. For the production kiosk, revisit **open-frame / embedded LCD panels with a driver board** (e.g. Mimo M15680-OF, faytech open-frame): flush mounting, no consumer bezel/power-button, longer-life industrial backlights, designed to be built into an enclosure. Decide before the final enclosure is fabricated.

### Need to talk about staff-servicing (Adding cards)

We can just have a file in tools that would connect to the backend and we manually scan each makerspace card to add it.

## Deferred / out of v1 scope

- **Occupancy counting** (computer vision, time-of-flight, tripwire, card-count proxy). Designed out of v1 — build the core checkout/return/access flow first. Do **not** order sensing hardware (camera/ToF) yet. Revisit as a later phase. Card-count alone is known to undercount (misses friends/hangers-on), so it's not a real substitute.

## Resolved (see CONTEXT.md)

- **Student card encoding** — _Resolved._ Reader is the OMNIKEY 5427 (already owned); it outputs the student number directly as keyboard input. No UID→number lookup needed.
