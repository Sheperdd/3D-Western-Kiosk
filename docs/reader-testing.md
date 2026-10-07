# Two-reader bring-up on the Raspberry Pi 4

Goal: validate the UID-first, one-presentation arrangement recorded in [plan section 6](plan.md#6-reader-experiment-evidence-and-current-limitations). The setup uses **one USB student-number reader and one SPI UID reader connected to the Pi's GPIO header**, not two USB keyboards. Run these commands on the Pi, not in the Windows development terminal.

## Hardware baseline

The reported experiment used a Raspberry Pi 4, Raspberry Pi OS/Debian trixie, Python 3.13.5, and VS Code Remote SSH.

| Reader | Connection | Output and software |
|---|---|---|
| HID OMNIKEY 5427 G2, detected as OMNIKEY 5427 CK | USB, keyboard mode | Student-number digits and Enter through Linux input events; Python uses `evdev`. |
| Elechouse NFC Module V3 / PN532 | SPI through the Pi's GPIO header | UID bytes through Adafruit Blinka and `adafruit-circuitpython-pn532` in a virtual environment; not a keyboard event stream. |

The reported PN532 setup used SPI switches **1 OFF, 2 ON**, 3.3 V, ground, MOSI/MISO/SCLK, and **software chip select GPIO5 (physical pin 29), not CE0**. Firmware 1.6 was reported. The wiring below follows that arrangement.

## Wiring the NFC module to the Pi

These instructions are for the **Elechouse NFC Module V3 / PN532 and Raspberry Pi 4's 40-pin header**. Check the module's printed labels rather than assuming connector order from another PN532 board.

1. Shut down the Pi and disconnect its power before changing wires or module switches.
2. Set the module's interface switches to **1 OFF, 2 ON (SPI)**. Use the printed ON marking to identify switch direction.
3. Connect the six wires below. **Physical pin numbers are header positions; GPIO numbers are signal names. GPIO5 means physical pin 29, not physical pin 5.** Locate pin 1 using the official header diagram before counting.

| NFC module label | Raspberry Pi signal | Physical header pin |
|---|---|---|
| `VCC` | 3.3 V power | **1** |
| `GND` | Ground | **6** |
| `MOSI` | GPIO10 / SPI0 MOSI | **19** |
| `MISO` | GPIO9 / SPI0 MISO | **21** |
| `SCK` | GPIO11 / SPI0 SCLK | **23** |
| `SS` [chip select] | GPIO5, controlled by software | **29** |

Connect MOSI to MOSI and MISO to MISO; do not cross them. Leave CE0 (physical pin 24) unused for this reader. The Pi script must select **GPIO5** as its chip-select output to match the wire.

4. Check every connection before restoring power. Use the **3.3 V** supply shown here; do not connect a 5 V supply to a GPIO signal pin. Keep the OMNIKEY on USB.
5. Start the existing PN532 SPI diagnostic. Confirm a firmware response and a UID read before testing the combined reader sequence. If initialization fails, recheck switch settings, power/ground, and the script's chip-select configuration with power disconnected before moving wires.

Module voltage, SPI labels, and switch settings: [Elechouse V3 manual, pages 3–5](https://www.elechouse.com/elechouse/images/product/PN532_module_V3/PN532_%20Manual_V3.pdf). Pi header orientation, power pins, and SPI mapping: [official Raspberry Pi hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio). GPIO5 chip select is this project's recorded configuration, rather than the default SPI0 CE0 connection.

## 1. Identify what Linux sees

With the readers connected as above, identify the USB OMNIKEY. Do not scan cards into a shell prompt. Run:

```sh
cat /etc/os-release
python3 --version
sudo apt update
sudo apt install usbutils evtest
lsusb
cat /proc/bus/input/devices
ls -l /dev/input/by-id/
```

`lsusb` identifies the USB OMNIKEY. The input-device listing associates its name with a handler such as `event4`; that was the observed path, not a stable identity. The by-id directory may provide useful device links; if it does not exist, use the input listing. Disconnect and reconnect the USB OMNIKEY, repeating the listings, to confirm its identity. Event numbers can change after reconnecting.

The SPI-connected PN532 will not appear as a second USB reader or `/dev/input/event*` keyboard. Verify it through the current Pi script's PN532 initialization, firmware response, and UID reads. Do not look for a second `evtest` path. If the OMNIKEY has no suitable input handler, inspect its mode before using the keyboard-input probe.

## 2. Check each reader independently

For the OMNIKEY, replace the example path with its identified input device, not the physical keyboard's device:

```sh
# USB student-number reader; replace eventX
sudo evtest --grab /dev/input/eventX
```

`--grab` prevents other applications receiving events from the selected input device until the monitor exits. Stop it with Ctrl+C before the Python probe attempts to read/grab the OMNIKEY.

Inspect key names, timestamps, and event values: press = 1, release = 0, repeat = 2. Record terminators, modifiers, prefixes, and leading zeros. Nine digits followed by Enter were observed on the tested card; this is not a universal student-number specification.

For the PN532, use the SPI diagnostic in Shane's current combined Pi script. Record initialization, firmware response, UID bytes, and RF command acknowledgements. Display UIDs as uppercase hexadecimal with leading zeros preserved. The workspace's combined probe uses the shared reader operations; preserve any newer Pi changes before updating it.

Test each reader independently before the combined sequence. The libraries and connection methods differ; only the OMNIKEY needs a keyboard-character buffer.

## 3. Test the UID-first handover

The reported working sequence keeps the card presented throughout:

1. Enable the PN532 RF field and require command acknowledgement.
2. Read the card UID through SPI.
3. Disable the PN532 RF field and require command acknowledgement.
4. Read the student number from the USB OMNIKEY while the card remains presented.

The OMNIKEY remains powered; the script does not switch its RF field. This sequence switches the PN532's radio field, not physical power. Simultaneous reading and student-number-first reading did not reliably produce both identifiers without another presentation in the reported experiment.

The reported helper uses PN532 `RFConfiguration` (`0x32`), item `0x01`, with `0x03` for on and `0x02` for off, retaining external-field checking. Alternatives `0x01`/`0x00` were discussed but not confirmed as the working configuration. Preserve the current script's evidence rather than assuming a different setting fixes RF interaction.

Log timestamps for field commands, acknowledgements, UID reads, and completed student-number scans. Discard stale OMNIKEY input before waiting for a fresh scan, while recording that a discard occurred. The exact production buffering and fresh-presentation rules remain to be designed.

A three-second diagnostic pause is not a card-removal detector or an agreed production timeout. A successful sequence or short time gap also does not prove that both identifiers came from the same card.

## 4. Trials to run

1. Confirm each reader's independent identifier output, then run the combined UID-first sequence with one card presentation.
2. Repeat across several student cards. Record formats, leading zeros, lengths, UID consistency, and whether both reads complete without lifting the card.
3. Lift and retap, then hold the card in place to observe repeat output. Establish evidence for detecting a genuinely fresh presentation.
4. Remove card A after its UID is read and present card B. Record missing, overlapping, buffered, or late output; never treat A's UID and B's student number as a confirmed pair.
5. Exercise missing student-number output, interruption, cancellation, and expired collection. Old buffered input must not leak into the next interaction. Every kiosk visit requires both identifiers before processing; a missing number must cause no activation or registration.
6. Reconnect the USB OMNIKEY and restart the Pi/PN532 diagnostic, then repeat. Re-identify the OMNIKEY input path and verify PN532 readiness separately.
7. Exercise field-on and field-off command failures with bounded waits and diagnostic logging. Missing acknowledgement must not permit registration/activation success or continued pairing with uncertain reader state; recovery policy still needs agreement.
8. Run repeated presentations long enough to investigate the reported intermittent failure after roughly a minute: field-on received no confirmation, followed by field-off cleanup also receiving no confirmation. Later one-tap success did not establish a root cause or prove that failure fixed.

Keep a small record of reader models, SPI wiring/switches, software versions, card aliases (A/B/C), attempts, missed/duplicate reads, RF acknowledgements/failures, and observed timing. Redact student numbers and UIDs from shared output while preserving key structure. The one-card trial establishes feasibility, not multi-card reliability or same-card assurance.

## 5. Before connecting the readers to the controller

Use the current combined Pi diagnostic as the starting point, separate from the student-card state machine. It reads PN532 UID bytes through SPI and OMNIKEY characters through Linux input events, following the RF handover above. Keep repeated scans visible during diagnosis. Preserve any newer Pi changes before updating the diagnostic.

The integrated diagnostic runs with `python -u -m kiosk --device /dev/input/eventX`. It discards queued OMNIKEY input before each UID attempt, preserves input arriving during RF-off, and emits `CardRead` only after UID/RF acknowledgement and a complete student number. Missing the number produces retry feedback and no backend call. The backend remains simulated. After feedback expires, acquisition rearms automatically once reader cleanup finishes and the controller is ready. Card removal is assumed, as requested; there is no presence detector or guarantee against repeated processing of a held card. Test this path independently of the probe, whose post-handover drain and repeat delay are experimental.

For the repeated-scan Pi trial:

1. Present card A, hold it through the student-number beep, verify both prints, then take it back.
2. Wait for the result to return to `IDLE` and print `Ready for next card.` (normally about 2 seconds after the result).
3. Present card A again without restarting. Expect one new completed pair and one simulated activation.
4. Take A back, wait for readiness, then present card B. Verify B's printed student number and UID; neither value may be carried over from A.
5. If a scan misses the student number, wait for incomplete-scan feedback and readiness, then retry without restarting. The incomplete attempt must not print `ActivateUid`.
6. Repeat several alternating-card cycles, then Ctrl+C while waiting for a card to check shutdown. Record any stale values, unexpected errors, or failure to rearm. Do not treat a held-card repeat as a removal-detection failure; removal is outside this version's behavior.

Before production integration, establish same-card assurance, fresh-presentation detection, and recovery from RF command failure. `IdentityConfirmed` must represent verified same-card evidence, not two values grouped by timing or session ID. Raw `CardRead` values never establish a trusted association. Cancellation must finish reader cleanup before devices close; device/command failures must produce `ReaderFault`.

These diagnostics must not register cards, replace cards, or activate visits. Reader evidence is separate from backend acceptance. The plan does not establish that the OMNIKEY can also supply a matching UID or that student numbers can be mathematically converted to UIDs.

## References

- [Current reader experiment and limitations](plan.md#6-reader-experiment-evidence-and-current-limitations).
- [Controller and backend obligations](plan.md#controller-and-backend-obligations).
- [Debian evtest manual](https://manpages.debian.org/trixie/evtest/evtest.1.en.html): capture mode and exclusive device grab.
- [Debian lsusb manual](https://manpages.debian.org/trixie/usbutils/lsusb.8.en.html): USB device discovery.
- [Linux input event codes](https://docs.kernel.org/input/event-codes.html): key event values.
