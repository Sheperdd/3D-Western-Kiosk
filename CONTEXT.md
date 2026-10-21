# Makerspace Access Kiosk

Students tap their campus cards to check in to and out of the makerspace. The kiosk sends each tap to the access gatekeeper, which links the card, checks orientation, and opens or closes the student's visit. An open visit and the right certifications determine machine access at the stations. See [ADR-0007](docs/adr/0007-kiosk-talks-to-gatekeeper.md).

## Language

**Kiosk**:
The self-service point at the entrance where students check in and check out.
_Avoid_: Tool controller, dispenser

**Gatekeeper**:
The access service on the makerspace PC. The only system the kiosk talks to. It answers from a local copy of the main backend's data and syncs with it on its own.
_Avoid_: Backend, ops, ops-backend (when meaning what the kiosk calls)

**Main backend**:
The platform's source of truth for accounts, orientation and certifications. The kiosk never calls it directly.
_Avoid_: Dashboard (when meaning the data source)

**Device key**:
The secret the kiosk sends in `X-Device-Key` on every tap. Issued once when an admin registers the kiosk as a `KIOSK` device.
_Avoid_: Token, API token

**Student card**:
The student's existing campus identity card. It carries both a card UID and the student number.
_Avoid_: Loan card, makerspace card

**Student number**:
The student's institutional identifier, read from the card by the student-number reader. Sent to the gatekeeper as an integer.
_Avoid_: Card number, UID

**Card UID**:
The card's identifier read by the UID reader, as uppercase hexadecimal with no separators.
_Avoid_: Student number, training level

**Card presentation**:
The physical act of presenting a card. One presentation supplies both the UID and the student number through adjacent readers.
_Avoid_: Two taps

**Tap**:
One request to the gatekeeper for one card presentation. It toggles: check-in if the student has no open visit, check-out if they have one.
_Avoid_: Activation, registration

**Card link**:
The gatekeeper's permanent association between a card UID and a student number. Made automatically by the first accepted tap with a new card. A student may have several linked cards. Only an admin can deactivate one.
_Avoid_: Registration, daily registration

**Check-in**:
A tap by a student with no open visit that passes the gatekeeper's checks. It opens a visit and links the card if needed.
_Avoid_: Activation, registration

**Check-out**:
A tap by a student with an open visit. It closes the visit and the student's machine sessions. No eligibility check.
_Avoid_: Card return, unlink

**Open visit**:
A student's current check-in. Stations require one before allowing a machine. Not proof of physical presence: students may leave without tapping out.
_Avoid_: Active visit, activation, occupancy

**Nightly reset**:
The gatekeeper closing visits still open at `nightlyResetTime` (admin setting, default 03:00 America/Toronto), recorded as "forgot to tap out". It does not touch card links and does not prevent checking in again.
_Avoid_: Daily access reset, midnight expiry, UID wipe

**Orientation**:
The general makerspace training everyone, staff included, must hold to check in.
_Avoid_: General induction

**Certification**:
A student's status for one machine training (`trainingId`). Checked at stations, not at the kiosk. The kiosk may list them on the welcome screen.
_Avoid_: Tool training, training level

**Station**:
The ESP32 reader at a machine. It sends only the card UID and refuses cards not linked at the kiosk.
_Avoid_: Tool reader, kiosk reader

**Result**:
The gatekeeper's answer to a tap: `CHECKED_IN`, `CHECKED_OUT`, `DENIED` or `IGNORED_DUPLICATE`. The kiosk adds local results for its own failures (bad read, timeout, gatekeeper unreachable, kiosk not set up).
_Avoid_: Outcome

**Reason**:
A stable code explaining a `DENIED` result (`UNKNOWN_STUDENT`, `ORIENTATION_REQUIRED`, `EMAIL_NOT_VERIFIED`, ...). Used to pick an icon or QR, never to build wording.
_Avoid_: Error code

**Message**:
The ready-to-show sentence the gatekeeper sends with every result. Display 1 shows it as given.
_Avoid_: Kiosk copy (for gatekeeper results)

**Unknown student**:
A student number the gatekeeper has no account for (`UNKNOWN_STUDENT`). The student signs up, then taps again.
_Avoid_: Unknown card, unlinked card

**Student-number reader**:
The kiosk reader (OMNIKEY) that obtains the student number from a student card.
_Avoid_: UID reader, station

**UID reader**:
The kiosk reader (PN532) that obtains the card UID.
_Avoid_: Return reader, station

**Display**:
An output-only kiosk screen. Display 1 guides the current student; display 2 shows general instructions and status without personal information.
_Avoid_: Touchscreen, return-side display
