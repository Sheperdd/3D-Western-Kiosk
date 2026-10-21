# Ops API: kiosk and machine nodes

> **Superseded, 2026-10-21:** ops-backend is not being run; the access gatekeeper took over its job. The kiosk's contract is now [kiosk-api.md](kiosk-api.md) ([ADR-0007](adr/0007-kiosk-talks-to-gatekeeper.md)). This file is historical.

**Status:** sketch for the Friday 2026-10-23 supervised test. Owner: Shane (taking over ops-backend). Move this file to `ops-backend/docs/` once the takeover is formal. It supersedes the open "to agree" items in [backend-agreement.md](backend-agreement.md) where they conflict.

**Updated 2026-10-20** for tap-out and daily registration ([ADR-0006](adr/0006-tap-out-and-daily-registration.md)).

## Decisions

- **A tap toggles the visit.** A tap with a card that has an active visit checks the student out. Any other tap checks them in, which registers the card for that visit.
- **Registrations last one visit.** The UID is stored on the visit (`visits.uid`); there is no separate registration table. The UID↔student link ends at check-out or at the next America/Toronto midnight, whichever comes first. This is the daily UID wipe. It is enforced by `ended_at` and `expires_at`, so no midnight job is needed.
- **Revoked cards are permanent.** `revoked_cards` is never wiped. Otherwise a lost card would register itself again the next morning, because the card carries its owner's student number.
- Ops stores visits (with their UIDs), revoked cards, and kiosk request results. It does not read dashboard tables.
- Training level comes from a **dashboard endpoint** (built by the dashboard team this week): student number in, training level out.
- At check-in, ops takes a **snapshot** of the training level and stores it on the visit. Machine nodes check ops only and never wait on the dashboard.
- Tool rule: the existing cumulative level. Allowed when `visit.training_level >= equipment.minimum_training_level`.
- **Friday only: the kiosk auto-registers** UID + student-number pairs without same-card verification. Because registrations are wiped daily, this now applies to **every check-in**, not just a student's first. Acceptable for a supervised test only; see [ADR-0005](adr/0005-student-card-registration-and-daily-activation.md), [ADR-0006](adr/0006-tap-out-and-daily-registration.md) and the [TODO](../TODO.md#same-card-identity-options--investigation-deferred).
- **No double-tap guard.** A card held on the reader is read again after each result and flips the visit in and out (about every 13 seconds). Accepted for Friday; count occurrences during the soak.

## Active visit

One definition, used by every route below:

```
ended_at IS NULL AND expires_at > now
```

Implement it once in ops (for example `active_visit_by_uid(uid)` and `active_visit_by_student(student_number)`). Never decide access from `visits.status`: no job runs at midnight, so an expired visit keeps `status = ACTIVE` in that column.

## Authentication

Uses the existing `ApiToken` bearer tokens (`app/api/dependencies/auth.py`).

- A token with `equipment_id` set belongs to a machine node; the equipment comes from the token.
- A token without `equipment_id` belongs to the kiosk.
- Kiosk routes reject equipment tokens. Equipment routes reject tokens without equipment (403).

ponytail: the token's role is inferred from `equipment_id`. Add an explicit role column when a third client type appears.

## Kiosk endpoints

Whenever ops makes a decision, it answers **200 with an `outcome`**. Any other status is a technical failure, and ops has rolled back: nothing was written.

### `POST /api/v1/kiosk/activate`

Despite its name, this is the **tap** endpoint. It either checks out an active visit or tells the kiosk to register the card.

```json
{"request_id": "6f1c…-uuid4", "uid": "04A1B2C3D4", "student_number": "250123456"}
```

```json
{"request_id": "6f1c…", "outcome": "CHECKED_OUT", "reason": null, "expires_at": null}
```

Rules, in order:

