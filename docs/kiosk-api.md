# Kiosk API (for the entrance kiosk)

How the entrance kiosk talks to the access gatekeeper on the makerspace PC. One call: the student taps their Western card, the
kiosk sends the card's UID and student number, and the gatekeeper answers checked in, checked out or denied, with the words
to show on screen.

- The binding source is the wire contract, [`specs/gatekeeper-contract.md`](../../makerspace-platform/docs/specs/gatekeeper-contract.md) section 1.1 (and
  section 4 for reason codes). This page is the kiosk-only guide to it. If they ever disagree, the contract wins.
- Every example reply below is real output from the gatekeeper (test stack, 2026-10-21).

## At a glance

| | |
|---|---|
| Base URL | `http://<gatekeeper address>:8080` (on the makerspace PC: `GK_BIND_ADDRESS`; in the test stack: `http://127.0.0.1:18080`) |
| Call | `POST /v1/kiosk/tap` |
| Auth | Header `X-Device-Key: <kiosk key>` |
| Body | JSON `{"uid": "04A1B2C3D4E5F6", "studentNumber": 251000123}` |
| Reply | `200` JSON, also for refusals (a refusal is an answer, not an error) |
| Speed | A few milliseconds on the PC; well under 200 ms over the network is the target |
| Internet | Not needed. The gatekeeper answers from its local copy and syncs with the backend on its own. |
| TLS | None. Plain HTTP on the private reader network only, never over campus Wi-Fi or the internet. |

## Getting a kiosk key

An admin registers the kiosk in the dashboard (Admin > Access System > Devices, kind **Kiosk**), or through the admin API:

```text
POST /api/v1/admin/access/devices
{"gatekeeperId": 1, "deviceKey": "entrance-kiosk", "kind": "KIOSK", "name": "Entrance kiosk"}
```

The reply shows the kiosk's `key` **once**. Store it on the kiosk as a secret (an env var or a file readable only by the
kiosk's user). Never commit it or paste it into chat. A lost or leaked key is replaced with `POST /devices/{id}/rotate-key`;
the old key stops working within seconds. The gatekeeper checks keys offline, so a new kiosk works as soon as the gatekeeper
has synced (seconds).

## The request

```http
POST /v1/kiosk/tap HTTP/1.1
Content-Type: application/json
X-Device-Key: <kiosk key>

{"uid": "04A1B2C3D4E5F6", "studentNumber": 251000123}
```

| Field | Type | Rules |
|---|---|---|
| `uid` | string | The card's UID in hex, 2 to 40 hex digits. Send it **uppercase with no separators** (`04A1B2C3D4E5F6`). The gatekeeper also accepts `04:a1:b2...`, `04-A1...` or spaces and cleans them up. |
| `studentNumber` | **integer** | The student number read from the same card. Must be a JSON number, not a string (`"251000123"` is rejected with `422`). |

## The reply

A check-in by a student with one machine training:

```json
{
  "v": 1,
  "result": "CHECKED_IN",
  "reason": null,
  "message": "Welcome, Sam.",
  "student": {"studentNumber": 251900001, "firstName": "Sam", "lastName": "Tester"},
  "orientation": {"status": "ACTIVE", "allowedUntil": null, "message": null},
  "certifications": [
    {"trainingId": 2, "title": "3D Printing", "status": "ACTIVE", "allowedUntil": null, "reason": null, "message": null}
  ],
  "notices": [],
  "cardLinked": true,
  "visitId": "0c8fe347-425f-4ae1-aaea-3ffc92cd9b58",
  "serverTime": "2026-10-21T18:44:22.803Z"
}
```

