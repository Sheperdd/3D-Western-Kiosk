---
status: accepted
date: 2026-09-16
---

# Persistent student-card registration with separate daily activation

The adjacent-reader arrangement produced a student number and a stable hexadecimal card UID from one student card. Student v1 will therefore register existing student cards instead of lending separate RFID cards, with broader card compatibility and reliable pairing still to be validated. Registration persists, while a separate backend-confirmed activation grants a visit after current account, general-induction, and eligibility checks.

One presentation registers and activates an eligible student; later visits require only a UID tap. Automatic verified replacement invalidates the old UID and activates the new card. Repeat taps confirm an active visit rather than unlinking or checking out. The backend expires activations at midnight America/Toronto without deleting registrations or prohibiting immediate reactivation; individual tools still enforce their own training requirements.

This removes the lending hardware and daily card-handling burden, but makes reliable identifier pairing, replacement, and revocation essential. Registration and activation are refused when the backend is unavailable. The kiosk owns the interaction, while the backend/tool team remains authoritative for associations, eligibility, visits, expiry, and enforcement. Founder access is deferred beyond student v1; earlier founder provisioning ideas are provisional.

## Effect on earlier decisions

**2026-10-07 amendment:** the kiosk now requires both the UID and student number before any backend processing, including returning visits. This supersedes the UID-only kiosk interaction above. Collection follows UID capture, acknowledged RF-off, then a complete student number. An observed pair is not verified same-card identity and cannot authorize registration or replacement. The internal activation request still takes a UID; this ordering decision does not settle the backend payload or change tool-reader behavior. The current hardware diagnostic permits one presentation per run until card-removal/rearming rules are validated.

**Subsequent rearming decision:** Shane explicitly chose to assume students take their cards back rather than implement presence detection. The controller now rearms after result feedback and reader cleanup, provided it is idle and both systems are ready. This supersedes the one-presentation-per-run restriction above; a held card may be processed again. Buffered input is discarded before the next UID attempt, and raw pairs remain unverified.

- **ADR-0001:** supersedes the kiosk's lending-lifecycle responsibility; backend authority and tool-side enforcement remain.
- **ADR-0002:** supersedes the checkout/return asymmetry, unlink outbox, and nightly unlink. Both registration and activation require backend confirmation; the daily reset expires activations only.
- **ADR-0003:** supersedes motor/lending interaction assumptions. The Python core, Chromium web UI, and scan-driven output-only direction remain; the current plan assigns student interaction to display 1 and general instructions/system status to display 2.
- **ADR-0004:** supersedes interpreting a recognised UID as a return. Adjacent readers support one-presentation registration; a registered UID supports activation or already-active confirmation.

The [requirements plan](../plan.md) is the current baseline. This decision does not specify an API schema or resolve reader correlation or cross-account UID conflicts. Display roles were subsequently agreed for now: student interaction on display 1 and general instructions/system status without student-specific information on display 2.