1. **Replay:** if `request_id` is already stored, return the stored result. If the same ID arrives with a different body, return 409 `REQUEST_ID_REUSED`.
2. **Revoked:** a UID in `revoked_cards` returns `DENIED` with reason `CARD_REVOKED`.
3. **Check-out:** if this UID has an active visit (lock it with `SELECT … FOR UPDATE`):
   - It belongs to a different student than the `student_number` sent → `UID_CONFLICT`. This is a cheap swap check.
   - Otherwise close it: `ended_at = now`, `status = CLOSED`, `checkout_method = KIOSK`. Return `CHECKED_OUT`.

   Check-out does **no eligibility check and no dashboard call**. Leaving must work for a suspended student and while the dashboard is down.
4. **Otherwise** return `UNREGISTERED` with no write. The kiosk continues to `/register`.
5. Store the result row **in the same transaction** as the writes.

### `POST /api/v1/kiosk/register`

This is check-in. Same body and the same replay rule.

1. **Replay**, as above.
2. **Revoked:** UID in `revoked_cards` → `DENIED` with reason `CARD_REVOKED`.
3. **Eligibility** (dashboard): no account → `UNKNOWN_STUDENT`; suspended or banned → `DENIED`; level 0 → `MISSING_INDUCTION`. An ineligible student is never registered.
4. Lock active visits for this UID and for this student (`SELECT … FOR UPDATE`). MariaDB has no partial unique index, so this locking is what enforces one active visit per UID and per student.
5. **UID on another student's active visit** → `UID_CONFLICT`. Ownership never transfers automatically.
6. **UID already on this student's active visit** (only possible if another tap raced this one) → refresh the `training_level` snapshot and return `REGISTERED_AND_ACTIVE`.
7. **Student has an active visit on a different UID** → insert the old UID into `revoked_cards`, set the visit's `uid` to the new one, refresh the snapshot, and return `REPLACED_AND_ACTIVE`. The visit keeps its `expires_at`.
8. **Otherwise** create a visit: `uid`, `student_number`, `started_at = now`, `status = ACTIVE`, `expires_at` at the next Toronto midnight (stored in UTC), and the level snapshot. Return `REGISTERED_AND_ACTIVE`.
9. Everything, including the result row, in one transaction.

### `GET /api/v1/kiosk/requests/{request_id}`

Returns the stored result, or 404.

Result rows commit atomically with the domain writes. So a 404 **after the original request's timeout window** (about 60 seconds after sending) means nothing was committed. The kiosk can then clear its pending hold without operator help. If the lookup itself fails on the network, the kiosk stays held and retries.

### Errors (no write in all cases)

| Status | `code` | Meaning |
|---|---|---|
| 401 | `INVALID_API_TOKEN` | Missing, inactive, or expired token. |
| 403 | `WRONG_CLIENT_TYPE` | Equipment token on a kiosk route, or the reverse. |
| 409 | `REQUEST_ID_REUSED` | Same `request_id`, different body. |
| 422 | (FastAPI validation) | Malformed UID or student number. |
| 503 | `DASHBOARD_UNAVAILABLE` | Training lookup failed; nothing stored. Only `/register` calls the dashboard. |

Error bodies keep the existing `{"code", "message"}` shape.

## Node endpoint

### `POST /api/v1/equipment/authorize` (replaces `authorize-user`)

```json
{"uid": "04A1B2C3D4"}
```

```json
{"allowed": true, "reason": "ALLOWED", "training_level": 2, "required_level": 1}
```

Deny reasons, checked in this order (all return 200 with `"allowed": false`):

1. `EQUIPMENT_UNAVAILABLE`: `equipment.status` is not available.
2. `NO_ACTIVE_VISIT`: no active visit on this UID. Covers unknown, revoked, checked-out, and expired cards alike.
3. `INSUFFICIENT_TRAINING`: snapshot level below `equipment.minimum_training_level`.

This endpoint uses the ops database only and never calls the dashboard. What a node does when a student checks out mid-use is the node's decision; the next `authorize` call is denied.

## Dashboard endpoint (request to the dashboard team)

