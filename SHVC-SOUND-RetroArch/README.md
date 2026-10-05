# Real SHVC-SOUND / RetroArch experiment

Windows x64 and Android ARM64 proof of concept for ESP32 rev0.4 and the user's local Super Mario World dump. ROMs, SPCs and ARAM dumps are never bundled or published.

## How it works

The CPU/PPU run in Snes9x. The game uploads its own sound program and samples to SHVC-SOUND, which executes them and produces analog audio. Runtime port reads return real hardware values over USB; this does not stream PCM to the module.

A shadow SMP still runs. Successful IPL port-0 echoes build batches of WRITE/WAIT instructions, and ESP checks every real byte ACK. IPL data precedes port-0 notification; a detected jump reserves 20 ms, advances the shadow SMP and aligns readiness with real AA/BB. These startup heuristics are validated on SMW, not every game. Cycle-exact synchronization, streaming games, save states, rewind and fast-forward remain outside the validated scope.

The core drains and discards emulated PCM whenever SHVC_APU_PORT is set, including transport failures. The separate RetroArch config disables PC audio and audio synchronization, retaining video vsync. Extra shadow-SMP startup samples cannot pace game playback.

## Run

1. Connect ESP USB and power the SHVC-SOUND/external amplifier.
2. Run start_smw.cmd (COM6 default; first argument overrides it).
3. Enter: Start; arrows: movement; Z/X: B/A; A/S: Y/X; Q/W: L/R.
4. Close RetroArch before flashing or opening COM6 elsewhere.

The launcher uses a separate portable RetroArch under ignored docs/tmp and does not modify another installation. The dedicated bridge firmware temporarily replaces BLE playback. restore_ble.ps1 restores the previously built BLE player; huge_app preserves its LittleFS/NVS layout and stored song.

## Build and diagnostics

- python build_core.py patches the local libretro/snes9x checkout under docs/tmp, builds with installed Zig in an ASCII temp directory and writes the private DLL/revision to ignored artifacts.
- Firmware: ../SHVC-SOUND_python/esp32_apu_bridge/build.ps1 -Port COM6.
- python probe_core.py --port COM6 --frames 1200 --no-throttle measures unpaced title/menu processing. Without --no-throttle the harness paces at the reported game frame rate.
- Logs record video frame counters every 300 frames and hardware failure status.
- Historical ARAM readback diagnostics remain private in docs/tmp. Current cold reset clears RAM; it is not a readback API.

Upstream sources and compiled derivatives retain the Snes9x license. The user's existing SFC-ROM directory supplies the ROM without copying it into this project.

## USB protocol

921600 baud, 8N1, DTR/RTS disabled. Request: AP, little-endian sequence/length/CRC16-CCITT (initial FFFF), then three-byte commands, at most 1536 payload bytes. Header and payload use one Windows WriteFile. ESP validates the CRC before execution.

Operations: 10 write(port,value), 11 wait for value (100 ms timeout), 12 read, 13 cold SMP/DSP/RAM initialization with AA/BB, 14 delay (16-bit microseconds).

Reply: AC, sequence, status, failed instruction, result length, result bytes and CRC16 of header/results. A failed instruction mutes hardware output.

## Validation / 2026-10-05

- Private core and firmware compiled; flash verified.
- Initial attempts exposed ACK/poll confusion, early notification and post-start input-port clearing; corrected.
- Readback matched the examined immutable program region. Writable/audio differences are not evidence of a full RAM match.
- Initial 600-frame real run reached title/menu without bridge error in 13.113 seconds including startup.
- User confirmed sound in RetroArch but reported slow gameplay and faulty PC audio.
- After disabling PC PCM/audio pacing and combining USB writes: unthrottled 1200 frames in 22.024 seconds including startup, zero delivered PCM frames. Frames 301-1199 averaged 69.17 fps.
- Updated visible RetroArch: frames 300-600 took 4.984 seconds, approximately 60.2 fps, with hardware_failed=0. This verifies this interval, not all gameplay scenarios. Initial sound-program transfers can still cause pauses.

## Experimental Bluetooth transports

A build without Wi-Fi credentials supports USB, BLE and Bluetooth Classic SPP. A build with Wi-Fi credentials starts Wi-Fi and USB only, to avoid radio coexistence delays. While connected, SPP has priority over BLE and BLE has priority over USB. Close the wireless relay before using USB. GPIOs and the stored BLE-player song are unchanged.