| Field | Meaning | What the kiosk does with it |
|---|---|---|
| `v` | Format version, `1` | Ignore fields you don't know; new optional fields may appear at any time. |
| `result` | `CHECKED_IN`, `CHECKED_OUT`, `DENIED` or `IGNORED_DUPLICATE` | Pick the screen (welcome, goodbye, refused). See below for `IGNORED_DUPLICATE`. |
| `reason` | `null` unless `DENIED`; then a code from the table below | Optional: an icon or colour per reason. Don't build your own wording from it; use `message`. |
| `message` | One friendly sentence, ready to show | **Show it as the main text.** The wording comes from the backend and may change. |
| `student` | `{studentNumber, firstName, lastName}`, or `null` if unknown | Name on screen. |
| `orientation` | `{status, allowedUntil, message}` or `null` | Status is `ACTIVE`, `REFRESHER_DUE` or `BLOCKED`. Mostly informational; the decision is already in `result`. |
| `certifications[]` | Every machine training the student has a record for: `{trainingId, title, status, allowedUntil, reason, message}` | Optional list on the welcome screen ("You can use: 3D Printing"). `status` is `ACTIVE` or `REFRESHER_DUE` (usable) or `BLOCKED` (not usable, `reason` says why). |
| `notices[]` | Extra lines, e.g. "Laser Cutter: time for a quick refresher. Your access still works." | Show them under the main message. Often empty. |
| `cardLinked` | `true` when this card is linked to the student | The first accepted tap of a new card links it automatically; nothing to do. |
| `visitId` | The visit this tap opened or closed (`null` when denied) | Logging only. |
| `serverTime` | The gatekeeper's clock (UTC) | Optional: set the kiosk clock from it. |

### Results

| `result` | When | Show |
|---|---|---|
| `CHECKED_IN` | The student had no open visit and passed every check | `message` ("Welcome, Sam."), plus `notices` |
| `CHECKED_OUT` | The student already had an open visit | `message` ("Goodbye, Sam."). Their machine sessions are closed too, but a machine still drawing working power is never cut. |
| `DENIED` | A check failed; nothing changed | `message` (it says why and what to do) |
| `IGNORED_DUPLICATE` | The **same card** was tapped again on this kiosk within the debounce window (admin setting `tapDebounceSeconds`, default 3 s), whatever the first answer was, refusals included | Keep showing the previous answer. The reply repeats it (same `message`, `reason`, `visitId`), so you can simply render it again. |

A tap toggles: no open visit means check-in, an open visit means check-out. There is no separate "check out" call.

### Reason codes for `DENIED`

| `reason` | Means |
|---|---|
| `UNKNOWN_STUDENT` | The student number isn't in the system (not signed up yet). |
| `ORIENTATION_REQUIRED` | Orientation can't be used: not finished, lapsed or expired (`allowedUntil` passed). Everyone needs it, staff included. `message` says which. |
| `ORIENTATION_NOT_CONFIGURED` | No orientation training is published, so nobody can check in ("Orientation isn't set up yet, please see staff"). No orientation QR: there is nothing to take yet. |
| `EMAIL_NOT_VERIFIED` | The account's email isn't verified yet. |
| `ACCOUNT_SUSPENDED`, `ACCOUNT_BANNED` | The account is blocked. |
| `DATA_STALE` | The gatekeeper has been offline from the backend longer than the admin allows (only if that limit is set). |

Example (`200`):

```json
{"v": 1, "result": "DENIED", "reason": "UNKNOWN_STUDENT",
 "message": "We can't find your account yet. Sign up on the website first.",
 "student": null, "orientation": null, "certifications": [], "notices": [],
 "cardLinked": false, "visitId": null, "serverTime": "2026-10-21T18:44:16.610Z"}
```

## Errors (not `200`)

| HTTP | Body | Cause | Kiosk should |
|---|---|---|---|
| `401` | `{"v":1,"error":"DEVICE_KEY_INVALID"}` | Missing, wrong or rotated key, or the device isn't a kiosk | Show "Kiosk not set up, please see staff" and log it. Retrying won't help. |
| `422` | `{"detail":[{"loc":["body","studentNumber"],"msg":"Input should be a valid integer",...}]}` | Malformed body: `studentNumber` not an integer, `uid` not 2-40 hex digits, missing field | A kiosk bug or a bad card read: ask the student to tap again; log the body. |
| no reply / timeout | | Network or PC down | See below. |

