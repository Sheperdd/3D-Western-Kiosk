# Python core with a Chromium-kiosk web UI; scan-driven, output-only displays

> **Partially superseded, 2026-09-16:** [ADR-0005](0005-student-card-registration-and-daily-activation.md) removes the motors and lending interaction. The Python/Chromium and scan-driven, output-only architecture direction remains. Two displays are retained; the current plan assigns student interaction to display 1 and general instructions/system status to display 2. The original hardware and workflow description below is historical, not implementation status.

A single Python process owns the hardware (student-card reader, the shared makerspace-card reader, iris and drawer motors) and the interaction state machine, exposing a local API/websocket. The user interface is a web app (HTML/JS) running full-screen in Chromium kiosk mode on the display(s). The displays are **output-only** — not touchscreens — and every user input arrives through a card scan (student card, makerspace card, or the student's phone scanning the on-screen training QR).

We chose this over a pure-Python native GUI (PyQt/Kivy): the existing code is already Python (`kasa`, asyncio), keeping hardware orchestration there avoids a rewrite, while a web UI gives richer, easier layout, QR rendering, and state-driven screens. The cost is running a browser on the Pi and a small local transport between the Python core and the UI.

Making the displays output-only follows from the interaction model — the whole flow is driven by scans, so a touch layer would add hardware and input paths the design never needs.
