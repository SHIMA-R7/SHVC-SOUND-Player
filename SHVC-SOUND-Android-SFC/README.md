# SHVC SFC Live — private Android prototype

An Android ARM64 libretro frontend for the experimental Snes9x SHVC-SOUND
backend. This is a separate app from Sound Deck and from official RetroArch.
It renders the game and accepts touch controls on Android. Rendering runs on a
separate thread using the latest frame, so surface buffer waits do not hold up
APU operations. APU port operations
go over a direct TCP connection to the ESP32 Wi-Fi bridge; the SHVC-SOUND module
runs the uploaded game sound program. The Android PCM callbacks do not play audio.

## Use

1. Run the Wi-Fi bridge firmware on ESP32. Connect Android to the same reachable
   LAN. The server listens on TCP port 28954.
2. Open **SHVC SFC Live**, enter the ESP's IPv4 address, choose a local `.sfc` or
   `.smc` file using **ROM選択**, and press **開始**.
3. Use the on-screen D-pad, ABXY, shoulder buttons, Start and Select.
4. Press **停止**, or leave the app, to send the bridge STOP command. A successful
   stop is recorded as `SHVC stopped: real IPL AA/BB confirmed` in app-private
   `files/core.log`. Disconnect also triggers the firmware's stop path.

The status line shows measured emulation frames per second and acknowledged
bridge packets. A hardware transport error stops the game rather than allowing
an emulated audio fallback to count as a successful hardware test. The current
backend was developed with Super Mario World; other games still need verification.

## Build

Requires the upstream Snes9x tree under ignored
`docs/tmp/snes9x-hardware-source` at revision
`fae2fea08f74180759ef540ee94259213f503480`, and the Android tools configuration
produced by Sound Deck's `tools/setup_build.py`. Install NDK `27.2.12479018`.

From the repository root:

```powershell
python SHVC-SOUND-RetroArch/build_android_core.py
python SHVC-SOUND-Android-SFC/tools/build.py
python SHVC-SOUND-Android-SFC/tools/install.py --device DEVICE_SERIAL --host ESP_IP --rom PATH_TO_USER_ROM
```

The core uses NDK Clang for ARM64 / Android API 26. Native libraries use 16 KB
ELF segment alignment. Gradle builds in an ASCII temporary directory and runs
`assembleDebug` and `lintDebug`. Output is
`artifacts/shvc-sfc-live-debug.apk` (ignored).

The installation helper verifies the ROM copy by SHA-256 and writes it only to
the app's private storage. No ROM or Wi-Fi password is included in the APK.
IP addresses are entered by the user and retained only in app preferences.

## Validation, 2026-10-05

- ARM64 core and JNI frontend linked with unresolved-symbol checks enabled.
- Debug APK build and Android Lint passed; warnings remain for prototype UI text
  and deprecated framework APIs.
- Xiaomi 14T / XIG07 detected by ADB on the same LAN as ESP32.
- Installation succeeded after the user accepted Xiaomi's USB install prompt.
  The 524288-byte user ROM copy was verified by SHA-256 on the device.
- Real IPL AA/BB handshake and ongoing real APU reads succeeded. The first run
  reached 7200 frames with `hardware_failed=0`; steady intervals were approximately
  47–50 emulation fps on this Wi-Fi setup.
- The user confirmed successful sound and gameplay, and reported poor touch
  control ergonomics. This remains a prototype UI limitation.
- Returning to the home screen produced `SHVC stopped: real IPL AA/BB confirmed`.
- The renderer was subsequently separated from the emulation thread and the APK
  updated on Xiaomi; early intervals remained approximately 47 fps. This change
  alone does not establish 60 fps Android performance.
- The conditional transport changes also passed the Windows core build.

## Distribution

Private research prototype. Do not publish the APK or compiled Snes9x derivative
without reviewing the upstream license and satisfying its conditions. ROMs,
compiled binaries, and generated private test logs stay outside tracked source.