## Rules for the kiosk code

1. **Timeout about 2 s.** If no reply arrives, show "Couldn't reach the system, please tap again" and **never** assume a
   check-in or check-out happened.
2. **Retry safely.** A tap is not idempotent (it toggles), but the debounce makes a quick retry safe: resend the *same* tap
   **once, immediately** (well inside the 3 s window). If the first one did land, the retry gets `IGNORED_DUPLICATE` with the
   first answer, which is exactly what you want to show. Don't retry later than that, or a second tap may check the student
   out again.
3. **Show `message` and `notices` as given.** Don't hard-code wording per reason; the backend owns it.
4. **Ignore unknown fields and unknown `reason` codes** (show `message` anyway).
5. **One tap, one request.** Don't send a request per card-reader event if your reader repeats reads; the debounce absorbs
   repeats within 3 s, but your screen should too.
6. **Keep the key secret** and only ever send it over the reader network.

## Checking the gatekeeper is up

`GET /healthz` (no key needed):

```json
{"ok": true, "version": "0.1.0", "hasSnapshot": true, "journalPending": 0}
```

`hasSnapshot: false` means the gatekeeper hasn't synced with the backend even once yet: every tap would be `UNKNOWN_STUDENT`.
Show "Starting up, please wait" until it's `true`. `journalPending` is the number of events not yet uploaded (informational).

## Trying it now, without the real PC

Run the test stack on any Mac or Linux/WSL2 machine (needs Docker, Java 21 via `mise install`, about 3 GB of memory):

```bash
cd gatekeeper
uv run gk-stack up      # throwaway backend + gatekeeper with fake plugs, kiosk already registered
```

- Gatekeeper: `http://127.0.0.1:18080` (this machine only).
- Kiosk key: `.local/stack.json`, field `kiosk.key` (owner-only file; don't paste it anywhere).
- Test students (card UID / student number): Sam `04A1B2C3D4E501` / `251900001` and Alex `04A1B2C3D4E502` / `251900002`
  (orientation + 3D Printing); Robin `04A1B2C3D4E503` / `251900003` (orientation only). Any other student number gives
  `UNKNOWN_STUDENT`.
- `uv run gk-stack down` throws everything away.

From the shell:

```bash
curl -s -H "X-Device-Key: $KIOSK_KEY" -H 'Content-Type: application/json' \
  -d '{"uid":"04A1B2C3D4E501","studentNumber":251900001}' http://127.0.0.1:18080/v1/kiosk/tap
```

A minimal Python client for the Pi (uses `requests`):

```python
import os
import requests

GATEKEEPER = os.environ["GK_URL"]          # e.g. http://192.168.50.2:8080
KIOSK_KEY = os.environ["GK_KIOSK_KEY"]     # the key shown once at registration


def tap(uid: str, student_number: int) -> dict:
    """Send one tap; returns the reply, or a local 'try again' answer if the gatekeeper can't be reached."""
    body = {"uid": uid.replace(":", "").upper(), "studentNumber": int(student_number)}
    headers = {"X-Device-Key": KIOSK_KEY}
    for _attempt in range(2):  # one immediate retry is safe: a duplicate within 3 s returns the first answer
        try:
            r = requests.post(f"{GATEKEEPER}/v1/kiosk/tap", json=body, headers=headers, timeout=2)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            return {"result": "ERROR", "message": "Kiosk not set up, please see staff."}
        return {"result": "ERROR", "message": "Please tap your card again."}  # 422: bad read
    return {"result": "ERROR", "message": "Couldn't reach the system, please tap again."}
```

To reach a gatekeeper on another machine (the real Pi talking to the PC), both must be on the same private reader network,
and the gatekeeper must be published on that network's address (`GK_BIND_ADDRESS` in `gatekeeper/.env`). See
[`gatekeeper-hardware-test.md`](../../makerspace-platform/docs/gatekeeper-hardware-test.md).
