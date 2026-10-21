---
status: accepted
date: 2026-10-20
---

# Tap to check out, with registrations wiped daily

Students need to be able to leave the makerspace by tapping their card again. A tap with a card that has an active visit now checks the student out; any other tap checks them in. Card registrations are also wiped every day: the UID↔student association lasts one visit and ends at check-out or at midnight America/Toronto, whichever comes first. The first tap of each day registers the card again.

The backend makes the toggle decision. The kiosk sends the same two logical operations as before: `ActivateUid` now returns `CHECKED_OUT` for an active card or `UNREGISTERED` for any other card, and `RegisterAndActivate` becomes the everyday check-in. The kiosk state machine keeps its shape and its same-card gate (`IdentityConfirmed` before registration). Ops stores the UID on the visit instead of in a separate registration table, so the daily wipe and the check-out both follow from the visit's `ended_at` and `expires_at`. No midnight job is needed and none can be missed. Check-out does no eligibility check, so a suspended student or a dashboard outage cannot stop someone from leaving. Contract: [ops-api.md](../ops-api.md).

Revoked cards are kept in a permanent table that the daily wipe never touches. Without it, a lost or replaced card would register itself again the next morning, because the card carries its owner's student number.

## Consequences

- **Same-card verification on every check-in.** Before this change it was needed once per card. Now every check-in is a registration. The Friday 2026-10-23 shortcut (auto-`IdentityConfirmed`, `TODO(same-card)`) therefore covers every check-in, and the real same-card mechanism becomes a requirement for every visit after Friday.
- **Held cards toggle.** Shane chose no double-tap guard. The controller assumes card removal and rearms after result feedback, so a card left on the reader flips the visit in and out about every 13 seconds. Count occurrences in the Thursday soak. If it happens, add a backend cooldown: when the student's latest visit started or ended less than N seconds ago, return its current status unchanged.
- **Offline check-out fails closed.** The kiosk cannot tell a check-out tap from a check-in tap without the backend, so it refuses both while offline. ADR-0002's queued-return idea is not revived: the worst case is a visit that lasts until midnight, which is the same as a forgotten tap-out.
- **Forgotten tap-outs.** A visit still ends at midnight without a tap. An active visit therefore remains not proof of physical presence; occupancy stays out of scope.
- **Outcomes.** `CHECKED_OUT` is added. `ACTIVATED` and `ALREADY_ACTIVE` lose their producers and are removed. `REGISTERED_AND_ACTIVE` is the normal check-in result.
- **Tools.** A checked-out or expired UID is refused with `NO_ACTIVE_VISIT`. What a tool does when its user checks out mid-use is the tool team's decision.
- **Privacy.** UIDs remain in visit history. Removing them is a separate nightly scrub, added only if the retention policy requires it. Access never depends on it.

## Effect on earlier decisions

- **ADR-0005:** supersedes "registration persists" and "repeat taps confirm rather than unlinking or checking out". The daily reset now ends registrations as well as activations. Backend authority, verified replacement with old-card invalidation, the collect-both-identifiers rule, and the Friday auto-registration exception remain.
- **ADR-0002:** card associations are reset nightly again, but by expiry rather than an unlink job. Check-out has no offline outbox; see above.
- **R5 and R8** in the [requirements plan](../plan.md) are rewritten to match.
