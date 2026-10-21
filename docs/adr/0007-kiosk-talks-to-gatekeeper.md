---
status: accepted
date: 2026-10-21
---

# The kiosk talks to the access gatekeeper with one tap call

The students' ops-backend is not being run. Its job (kiosk check-in/out, visits, machine allow/deny) moved to the **access gatekeeper**, a small service on the makerspace PC that answers from a local copy of the main backend's data and syncs with it on its own (platform decisions D-13 and D-18). The kiosk talks only to the gatekeeper. It never talks to the main backend.

The gatekeeper exposes one kiosk call, `POST /v1/kiosk/tap`, with the card UID and the student number from the same presentation (`{"uid", "studentNumber"}`, the number as a JSON integer) and the kiosk's `X-Device-Key`. It answers `200` with a `result` (`CHECKED_IN`, `CHECKED_OUT`, `DENIED`, `IGNORED_DUPLICATE`), a `reason` code when denied, and a ready-to-show `message` and `notices`. The kiosk-facing guide is [kiosk-api.md](../kiosk-api.md); the binding wire contract is the platform's [gatekeeper-contract.md](../../../makerspace-platform/docs/specs/gatekeeper-contract.md) §1.1 and §4. Where they disagree, the contract wins.

The kiosk's two logical operations (`ActivateUid`, then `RegisterAndActivate` after `UNREGISTERED`) collapse into that single tap. The gatekeeper decides check-in versus check-out, links the card, and checks eligibility in one step. The kiosk still owns reading both identifiers from one presentation and never sending a mis-paired UID and number.

## What changes

- **One call per presentation.** No routing result, no second request, no `IdentityConfirmed` gate inside the state machine. Same-card assurance stays in the reader layer, before the tap is sent.
- **Toggle by student number.** A student with an open visit is checked out, whichever of their cards was tapped. Check-out does no eligibility check.
- **Card links are permanent.** The first accepted tap with a new UID links it to the student number on the card. A student may have several linked cards (an old and a replacement); the kiosk does not revoke the old one. There is no daily UID wipe.
- **Nightly reset, not midnight.** Open visits close at the gatekeeper's `nightlyResetTime` (admin setting, default 03:00 America/Toronto). A visit left open past it is closed as "forgot to tap out" at the student's next tap.
- **Eligibility is orientation.** Check-in needs an active account, a verified email, and orientation (`ORIENTATION_REQUIRED` otherwise). Everyone needs it, staff included. Machine certifications are checked at stations, not the kiosk.
- **The backend owns the wording.** The kiosk shows `message` and `notices` as given and ignores unknown fields and reason codes. Local wording remains only for kiosk-side results (bad read, timeout, gatekeeper unreachable, kiosk not set up). QR codes are chosen from `reason`.
- **No request-ID recovery.** There is no lookup endpoint for a lost reply. The kiosk waits about 2 s, resends the same tap once immediately (a repeat within `tapDebounceSeconds`, default 3 s, returns the first answer as `IGNORED_DUPLICATE`), and otherwise shows "Couldn't reach the system, please tap again" and returns to ready. `OUTCOME_UNKNOWN` and its hold are removed.
- **Readiness comes from `GET /healthz`.** The kiosk is online only when the gatekeeper answers with `hasSnapshot: true`; before its first sync every tap would be `UNKNOWN_STUDENT`.
- **Device authentication.** The kiosk is registered as a `KIOSK` device and sends its key on every tap. The key is a secret on the Pi, sent only over the private reader network (plain HTTP).

## Consequences

- **Lost replies can toggle twice.** If the gatekeeper committed a tap but the reply was lost, and the student taps again after the debounce window, the visit flips back. Accepted: every reply is shown, so the student sees the result and can tap again.
- **Mis-pairs now move ownership.** The gatekeeper trusts the pair and relinks a UID to whatever number arrives, so a reader mis-pair silently hands a card to another student. The kiosk is the only guard (R13). A server-side `CARD_CONFLICT` refusal is proposed to the platform and needs Troy's approval.
- **Lost cards are not blocked yet.** An admin can deactivate a card link, but the next kiosk tap with that card links it again, because the card carries its owner's number. Permanent revocation needs a platform change (contract, backend snapshot, gatekeeper) and is required before unattended use.
- **A held card still toggles.** The 3 s debounce does not cover the kiosk's ~13 s rearm. Card-removal detection remains kiosk follow-up work.
- **Display 1 shows the student's first name and backend messages.** Display 2 still shows no personal information.
- **Plan:** [gatekeeper-integration-plan.md](../gatekeeper-integration-plan.md).

## Effect on earlier decisions

- **ADR-0005:** superseded. Registration is replaced by permanent card links owned by the gatekeeper; replacement no longer revokes the old card; there is no separate activation call.
- **ADR-0006:** mostly superseded. A tap still toggles the visit and check-out still needs no eligibility check. The daily UID wipe, midnight expiry, permanent revoked-cards table, two-operation flow and the "no double-tap guard" statement no longer apply. Offline check-out still fails closed: the kiosk cannot tell a check-in from a check-out without the gatekeeper.
- **ADR-0002:** the kiosk still never grants access offline. The gatekeeper itself keeps working when the main backend is unreachable; that is its concern, not the kiosk's.
- **ADR-0003:** unchanged (Python core, Chromium web UI, scan-driven output-only displays).
- [ops-api.md](../ops-api.md) and [backend-agreement.md](../backend-agreement.md) are superseded by [kiosk-api.md](../kiosk-api.md).