The core selects a local named pipe with SHVC_APU_PORT=BLE; either ble_relay.py or spp_relay.py bridges it to the actual wireless link. This pipe adds no network-accessible service. PC PCM remains disabled. Do not run both relays simultaneously.

Run `powershell -ExecutionPolicy Bypass -File SHVC-SOUND-RetroArch/start_smw_ble.ps1` for BLE, or append `-Transport SPP` for Classic. The launcher closes its relay when RetroArch exits. SPP defaults to this module's detected Bluetooth address A4:F0:0F:69:0A:EE, RFCOMM channel 1; direct relay arguments can override both. It connects without requiring a Windows virtual COM port.

BLE requests the Windows throughput-optimized connection profile for the life of the connection, then restores defaults on disconnect. The measured connection interval is 15 ms, not the ESP's requested 7.5 ms. See [Microsoft's RequestPreferredConnectionParameters documentation](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.bluetoothledevice.requestpreferredconnectionparameters). SPP splits operations into 384-byte batches to respect Arduino BluetoothSerial's 512-byte RX queue. All real WAIT acknowledgments, packet CRCs, sequence checks and failure indexes are retained.

Measurements so far (unthrottled SMW title/menu, actual hardware):

- BLE before Windows tuning: roughly 170 ms for individual small exchanges.
- BLE throughput profile: 600 frames in 44.190 s including startup; steady interval averaged 20.76 fps, zero PC PCM frames.
- Classic initial large packets exceeded the RX queue; corrected. Failed runs are excluded.
- Classic with small batches: 1200 frames in 84.056 s including startup, steady 24.00 fps.
- Clearing stale IPL readiness and enabling a scoped 1 ms Windows timer: 1200 frames in 72.677 s, steady 32.68 fps; normal exchanges about 29 ms.

These measurements do not establish wireless 60 fps. The diagnostic now fails explicitly if the real hardware backend fails, so silent emulated fallback cannot count as a successful benchmark.

- Classic with an additional ESP low-poll-interval QoS request and BLE advertising suspended while connected: 600 frames in 64.606 s, steady 28.03 fps. The request does not guarantee the Windows controller's actual poll schedule. Observed Classic performance remains roughly 28-33 fps, not 60 fps.
- Wireless audio has not yet been independently confirmed by the user; success here means verified real port responses and transfers, not an acoustic listening result.

The current synchronous runtime-read design stalls the game for each wireless round trip. Achieving wireless 60 fps will require either reducing that round-trip time below the frame budget, or redesigning synchronization with explicitly bounded buffering/latency. Returning unverified emulated replies is not treated as a speed improvement.

## Wi-Fi transport

Wi-Fi station support is optional. Pass build.ps1 `-WifiCredentials` with a private header defining SHVC_WIFI_SSID and SHVC_WIFI_PASSWORD. The build copies it only into the temporary sketch; without a header it builds with Wi-Fi disabled. The header is excluded from Git. No credentials are included in this repository.

The huge_app partition layout is unchanged. The build also overrides the board's default 1.25 MiB size check to the actual 3 MiB app capacity. This is necessary for Wi-Fi plus both Bluetooth stacks and does not change filesystem offsets.

Wi-Fi disables modem sleep and uses TCP_NODELAY on both ends. ESP listens on LAN TCP 28954 and answers the SHVC-APU-FIND1 UDP discovery query on 28955. wifi_relay.py accepts an optional --host address, or discovers the bridge automatically. Game packets retain their real ACK/CRC/sequence checks.

The same launcher accepts `-Transport WIFI`. A connected Wi-Fi client has priority over Classic, BLE and USB. Close the relay before switching transports. The legacy SHVC_APU_PORT=BLE setting selects the local pipe for every relay; it does not mean Wi-Fi traffic goes through Bluetooth. USB operation 18 returns the station's four IPv4 octets for setup diagnostics.

### Wi-Fi validation

- Station connected after the user corrected the SSID spelling. LAN broadcast discovery did not work on this network; the actual IP was obtained with USB operation 18 and a direct TCP connection succeeded. wifi_relay.py caches only that IP under ignored docs/tmp, retries discovery if the cached connection fails, and accepts --host explicitly.
- Initial Wi-Fi plus active Bluetooth stacks: 1200 actual-hardware frames in 35.748 s including startup; steady 43.88 fps. Typical exchanges were about 21-23 ms.
- The Wi-Fi build now skips Bluetooth stack startup. USB and Wi-Fi remain available; build without credentials to test Bluetooth again.
- USB regression after the shadow-IPL fix: 600 frames in 9.062 s including startup; unthrottled steady 294.22 fps, no hardware failure and zero delivered PC PCM frames. Frontend vsync, not this unthrottled test, sets normal gameplay speed.

