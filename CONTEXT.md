# Makerspace Access Kiosk

Students tap their campus cards to check in to and out of the makerspace. Check-in registers the card for that visit; an active visit and the appropriate training determine tool access.

## Language

**Kiosk**:
The self-service point where students check in and check out.
_Avoid_: Tool controller, dispenser

**Student card**:
The student's existing campus identity card, used to identify the student and present their registered credential at tools.
_Avoid_: Loan card, makerspace card

**Student number**:
The student's institutional identifier, distinct from the identifier of their physical card.
_Avoid_: Card number, UID

**Card UID**:
The card identifier read from a physical student card and represented in hexadecimal. Its association with a student number identifies the registered holder.
_Avoid_: Student number, training level

**Registration**:
The association between a student card's UID and a student number for one visit. Check-in creates it; check-out or the daily access reset ends it.
_Avoid_: Activation, permanent link

**Activation**:
The granting of a temporary visit after the student's current eligibility is checked. It happens together with registration at check-in.
_Avoid_: Registration, card issuance

**Check-in**:
A tap with a card that has no active visit. After eligibility checks, it registers the card and activates a visit.
_Avoid_: Activation (when describing the whole tap)

**Check-out**:
A tap with a card that has an active visit. It ends the visit and its registration. No eligibility check is needed to check out.
_Avoid_: Card return, unlink

**Active visit**:
A student's current activation, recognised across participating tools subject to each tool's training requirements. It ends at check-out or the daily access reset. It is not a measurement of physical presence, since students may leave without tapping out, and it does not grant permission to use every tool.
_Avoid_: Occupancy, universal tool permission

**Replacement**:
The substitution of the UID on a student's active visit with their replacement card's UID. The previous card is revoked.
_Avoid_: Additional card, second registration

**Revoked card**:
A card UID the backend permanently refuses. Revocation survives the daily access reset, so a lost or replaced card cannot register itself again.
_Avoid_: Expired card, unregistered card

**Daily access reset**:
The end of all active visits and their registrations at midnight in America/Toronto. It is expiry, not a job, and it does not affect revoked cards. It does not prohibit an immediate check-in.
_Avoid_: Enforced closing time

**General induction**:
The general makerspace training required for registration and activation, distinct from training for a particular tool.
_Avoid_: All-tool training

**Tool training**:
The training required to use a particular tool, checked separately from general induction.
_Avoid_: General induction, activation

**Eligibility**:
Whether a student is currently permitted to register or activate under the backend-owned access policy, including the account and general-induction requirements.
_Avoid_: UID recognised, card registered

**Unknown student**:
A student number for which no backend account exists. This differs from an unregistered card belonging to a student who already has an account.
_Avoid_: Unknown card, founder

**Unregistered card**:
A card UID without a current registration: every card at its first tap of the day, and after check-out. Its holder may still have an existing account.
_Avoid_: Unknown student

**Student-number reader**:
The kiosk reader that obtains the student number from a student card.
_Avoid_: UID reader, tool reader

**UID reader**:
The kiosk reader that obtains the card UID for check-in or check-out.
_Avoid_: Return reader, makerspace-card reader

**Card presentation**:
The physical act of presenting a card to be read. One presentation during registration supplies both the student number and card UID through adjacent readers.
_Avoid_: Two taps (when describing registration)

**Tool reader**:
The reader associated with a tool that participates in enforcing the registered student's access and training requirements.
_Avoid_: Kiosk reader, entrance-door reader

**Display**:
An output-only kiosk screen presenting instructions and feedback to users.
_Avoid_: Touchscreen, return-side display
