# Makerspace Access Kiosk

Students register their campus cards and activate temporary access to makerspace tools. Card registration identifies the student; an active visit and the appropriate training determine tool access.

## Language

**Kiosk**:
The self-service point where students register cards and activate visits.
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
The persistent association between a student card's UID and a student number. It survives the daily access reset.
_Avoid_: Activation, checkout, temporary link

**Activation**:
The granting of a temporary visit after the student's current eligibility is checked.
_Avoid_: Registration, card issuance

**Active visit**:
A student's current activation, recognised across participating tools subject to each tool's training requirements. It is not a measurement of physical presence or permission to use every tool.
_Avoid_: Occupancy, universal tool permission

**Replacement**:
The substitution of a student's registered card UID with their replacement card's UID, invalidating the previous card's access.
_Avoid_: Additional card, second registration

**Daily access reset**:
The expiry of visit activations at midnight in America/Toronto while registrations remain intact. It does not prohibit immediate reactivation.
_Avoid_: Unlink, nightly wipe, enforced closing time

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
A card UID without a current registration. Its holder may still have an existing account.
_Avoid_: Unknown student

**Student-number reader**:
The kiosk reader that obtains the student number from a student card.
_Avoid_: UID reader, tool reader

**UID reader**:
The kiosk reader that obtains the card UID for registration or visit activation.
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