- Wi-Fi-only radio runtime: 1200 frames in 10.625 s including startup; frames 301-1199 averaged 154.39 fps without frontend pacing. No hardware failure and zero PC PCM frames. Normal packet round trips averaged 5.5-6.1 ms in the later batches. Large startup transfers and cold reset take longer.

- Visible portable RetroArch was launched through the Wi-Fi relay. Multiple 300-frame intervals took 5.000 seconds, approximately 60 fps, with hardware_failed=0. Some intervals took about 5.3 seconds and occasional network round trips exceeded 100 ms; brief Wi-Fi stalls remain possible. This is near normal speed, not a claim of perfectly constant frame pacing.
- Double-click start_smw_wifi.cmd to launch the Wi-Fi game. start_smw_wireless.ps1 is the shared launcher; the older BLE script remains a compatibility wrapper.
- Temporary credential headers were removed after flashing, and a source check found no private SSID/password in the public source files. The private firmware binary embeds the supplied credentials and must stay excluded from public artifacts.

## Stop on exit

The core sends operation 15 on APU deinitialization before closing its transport. ESP mutes the output, switches the blue LED off, cold-resets SMP/DSP/ARAM and returns a verified AA/BB waiting handshake. The host records `SHVC stopped: real IPL AA/BB confirmed` only after that reply. A new game reset (operation 13) enables output again.

Wi-Fi/BLE/SPP disconnect events also request a stop executed on the ESP main loop. This covers wireless relay/application termination without relying on a game-specific music command. Abrupt USB process termination without a clean core shutdown is not detectable through the existing disabled DTR/RTS interface.

Validated by launching the updated portable RetroArch over Wi-Fi and closing its own test window normally. The game process exited and the core logged a verified real AA/BB stop acknowledgment; the launcher/relay then exited. Replay before closing still ran near 60 fps with no hardware failure.

## Android RetroArch

The same modified Snes9x core now runs in the existing Android RetroArch UI,
with its standard SNES touchscreen overlay and Android controller driver.
`SHVC-SOUND-Android-SFC` is the earlier standalone test frontend; RetroArch is
the usable follow-up for users who prefer its established controls.

Build `build_android_core.py` with NDK 27.2.12479018. It adds the core option
**SHVC-SOUND: ESP address (Reload Core)**. Without `--host`, the option defaults
to reading the first IPv4 address from `system/shvc-wifi.txt`. Supplying
`--host ESP_IP` also adds that address as a selectable private-build preset.
Reload the core after changing the endpoint. The device's Wi-Fi credentials
remain exclusively in the private ESP firmware build.

For the verified test setup, download the official RetroArch 1.22.2 ARM64 APK
to the Android tools directory as `RetroArch_aarch64.apk`, then run:

```powershell
python SHVC-SOUND-RetroArch/build_android_core.py
python SHVC-SOUND-RetroArch/package_android_retroarch.py
python SHVC-SOUND-RetroArch/provision_android_retroarch.py --device DEVICE_SERIAL --host ESP_IP --rom PATH_TO_USER_ROM
```

Install the generated private APK before running the provisioning script.
The packager retains RetroArch's UI/code, adds the native core and shared C++
runtime, enables debugging for ADB provisioning, and signs with a local test
key. It is not an official RetroArch APK and must stay out of public releases.
The provisioner verifies a separately supplied ROM by SHA-256, sets up private
core/info/config/save directories and copies RetroArch's own SNES overlay.
It disables frontend PCM, rewind, run-ahead and automatic state loading.

Validation on 2026-10-05: Xiaomi 14T / XIG07 loaded the real core in RetroArch,
completed the real IPL handshake, and ran at least 2100 frames with
`hardware_failed=0`. The user confirmed that the game was playable and audible
through SHVC-SOUND. Short 300-frame intervals varied from roughly 58 to 65 fps;
strictly constant frame pacing with frontend audio disabled is not established.
The earlier standalone frontend ran approximately 47–50 fps. Standard SNES
controls loaded in RetroArch. Hardware APU state serialization, rewind and
cycle-exact host/APU timing remain unimplemented.

`QUITFOCUS` is supplied to the verified launch command so leaving the game
requests RetroArch shutdown and the core's existing verified STOP path. The
standalone Android frontend's home-screen STOP was verified independently;
the equivalent Android RetroArch exit still needs a dedicated log check.
