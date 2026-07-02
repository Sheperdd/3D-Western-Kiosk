# Makerspace Access Kiosk

A self-service kiosk that gates physical access to a makerspace. A student identifies themselves, and if their training is on file the kiosk dispenses a reusable access card linked to them; tools in the space then enforce per-student training when that card is presented. On the way out the student returns the card and the link is dropped.

## Language

**Kiosk**:
The self-service station this project builds. It owns the access-card lifecycle — dispensing, linking, unlinking, and accepting returns — and nothing else.
_Avoid_: Terminal, station, machine

**Student card**:
The student's existing campus identity card, presented at the kiosk's student-card reader. It emits the student number directly (confirmed — the OMNIKEY 5427 reads the card and types the student number as keyboard input).
_Avoid_: ID card, badge

**Student number**:
The canonical student identifier the backend keys on. Obtained from the student card and sent to the training endpoint.
_Avoid_: Student ID, user ID

**Makerspace card**:
A reusable RFID card on a retractable badge reel that the kiosk dispenses. While linked to a student it acts as that student's key to the tools they're trained on. Owned by the kiosk between uses.
_Avoid_: Access card, key card, RFID tag (when a specific card is meant)

**Link**:
The association between a makerspace card and a student, recorded by the backend. Created when the student scans the dispensed card at the kiosk; consulted by tools at unlock time.
_Avoid_: Pair, assign, register

**Unlink**:
Removing the makerspace card↔student association in the backend. Happens on return and on the midnight reset.
_Avoid_: Unpair, release, deregister

**Trained / Training level**:
Whether (and on what) a student is certified, as returned by the backend training endpoint for a student number.
_Avoid_: Certified, qualified (as nouns)

**Unknown student**:
A person whose student card scan yields a student number the backend has no account for — they have not created a club account. The kiosk shows a QR code to the account signup page (a distinct screen from the not-trained training QR). Not to be confused with an unknown makerspace card (a UID not in the card registry), which is a transient error.
_Avoid_: Unregistered user, guest, unknown user

**Dispense box**:
The motorised iris-diaphragm enclosure that holds the pool of undispensed makerspace cards. Opens when a trained student scans in, exposing the whole pool so they can take one card; closes once the link is formed (or the interaction times out).
_Avoid_: Compartment (ambiguous), dispenser

**Return drawer**:
The separate motorised, locking drawer that unlocks on a valid return scan for the student to drop their card into. Returned cards collect here, distinct from the dispense box's pool.
_Avoid_: Compartment (ambiguous), slot

**Stock**:
The count of makerspace cards available in the dispense box. "Out of stock" means the dispense box is empty even though returned cards may be sitting in the return drawer awaiting manual refill.
_Avoid_: Inventory

**Midnight reset**:
A scheduled job (at midnight / makerspace close) that unlinks every outstanding makerspace card in the backend, in case students left without returning. Also the backstop that cleans up any unlinks the offline outbox failed to deliver.
_Avoid_: Nightly wipe, purge

**Non-return flag**:
A mark set on a student's backend account by the midnight reset when they failed to return their makerspace card that day. In v1 it is a passive, countable record with no automatic penalty.
_Avoid_: Strike, penalty, ban

**Outbox**:
The kiosk's local, best-effort queue of unlink operations recorded while the backend was unreachable, retried until confirmed. Not a source of truth — the backend is authoritative; the midnight reset covers anything the outbox loses.
_Avoid_: Sync queue, cache

**Display**:
An output-only screen on the kiosk that shows the current state — instructions, errors, the training QR code, flow prompts. Not a touchscreen; the kiosk takes no touch input. All user input arrives via card scans.
_Avoid_: Touchscreen, monitor

**Student-card reader**:
The OMNIKEY 5427 (already owned) mounted at the kiosk that reads a presented student card and outputs the student number as keyboard input. Distinct from the makerspace card reader.
_Avoid_: ID reader, badge reader

**Makerspace card reader**:
The single 13.56 MHz RFID reader that handles both checkout (link) and return (unlink). It sits at the bottom of the kiosk's open middle so a card can be presented from either side. Replaces the earlier separate link and return scanners (see ADR-0004). Whether a tap is a link or an unlink comes from the card's current link state plus session context — a linked card is a return (no student-card scan needed); an unlinked card links inside an active checkout session, and outside any session opens the return drawer as a loose card with no link to remove.
_Avoid_: Link scanner, return scanner (no longer separate), tool reader

**Tool reader**:
A reader+lock attached to each tool/machine. NOT part of this project. It reads a presented makerspace card and queries the backend to decide whether to unlock. The kiosk never controls tool power.
_Avoid_: Machine lock, tool lock

## Resolved assumptions

- **Student card encoding.** _Resolved._ The reader is the OMNIKEY 5427 (already owned); it reads the campus card and outputs the student number directly as keyboard input. No UID→student-number lookup is needed, and the earlier risk — that the card might expose only an opaque chip UID — does not apply.
