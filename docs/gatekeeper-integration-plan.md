# Plan: connect the kiosk to the gatekeeper

## Context
Gatekeeper (`makerspace-platform/gatekeeper`) replaces ops-backend (decision D-18). The kiosk core was built for
`docs/ops-api.md`: two calls (`ActivateUid` → `UNREGISTERED` → `RegisterAndActivate`), daily registrations, request-ID
recovery. Gatekeeper exposes **one** call, `POST /v1/kiosk/tap` with `{uid, studentNumber:int}` + `X-Device-Key`, answering
`result` (`CHECKED_IN|CHECKED_OUT|DENIED|IGNORED_DUPLICATE`) + `reason` + ready-to-show `message`/`notices`.
Spec: `Kiosk/docs/kiosk-api.md`, binding contract `makerspace-platform/docs/specs/gatekeeper-contract.md` §1.1, §4.

Goal: kiosk on the Pi taps against the real gatekeeper and shows its answers.

Decisions taken:
- **Lost reply = follow contract.** One immediate retry; then show "Couldn't reach the system, please tap again" and
  return to ready. `OUTCOME_UNKNOWN` is deleted.
- **Gatekeeper scope:** fix `ORIENTATION_NOT_CONFIGURED` now; `CARD_CONFLICT` and revoked-card blocking are a later
  phase gated on Troy.
- Shane writes all code (AGENTS.md). One commit per step; tests updated in the same commit.

---

## Phase 0 — Decisions on paper (no code)
1. `docs/adr/0007-kiosk-talks-to-gatekeeper.md`: one call, toggle by student number, permanent card links, nightly
   reset at `nightlyResetTime` (default 03:00) not midnight, no request-ID recovery, backend owns wording. Supersedes
   ADR-0005, most of ADR-0006.
2. `CONTEXT.md` glossary: General induction→**Orientation**, Tool training→**Certification**, Tool reader→**Station**,
   Registration→**Card link** (permanent), Activation/active visit→**Check-in/open visit**, Daily access reset→**Nightly
   reset**, Backend→**Gatekeeper** (kiosk-facing).
3. `docs/plan.md`: rewrite R4, R5 (3 s debounce exists), R6 (no revocation by kiosk), R8, R11, R12 (name on display 1),
   R13 (kiosk is now the only mis-pair guard).