`GET …/training-level/{student_number}`, authenticated with a **service credential** such as an API key. User session tokens expire after 7 days, so they don't work for a service.

- 404: no account.
- 200: `{"training_level": 0, "account_status": "ACTIVE"}`, where `account_status` is one of the dashboard's Active / Locked / Suspended / Banned.
- To confirm with them: level 0 means general induction is not complete. `experience_level` is self-reported at signup and must not be used.

Ops calls it through one function, `get_training_level(student_number)`. Stub that function until the endpoint exists.

## Ops data changes (one forward Alembic migration)

- **`visits`:** add `uid` (nullable, indexed), `expires_at` (UTC, nullable), and `training_level` (nullable). The columns are nullable only because legacy loan visits have no values. Check-out reuses the existing `ended_at`, `status = CLOSED`, and `checkout_method = KIOSK` (`app/enums.py`). A visit with `ended_at` NULL and a past `expires_at` expired without a tap-out.
- **`revoked_cards`:** `uid` (primary key), `revoked_at`. Never deleted.
- **`kiosk_requests`:** `request_id` (primary key), `op`, `uid`, `student_number`, `outcome`, `reason`, `expires_at`, `created_at`.
- No `card_registrations` table.
- Delete `app/services/dashboard.py` and the `DashboardUser` model. They read a `users.student_number` column, but the dashboard's column is `student_id`.
- Leave the lending tables and routes alone for now; nothing will call them.
- **Identifiers:** UIDs are uppercase hex, as read. Student numbers are 9-digit strings at the API and integers in the database, matching the dashboard's `student_id`. Reject anything that isn't digits.

Old UIDs stay in visit history. If the retention policy later requires removing them, add one nightly `UPDATE visits SET uid = NULL WHERE expires_at <= now()`. Access never depends on that job running.

## Kiosk-side changes

- `ActivateUid` gains `student_number`; `machine.py` passes `ctx.observed_student_number`.
- Outcomes: add `CHECKED_OUT`; remove `ACTIVATED` and `ALREADY_ACTIVE` (nothing produces them). The machine accepts only `CHECKED_OUT`, `UNREGISTERED`, `DENIED`, and `UID_CONFLICT` from `ActivateUid`; anything else holds in `OUTCOME_UNKNOWN`.
- **Temporary (Friday):** the controller emits `IdentityConfirmed` immediately after each `CardRead`, marked `TODO(same-card)`. The state machine already holds an early confirmation during `ACTIVATING` and moves from `UNREGISTERED` to `RegisterAndActivate`, so nothing else in the machine changes.
- **HTTP to events:**
  - 200 → `BackendResult(op, Outcome[body["outcome"]], reason)`. Ops sends enum names (`"CHECKED_OUT"`); the kiosk's enum values are lowercase, so look up by name.
  - Error response from ops with a JSON `code` → nothing was written → `BackendError(NOT_SENT)`. Rename this later to a "confirmed no write" kind.
  - Timeout or dropped connection → `BackendError(UNKNOWN)`.
- The pending-operation file stores the `request_id`. On startup, the kiosk calls `GET /kiosk/requests/{request_id}` to resolve it.

## Outcome coverage

| Kiosk outcome | Produced by |
|---|---|
| `CHECKED_OUT` | `/activate` rule 3 |
| `UNREGISTERED` | `/activate` rule 4 |
| `REGISTERED_AND_ACTIVE` | `/register` rules 6 and 8 |
| `REPLACED_AND_ACTIVE` | `/register` rule 7 |
| `UNKNOWN_STUDENT`, `MISSING_INDUCTION` | `/register` rule 3 |
| `DENIED` | Revoked card (both routes, rule 2); suspended or banned account (`/register` rule 3) |
| `UID_CONFLICT` | `/activate` rule 3, `/register` rule 5 |
| `READ_AGAIN`, `SESSION_EXPIRED` | Kiosk-local; never sent by ops |
