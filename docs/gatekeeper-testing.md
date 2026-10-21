# Testing the kiosk against the gatekeeper

How to take the kiosk from the laptop to the makerspace PC in four stages. Each stage adds one new thing, so a failure
points at that thing. The platform's own checklist for the PC, plugs and stations is
[`gatekeeper-hardware-test.md`](../../makerspace-platform/docs/gatekeeper-hardware-test.md) (Troy's); this page covers
the kiosk side and the network it needs.

## Before you start

- **Troy owns the gatekeeper and its hardware checklist** and wants the results (his step 7). Don't edit
  `makerspace-platform` without asking.
- **The makerspace PC also runs the students' production dashboard backend** (Docker, port 8000, MariaDB on 3306).
  Its MariaDB has `restart: no`, no data volume and no backups. A PC reboot, a Docker Desktop restart or `wsl --shutdown`
  stops it and it does not come back by itself. Agree a time with its owner before any of those. Never run anything
  else on port 8000 there.
- **No backend is hosted yet.** The gatekeeper will not start without `GK_BACKEND_URL` and a gatekeeper token, so every
  stage needs a dev backend somewhere. Its dev profile has well-known admin passwords: private networks only, and shut
  it down afterwards.
- **The reader network needs Western IT's OK** before it runs in the space.

## The network

The reader network is its own router with an empty WAN port: no internet. Addresses from
[`kasa-plug-setup.md`](../../makerspace-platform/docs/kasa-plug-setup.md):

```
                 internet / campus LAN
                          │
                  ┌───────┴────────┐
                  │  Makerspace PC │  NIC 1: normal network (outbound HTTPS to the backend)
                  │   gatekeeper   │  NIC 2: 192.168.50.2/24, NO default gateway
                  └───────┬────────┘
        reader router 192.168.50.1 (WAN empty, 2.4 GHz WPA2 for the plugs)
            ┌─────────────┼──────────────┐
      Pi kiosk .10   plugs .20–.39   ESP32 stations .40–.59
```

- **PC, two networks.** A second NIC (a USB Ethernet adapter is fine) or Wi-Fi to the reader router. Give it the fixed
  address `192.168.50.2/24` and **leave its default gateway empty**. With a gateway the PC may send internet traffic to
  the reader router, which has none, and backend sync breaks. Linux with DHCP: `nmcli connection modify <conn>
  ipv4.never-default yes`.
- **PC firewall.** Allow inbound TCP 8080 on the reader NIC only. Windows: mark that network Private, add an inbound
  rule for 8080.
- **Docker binds only `GK_BIND_ADDRESS`.** If the reader NIC is down when Docker starts (router off, cable out), the
  gatekeeper cannot bind its port. Power the router with the PC and check `docker compose ps` after a boot. For the same
  reason `curl localhost:8080` on the PC fails; use `curl http://192.168.50.2:8080/healthz`.
- **Pi.** Ethernet to the reader router, `.10` (DHCP reservation or static).
  - No internet there: finish every `apt` and `uv` install first.
  - No time source either, and a Pi 4 has no battery clock. Only kiosk log timestamps drift; the kiosk never sends a time.
  - Don't keep it on campus Wi-Fi too. The device key must never cross that network.
- **Laptop.** Join the reader network to SSH into the Pi; you have no internet while you are on it.

## Stage A: laptop only, no Pi

Proves the HTTP client against a real gatekeeper.

1. In WSL2 (Docker Desktop, Java 21 via `mise install`, about 3 GB free memory):
   `cd makerspace-platform/gatekeeper && uv run gk-stack up`. The first start compiles the backend; allow a few minutes.
2. The kiosk key is in `gatekeeper/.local/stack.json`, field `kiosk.key`. Don't paste it anywhere.
3. Start the kiosk in demo mode, pointed at the stack:
   - PowerShell: `$env:GK_URL="http://127.0.0.1:18080"; $env:GK_KIOSK_KEY="<key>"; uv run python -m kiosk`
   - bash: `GK_URL=http://127.0.0.1:18080 GK_KIOSK_KEY=<key> uv run python -m kiosk`

   Windows reaches a WSL2 server on localhost by default; if it doesn't, run the kiosk inside WSL.
4. Open `http://127.0.0.1:8000/?display=1`. Expect the ready screen (not offline) and no demo badge, then
   "Welcome, Sam." at about 10 s and "Goodbye, Sam." at about 30 s.
5. Temporarily set `DEMO_STUDENT_NUMBER = "251999999"` in `kiosk/__main__.py`. Expect a denial with the signup QR. Revert it.
6. Start with a wrong key. Expect "Kiosk not set up" and a log line naming `GK_KIOSK_KEY`.
7. While idle, `uv run gk-stack down`. Expect the offline screen within about 5 s.

## Stage B: Pi with real cards, gatekeeper still on the laptop

Proves the readers end to end with no network changes, through an SSH reverse tunnel.

1. Stack up on the laptop (stage A). Then `ssh -R 18080:127.0.0.1:18080 <user>@<pi>.local`: while that session is
   open, the Pi's `127.0.0.1:18080` reaches the laptop's gatekeeper.
2. On the Pi, stop the service if it is installed (`sudo systemctl stop kiosk`), then:
   `GK_URL=http://127.0.0.1:18080 GK_KIOSK_KEY=<key> python -m kiosk --device <omnikey path>`.
3. Tap your own card. Expect a denial with the signup QR: you are not in the test data. That still proves the readers,
   the HTTP call and the screens together.

## Stage C: the real network, laptop standing in for the PC

Proves the network, the port binding and the firewall without touching the shared PC.

1. Set up the reader router as in [The network](#the-network). Pi on it at `.10`; laptop on it as `192.168.50.2`,
   no gateway.
2. On the laptop:
   1. Start the platform dev backend ([`dev-setup.md`](../../makerspace-platform/docs/dev-setup.md)).
   2. `cd makerspace-platform/gatekeeper && cp .env.example .env`. Set `GK_BIND_ADDRESS=192.168.50.2` and
      `GK_BACKEND_URL=http://host.docker.internal:8000`, plus `GK_ALLOW_INSECURE_BACKEND=true` if it rejects plain http.
   3. In the dev dashboard (Admin > Access System) or Swagger, register a gatekeeper and copy its token into `.env`.
   4. Register a kiosk device under that gatekeeper (kind Kiosk). Its key is shown once.
   5. `docker compose up -d --build`. `docker compose logs -f gatekeeper` should show "snapshot applied".
3. For a real check-in, your account must exist in that dev backend with a verified email and orientation ACTIVE. Ask
   Troy how best to seed it.
4. From the Pi: `curl http://192.168.50.2:8080/healthz` shows `"hasSnapshot": true`. If this fails, the problem is the
   network, the firewall or the binding, not the kiosk.
5. On the Pi, create the settings file (root only; systemd reads it before switching to `kioskapp`):
   ```bash
   sudo install -d /etc/kiosk
   sudo install -m 600 -o root -g root /dev/null /etc/kiosk/kiosk.env
   sudoedit /etc/kiosk/kiosk.env
   ```
   Contents:
   ```
   GK_URL=http://192.168.50.2:8080
   GK_KIOSK_KEY=<the kiosk key>
   ```
6. Install the service: `sudo cp deploy/kiosk.service /etc/systemd/system/ && sudo systemctl daemon-reload &&
   sudo systemctl restart kiosk`.
7. Run the [checklist](#kiosk-checklist).

## Stage D: the makerspace PC

With Troy, following his `gatekeeper-hardware-test.md`.

1. Before you start:
   - Find out whether the PC runs Linux or Windows.
   - Agree a time with the owner of the production dashboard backend.
   - Settle where the dev backend runs. Not on port 8000 on that PC.
2. Set up the PC's reader NIC exactly as in stage C, then do steps 1–3 of the hardware test.
3. A kiosk key belongs to one gatekeeper. If the PC gets its own gatekeeper registration, register the kiosk under it,
   update `/etc/kiosk/kiosk.env` and `sudo systemctl restart kiosk`.
4. Run the [checklist](#kiosk-checklist), then the hardware test's script (steps 6.1–6.10).
5. Send Troy the results (hardware test step 7), including how fast the kiosk felt.

## Kiosk checklist

For stages C and D. Watch the kiosk with `journalctl -u kiosk -f` and the gatekeeper with
`docker compose logs -f gatekeeper`.

| # | Do | Expect |
|---|---|---|
| 1 | Start `kiosk.service` | Ready screen within about 5 s, no demo badge; the log says "Gatekeeper online." |
| 2 | Tap your card | "Welcome, \<name\>."; the dashboard's Live view shows you checked in |
| 3 | Tap again after the screen clears | "Goodbye, …"; Live shows you gone |
| 4 | Tap the card of someone not signed up | Denial with the signup QR |
| 5 | Wrong key in `kiosk.env`, restart the service | "Kiosk not set up"; the log names `GK_KIOSK_KEY` |
| 6 | `docker compose stop gatekeeper` while idle | Offline within about 5 s; `docker compose start gatekeeper` brings back the ready screen |
| 7 | Unplug the PC's reader cable during a check | "Couldn't reach the system" within about 4 s, then offline |
| 8 | Unplug the PC's **internet** cable only | Taps still work (the gatekeeper answers from its local copy) |
| 9 | Time from tap to result screen | Well under a second (the HTTP target is under 200 ms) |
| 10 | Reboot the **Pi** | The kiosk comes back by itself |
