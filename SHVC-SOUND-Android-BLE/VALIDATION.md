# Validation — 2026-10-04

Device: moto g66j 5G, Android API 36. ESP32 BLE address ending 0A:EE, SPC-gain/activity-LED/load-progress firmware.

- Debug APK built and installed using ADB.
- Six JVM tests passed: SPC restore stub, MIDI multi-track tempo conversion and WAV BRR output matched established Python player bytes; CRC framing, gain negotiation and truncated SPC rejection passed.
- Android lint passed with zero errors (dependency-version and manifest recommendations remain).
- Opt-in `RealDeckTest`: passed in 58.045 seconds. Connected, received INFO, toggled/restored mute, entered MIDI live, sent three note-on/off pairs and restored saved SPC playback.
- App UI: scanned and selected the advertised ESP, received status, entered MIDI mode, played C4/E4/G4 from on-screen keys. User confirmed audible notes.
- Android document picker selected an existing user-owned local SPC. App converted and uploaded 66,376 bytes, all offsets acknowledged, COMMIT returned code 0. After app restart, reconnection returned mode 1 (SPC) with full received/total counts, confirming standalone playback survived.
- Portrait and landscape screen layouts inspected; dark system-bar text contrast corrected.

Initial hardware attempts connected successfully but INFO timed out. Subsequent attempts and normal UI reconnections succeeded; the cause of those initial timeouts has not been isolated. Reconnect if the first state request stalls.

WAV and MIDI-file conversion have byte-for-byte JVM coverage; their full Android-to-chip file playback has not yet been separately checked. Commercial song data is absent from application assets and repository fixtures.

## Version 0.1.1 correction and retest

The earlier app restart was a real crash, subsequently confirmed from AndroidRuntime logs (DeckScreen.kt:106, NullPointerException). Deferred progress-indicator draw/semantics callbacks read `ui.progress!!` after the upload stage changed it to null. Capturing the composition's immutable progress value fixes that transition.

- Version 0.1.1 (versionCode 2) installed on moto g66j 5G; load-progress firmware flashed to ESP32.
- Seven codec/status JVM tests and Android lint passed. Existing Windows Python protocol/client tests: 9 passed.
- `TransferProgressTest` passed on the phone in 5.187 seconds: 20 determinate-to-indeterminate transitions with semantics queries and rendering.
- Firmware replay probe: 66 progress notifications, monotonic from 0 to 66,278 acknowledged chip bytes, then final SPC mode.
- Full app UI test: selected SPC uploaded and committed, transitioned to SHVC loading, displayed 40% and 98%, reached 100% and received successful PLAY reply. App PID 13397 remained alive throughout; UI returned to Super Mario World / SPC. No new app crash log appeared.
- Copied 949 SPC files (62,764,246 bytes) from PC document roots to `/sdcard/Download/SHVC-SPC`, preserving document subfolders. All 949 destination SHA-256 values matched their source files.
- USB interruptions required reconnecting the phone. Final successful tests/copy used Google's platform-tools 36.0.2 with libusb on this Windows host.

## Version 0.2.2 — 2026-10-05

Latest validation supersedes the initial WAV and test-count limitations above.

- 20 JVM tests and Android lint passed; debug APK versionCode 8 built.
- Firmware compiled (1,246,318 bytes; 43,412 bytes static RAM), flashed and verified.
- 32 kHz stereo streaming completed a 235.029-second track with zero dropped bytes; the user confirmed playback through completion.
- Automatic full-upload recovery and failed playlist-track continuation passed hardware checks.
- Optional amplifier PWM fade and restoration passed electrical checks. Audible fading requires TDA7053A hardware and remains unverified. The current external jack amplifier uses profile 0, PWM disabled.
- Xiaomi's 862 SPC files in 18 game folders were registered in Downloads; the user confirmed picker visibility. Music files are absent from the repository and APK.

See the latest stereo-stream-performance, transfer-performance and playlist-retry-and-amplifier reports in ../docs/.
