# Kiosk owns the card lifecycle only; the backend is the source of truth

> **Partially superseded, 2026-09-16:** [ADR-0005](0005-student-card-registration-and-daily-activation.md) replaces the lending lifecycle with student-card registration and daily activation. Backend authority and tool-side enforcement remain. The original reasoning below is historical.

The kiosk is responsible for the makerspace-card lifecycle (dispense, link, unlink, return) and nothing else. Each tool has its own reader+lock that queries the backend to enforce per-student training at unlock time — the kiosk never controls tool power. The backend owns both the training data (read: student number → training level) and the card↔student link (write/delete), so it is the single source of truth that both the kiosk and the tool readers consult.

We chose this over making the kiosk the central gatekeeper (toggling tool power itself, as the early `kiosk_test.py` Kasa-plug spike did) and over encoding permissions onto the card for offline tool reads. Centralising enforcement in the backend keeps tools independent of kiosk uptime, lets training changes take effect immediately, and avoids trusting/writing card-resident permissions. The trade-off is that every tool unlock depends on backend availability.
