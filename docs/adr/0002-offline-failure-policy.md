# Offline failure policy: checkout fails closed, return stays open with a queued unlink

> **Superseded, 2026-09-16:** [ADR-0005](0005-student-card-registration-and-daily-activation.md) requires backend confirmation for registration and activation. Returns, the unlink outbox, and nightly unlink are outside student v1; midnight expires activation only. The original reasoning below is historical.

When the backend is unreachable, the kiosk treats its two interactions asymmetrically. **Checkout fails closed**: without the backend the kiosk can neither verify training nor write the link, so it refuses and shows a clear "system offline" message. **Return stays open**: the student can always give a card back — the return drawer opens and the kiosk records the unlink in a local best-effort outbox, retrying until the backend confirms.

We chose this over failing both closed (consistent but strands cards with students during an outage) and over failing both open with a cached training list (maximises availability but can hand cards to untrained students from stale data — unacceptable for a safety gate). The asymmetry follows the risk: handing out access is safety-critical and must be verified live; taking access back is always safe to accept.

The outbox is deliberately *not* a source of truth — the backend remains authoritative for who holds which card. If the outbox is lost (e.g. a crash before drain), the nightly midnight reset unlinks all outstanding cards as a backstop, so the worst case self-heals within a day. This keeps the kiosk's only durable state to a disposable retry queue rather than authoritative state.
