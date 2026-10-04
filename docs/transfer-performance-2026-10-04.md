# ESP32 to SHVC transfer performance

Measured on the assembled ESP32 rev0.4 board on 2026-10-04.
The saved SPC was replayed using BLE command PLAY. Times include reset,
RAM transfer, restore stub, and the final playback acknowledgment.

| Implementation | Chip bytes | Seconds | Result |
| --- | ---: | ---: | --- |
| Original GPIO implementation | 66,278 | 45.825 | SPC playback state |
| Fast GPIO, run 1 | 66,278 | 19.920 | SPC playback state |
| Fast GPIO, run 2 | 66,278 | 19.920 | SPC playback state |

Each run emitted 66 progress notifications. The probe verified consistent
totals, monotonic progress, zero start, complete end, and final SPC mode.
The resulting speedup is 2.30 times; elapsed time fell by 56.5 percent.

The BLE player opts into `SHVC_FAST_GPIO`. Direction changes use the GPIO
output-enable registers instead of repeatedly configuring eight pins;
address and data writes use register masks, and reads sample GPIO once.
Both external buffers remain disabled during direction changes. All byte
acknowledgments, 15/30 microsecond delays, and scheduler yields are retained.
Other sketches keep the original implementation by default.

Playback state was verified; audible output was not independently measured.

## Android to ESP32 transfer

Sound Deck 0.1.3 requests Android's high connection priority only during
uploads, then restores balanced priority in a finally block. The packet
size, per-packet acknowledgments, offset verification, and firmware CRC
validation are unchanged. An unsuccessful priority request retains normal
transfer behavior. No additional ESP firmware update is required.

On Xiaomi 14T, the same 66,376-byte SPC bundle took 29.216 seconds with
0.1.2 and 14.032 seconds with 0.1.3, including BEGIN, data packets, COMMIT,
and the new 500 ms settling delay. Connection logs confirmed a successful
interval change from 39 to 12 BLE units during upload, followed by the
balanced-priority request. Both hardware tests passed, including final
received byte count, zero dropped packets, CRC-validated COMMIT and PLAY.
Seven codec unit tests passed and lint reported no errors.
An additional 0.1.3 hardware run passed in 14.654 seconds for the phone
upload, again with successful CRC commit and SHVC playback.

Android API reference:
https://developer.android.com/reference/android/bluetooth/BluetoothGatt#CONNECTION_PRIORITY_HIGH

## Xiaomi 14T setup

Installed Sound Deck and copied SPCs to `/sdcard/Download/SHVC-SPC`.
Files were grouped using SPC game tags, with source folder fallback for
untagged files. Byte-identical duplicates were omitted. All 862 copied
files (57,013,270 bytes in 18 folders) passed SHA-256 verification.
Private music files and the local source manifest are excluded from Git.