4. Mark `docs/ops-api.md` and `docs/backend-agreement.md` superseded (status line at top; don't delete history).
5. `docs/kiosk-api.md`: fix the broken `specs/…` links → `../../makerspace-platform/docs/specs/…`.

## Phase 1 — Gatekeeper fix: `ORIENTATION_NOT_CONFIGURED` (makerspace-platform)
- `gatekeeper/src/gatekeeper/engine.py` `_check_in_decision` (~line 332): when orientation is unusable and
  `user.orientation.reason == "ORIENTATION_NOT_CONFIGURED"`, return that reason instead of `ORIENTATION_REQUIRED`.
- Test in `gatekeeper/tests/` using `conftest.py` fixtures (snapshot user with orientation BLOCKED /
  `ORIENTATION_NOT_CONFIGURED`) → kiosk tap returns that reason.
- Remove the "today the gatekeeper reports that case as ORIENTATION_REQUIRED" note in `kiosk-api.md` (lines ~110-111).
- Check: `cd gatekeeper && uv run pytest && uv run ruff check .`

## Phase 2 — Collapse the kiosk core to one tap (`kiosk/events.py`, `kiosk/machine.py`)
Delete before adapting. Order inside the phase:
1. **Rename `session_id` → `tap_id`** (and `TimeoutName.SESSION` → `TAP`) — mechanical commit; avoids clash with
   gatekeeper `sessionId` (machine session).
2. **Delete the registration path:** `IdentityConfirmed`, `RegisterAndActivate`, `BackendOp`, states
   `AWAITING_IDENTITY`/`REGISTERING`/`OUTCOME_UNKNOWN`, `Context.confirmed_student_number`, `_register`, `_WAITING`
   entries, `_BACKEND_OUTCOMES` table. Drop matching tests in `tests/test_machine.py`, `test_controller.py`,
   `test_invariants.py`.
3. **Rename + reshape vocabulary:**
   - `Outcome` → `Result(StrEnum)` with **values = wire strings**: `CHECKED_IN`, `CHECKED_OUT`, `DENIED`,
     `IGNORED_DUPLICATE`; local-only `READ_AGAIN`, `SESSION_EXPIRED`→`TAP_EXPIRED`, `UNREACHABLE`, `NOT_SET_UP`.
   - `ActivateUid` → `Tap(tap_id, uid, student_number)`.
   - `BackendResult` → `GatekeeperResult(tap_id, result, reason, message, notices: tuple[str, ...], first_name)`.
     `reason` stays `str | None` (unknown codes must not crash).
   - `BackendError` → `GatekeeperError(tap_id, kind)`; `FailureKind` → `UNREACHABLE` (timeout/network),
     `BAD_REQUEST` (422), `BAD_KEY` (401).
   - `BackendOnline/Offline` → `GatekeeperOnline/Offline`; `KioskState.ACTIVATING` → `CHECKING`.
   - `Context.observed_student_number` → `student_number`; `pending_op` → `pending: bool`; add `message`, `notices`,
     `first_name` (filled from `GatekeeperResult`, cleared by `_end_session`).
4. **Machine rules after collapse** (`handle`):
   - `CardRead` in IDLE, valid → `CHECKING`, effects `[StartTimeout(TAP), Tap(...)]` (9-digit check stays).
   - `GatekeeperResult` in CHECKING → `_finish(result, …)`. `IGNORED_DUPLICATE` just renders its (repeated) message.
   - `GatekeeperError`: `UNREACHABLE` → `_finish(UNREACHABLE)`; `BAD_REQUEST` → `_finish(READ_AGAIN)`;
     `BAD_KEY` → `_finish(NOT_SET_UP)` (log it). Always clear `pending`.
   - Tap timeout while CHECKING → `_finish(UNREACHABLE)` (no hold).
   - Online/offline handling unchanged apart from names.
- Check: `uv run pytest`, `uv run ruff check .`, `uv run pyright`.

## Phase 3 — HTTP adapter (`kiosk/controller.py`)
- Replace `fake_activate_uid` / `fake_register_and_activate` / `DEMO_CHECKED_IN` with one `send_tap` coroutine.
- Use **aiohttp `ClientSession`** (already a dependency) — not `requests` from the doc example (blocks the loop).
  One session created in `__main__.main`, passed into `run`; `ClientTimeout(total=2)`.
- Body `{"uid": uid, "studentNumber": int(student_number)}`, header `X-Device-Key`.
- One immediate retry **only** on network error/timeout (contract rule 2). Mapping:
  200 → `GatekeeperResult` (unknown `result` string → `Result.DENIED` showing `message`; never show success on
  unknown); 401 → `BAD_KEY`; 422 → `BAD_REQUEST`; other status / 2nd failure → `UNREACHABLE`.
- Config from env: `GK_URL`, `GK_KIOSK_KEY` (read once at startup; fail fast if missing in hardware mode).
- `RESULT_DURATION_SECONDS` keyed by new `Result` values.
- Test: one `tests/test_gatekeeper_client.py` using `aiohttp.test_utils.TestServer` as a fake gatekeeper —
  200 / 401 / 422 / timeout-then-success (retry) / two timeouts.

## Phase 4 — Gatekeeper health → online/offline (`kiosk/controller.py` or `__main__.py`)
- Background task: `GET {GK_URL}/healthz` every ~5 s (2 s timeout). Online = `ok and hasSnapshot`.
  Put `GatekeeperOnline()` / `GatekeeperOffline()` on the queue **only on change**.
- Delete the hard-coded `queue.put_nowait(BackendOnline())` calls in `kiosk/__main__.py`.
- `hasSnapshot: false` → offline screen "Starting up, please wait" (prevents mass `UNKNOWN_STUDENT` → signup QR).

## Phase 5 — Displays (`kiosk/__main__.py` `update_display`, `kiosk/web/app.js`, `index.html`)
- Display 1 payload: `{state, result, reason, message, notices, firstName}`. Display 2 unchanged (no personal data).
- `app.js`: for gatekeeper results show `message` as the main text and `notices` as a list; tone from `result`
  (`CHECKED_IN`/`CHECKED_OUT` success, `DENIED` attention). QR keyed on `reason`: `UNKNOWN_STUDENT` → signup,
  `ORIENTATION_REQUIRED` → orientation; none for `ORIENTATION_NOT_CONFIGURED` or others. Local results
  (`READ_AGAIN`, `TAP_EXPIRED`, `UNREACHABLE`, `NOT_SET_UP`) keep hard-coded wording. Delete outcome entries for
  removed results and the `OUTCOME_UNKNOWN`/`AWAITING_IDENTITY`/`REGISTERING` states.
- Update `tests/test_display_ui.cjs`.

## Phase 6 — Deploy wiring
- Register the kiosk: dashboard Admin › Access System › Devices (kind KIOSK) or
  `POST /api/v1/admin/access/devices {"gatekeeperId":1,"deviceKey":"entrance-kiosk","kind":"KIOSK","name":"Entrance kiosk"}`.
  Key shown once.
- Pi: `/etc/kiosk/kiosk.env` with `GK_URL=http://<PC reader-network IP>:8080` and `GK_KIOSK_KEY=…`, owner root,
  mode 600 (systemd reads it as root before dropping to `kioskapp`). `deploy/kiosk.service`: add
  `EnvironmentFile=/etc/kiosk/kiosk.env`, resolve the `TODO(Wednesday)` line. Test stages: [gatekeeper-testing.md](gatekeeper-testing.md).
- Network: Pi and PC on the private reader network; PC's `GK_BIND_ADDRESS` = its reader-network address
  (`makerspace-platform/docs/gatekeeper-hardware-test.md`).

## Phase 7 — Later (gated on Troy; kiosk needs no change because it shows `message`)
1. `CARD_CONFLICT`: kiosk tap with a UID already linked to a different student → DENIED, no relink. Contract §1.1/§4
   first, then `engine.py kiosk_tap`, test.
2. Revoked cards: backend snapshot/`config.replace` carries deactivated UIDs; kiosk tap → DENIED `CARD_REVOKED`,
   never relinks. Contract → backend (Kotlin) → gatekeeper. Required before unsupervised use.
3. Kiosk card-removal detection (PN532 presence poll) so a held card stops toggling after the 3 s debounce.

---

## Verification
1. Unit: `uv run pytest` (kiosk), `node tests/test_display_ui.cjs`, `uv run ruff check .`, `uv run pyright`;
   gatekeeper `uv run pytest`.
2. End-to-end without hardware (WSL2/Docker, Java 21): `cd makerspace-platform/gatekeeper && uv run gk-stack up`;
   key from `.local/stack.json` `kiosk.key`. Run `GK_URL=http://127.0.0.1:18080 GK_KIOSK_KEY=… python -m kiosk`
   (demo mode: change the synthetic `CardRead`s in `__main__.py` to Sam `04A1B2C3D4E501`/`251900001`). Open
   `http://127.0.0.1:8000/?display=1`: expect "Welcome, Sam." then "Goodbye, Sam.". Also: an unknown number → signup QR;
   stop the gatekeeper → offline screen; wrong key → NOT_SET_UP; `uv run gk-stack down`.
3. Hardware: Pi on the reader network, real cards, check-in/out, measure tap→screen latency (<200 ms target), unplug
   the PC network → UNREACHABLE then offline screen; follow `gatekeeper-hardware-test.md`.
