# Unified BLE player and Wi-Fi APU bridge

This firmware combines Sound Deck's BLE SPC/MIDI/WAV player with the RetroArch
Wi-Fi bridge. The rev0.4 bus and amplifier GPIO assignments are unchanged.

Build with `build.ps1 -Port COM6 -WifiCredentials <private-header>`.
The private header defines `SHVC_WIFI_SSID` and `SHVC_WIFI_PASSWORD` and must
never be committed. Omitting it builds a BLE-only configuration.
The 3 MB application partition leaves 896 KB for saved songs; flashing the
application does not erase the song filesystem or preferences.

Wi-Fi TCP port 28954 and discovery UDP port 28955 use the existing AP bridge
protocol. A RetroArch TCP connection takes ownership and suspends BLE.
Closing the connection stops and resets the SHVC, then restarts the ESP into
a clean BLE stack without automatically starting its saved song. Allow a few
seconds for the device to reappear in Sound Deck.

While Sound Deck is connected, Wi-Fi is disabled. Disconnect Sound Deck before
starting RetroArch; Wi-Fi reconnects automatically. The two clients cannot
control the SHVC simultaneously.

If a complete SPC snapshot cannot fit in contiguous heap, playback streams its
ARAM image from LittleFS in 1 KB IPL blocks, retaining only the restore stub
for volume adjustment. Song duration does not increase the snapshot RAM size.

## Hardware validation (2026-10-05)

- ESP32 DOIT DevKit v1 / SHVC-SOUND rev0.4, Arduino ESP32 core 3.3.12.
- Application: 1,810,562 bytes, 57% of the 3 MB application partition.
- Two successive Wi-Fi RESET/STOP sessions returned verified real IPL AA/BB
  responses with valid packet CRCs; Sound Deck then connected over BLE.
- Xiaomi 14T transferred the longest duration-tagged SPC in the local library:
  FF6 `Dancing Mad (Full)`, 683 seconds. SHVC upload acknowledged success:
  66,278 bytes in 2,266 ms, streamed from the saved snapshot.
- The application showed SPC playback and the playlist countdown; the user
  confirmed audible playback. Full-song completion was not verified.
