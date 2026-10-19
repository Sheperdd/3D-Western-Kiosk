# Ops API: kiosk and machine nodes

**Status:** sketch for the Friday 2026-10-23 supervised test. Owner: Shane (taking over ops-backend). Move this file to `ops-backend/docs/` once the takeover is formal. It supersedes the open "to agree" items in [backend-agreement.md](backend-agreement.md) where they conflict.

## Decisions

- Ops stores **card registrations (UID → student number)**, visits, and kiosk request results. It does not read dashboard tables.
- Training level comes from a **dashboard endpoint** (built by the dashboard team this week): student number in, training level out.
- At kiosk activation, ops takes a **snapshot** of the training level and stores it on the visit. Machine nodes check ops only and never wait on the dashboard.
- Tool rule: the existing cumulative level. Allowed when `visit.training_level >= equipment.minimum_training_level`.
- **Friday only: the kiosk auto-registers** UID + student-number pairs without same-card verification. This is acceptable for a supervised test only; see [ADR-0005](adr/0005-student-card-registration-and-daily-activation.md) and the [TODO](../TODO.md#same-card-identity-options--investigation-deferred).
- Activation expires at the next America/Toronto midnight, enforced by an `expires_at` timestamp. No midnight job is needed.

## Authentication

Uses the existing `ApiToken` bearer tokens (`app/api/dependencies/auth.py`).

- A token with `equipment_id` set belongs to a machine node; the equipment comes from the token.
- A token without `equipment_id` belongs to the kiosk.
- Kiosk routes reject equipment tokens. Equipment routes reject tokens without equipment (403).

ponytail: the token's role is inferred from `equipment_id`. Add an explicit role column when a third client type appears.

## Kiosk endpoints

Whenever ops makes a decision, it answers **200 with an `outcome`**. Any other status is a technical failure, and ops has rolled back: nothing was written.

### `POST /api/v1/kiosk/activate`

```json
{"request_id": "6f1c…-uuid4", "uid": "04A1B2C3D4", "student_number": "250123456"}
```

```json
{"request_id": "6f1c…", "outcome": "ACTIVATED", "reason": null, "expires_at": "2026-10-24T04:00:00Z"}
```

Rules, in order:

1. **Replay:** if `request_id` is already stored, return the stored result. If the same ID arrives with a different body, return 409 `REQUEST_ID_REUSED`.
2. **Card lookup:** an unknown UID returns `UNREGISTERED`. A revoked UID returns `DENIED` with reason `CARD_REVOKED`, so a replaced card cannot register itself again.
3. **Owner check:** if the UID's registered student differs from the `student_number` sent, return `UID_CONFLICT`. This is a cheap swap check on repeat visits.
4. **Eligibility** (dashboard): no account → `UNKNOWN_STUDENT`; suspended or banned → `DENIED`; level 0 → `MISSING_INDUCTION`.
5. **Visit:** if the student already has a visit with `expires_at > now`, refresh its `training_level` snapshot and return `ALREADY_ACTIVE`. Otherwise create a visit with `expires_at` set to the next Toronto midnight (stored in UTC) and the level snapshot, and return `ACTIVATED`.
6. Store the result row **in the same transaction** as the writes.

### `POST /api/v1/kiosk/register`

Same body and the same replay rule.

1. Check eligibility first. An ineligible student is never registered (`UNKNOWN_STUDENT`, `MISSING_INDUCTION`, `DENIED`).
2. UID registered to another student → `UID_CONFLICT`. Ownership never transfers automatically. Revoked UID → `DENIED` with reason `CARD_REVOKED`.
3. UID already registered to this student → treat it as registered and continue.
4. Student holds a different active UID → set that UID's `revoked_at`, insert the new one, and return `REPLACED_AND_ACTIVE`. Otherwise insert and return `REGISTERED_AND_ACTIVE`.
5. Activate as in rule 5 of `/activate`, all in one transaction. Lock the student's registration rows (`SELECT … FOR UPDATE`): MariaDB has no partial unique index to enforce "one active card per student".

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
| 503 | `DASHBOARD_UNAVAILABLE` | Training lookup failed; nothing stored. |

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
2. `CARD_NOT_REGISTERED`: UID unknown or revoked.
3. `NO_ACTIVE_VISIT`: no visit with `expires_at > now`.
4. `INSUFFICIENT_TRAINING`: snapshot level below `equipment.minimum_training_level`.

This endpoint uses the ops database only and never calls the dashboard.

## Dashboard endpoint (request to the dashboard team)

`GET …/training-level/{student_number}`, authenticated with a **service credential** such as an API key. User session tokens expire after 7 days, so they don't work for a service.

- 404: no account.
- 200: `{"training_level": 0, "account_status": "ACTIVE"}`, where `account_status` is one of the dashboard's Active / Locked / Suspended / Banned.
- To confirm with them: level 0 means general induction is not complete. `experience_level` is self-reported at signup and must not be used.

Ops calls it through one function, `get_training_level(student_number)`. Stub that function until the endpoint exists.

## Ops data changes (one forward Alembic migration)

- **`card_registrations`:** `uid` (unique), `student_number`, `registered_at`, `revoked_at` (nullable).
- **`visits`:** add `expires_at` (UTC) and `training_level`. A visit is active when `expires_at > now`.
- **`kiosk_requests`:** `request_id` (primary key), `op`, `uid`, `student_number`, `outcome`, `reason`, `expires_at`, `created_at`.
- Delete `app/services/dashboard.py` and the `DashboardUser` model. They read a `users.student_number` column, but the dashboard's column is `student_id`.
- Leave the lending tables and routes alone for now; nothing will call them.
- **Identifiers:** UIDs are uppercase hex, as read. Student numbers are 9-digit strings at the API and integers in the database, matching the dashboard's `student_id`. Reject anything that isn't digits.

## Kiosk-side changes

- `ActivateUid` gains `student_number`; `machine.py` passes `ctx.observed_student_number`.
- **Temporary (Friday):** the controller emits `IdentityConfirmed` immediately after each `CardRead`, marked `TODO(same-card)`. The state machine already holds an early confirmation during `ACTIVATING` and moves from `UNREGISTERED` to `RegisterAndActivate`, so nothing else in the machine changes.
- **HTTP to events:**
  - 200 → `BackendResult(op, outcome, reason)`.
  - Error response from ops with a JSON `code` → nothing was written → `BackendError(NOT_SENT)`. Rename this later to a "confirmed no write" kind.
  - Timeout or dropped connection → `BackendError(UNKNOWN)`.
- The pending-operation file stores the `request_id`. On startup, the kiosk calls `GET /kiosk/requests/{request_id}` to resolve it.

## Outcome coverage

| Kiosk outcome | Produced by |
|---|---|
| `ACTIVATED`, `ALREADY_ACTIVE` | `/activate` rule 5 |
| `UNREGISTERED` | `/activate` rule 2 |
| `REGISTERED_AND_ACTIVE`, `REPLACED_AND_ACTIVE` | `/register` rules 3–4 |
| `UNKNOWN_STUDENT`, `MISSING_INDUCTION` | Eligibility (`/activate` rule 4, `/register` rule 1) |
| `DENIED` | Suspended or banned account, or revoked card |
| `UID_CONFLICT` | `/activate` rule 3, `/register` rule 2 |
| `READ_AGAIN`, `SESSION_EXPIRED` | Kiosk-local; never sent by ops |
