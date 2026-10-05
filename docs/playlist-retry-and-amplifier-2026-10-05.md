# Playlist recovery and optional amplifier fade

Android 0.2.2, Xiaomi 14T/XIG07, ESP32 rev0.4, COM6. The actual audio path remains a jack-connected external amplifier.

## Recovery

- File/device/BLE transport failures get up to three full upload + PLAY attempts, with one/two second backoff. A command timeout or disconnect reconnects before retry. CRC-protected packet repair remains in place inside each attempt.
- Invalid local input, unsupported commands and explicit cancellation do not auto-retry. Exhausted transfer failures retain the failed song and playlist position and expose a retransfer action.
- Playlist timing options are captured at the start of a run. A timer starts only after the successful PLAY acknowledgement.
- Real Rainbow Road transfer: a deliberately invalid first bundle was rejected with device code 2, then the valid second upload and SHVC transfer completed with mode SPC and zero dropped messages. This proves recovery from an injected validation failure, not the cause of the original reported failure.
- The retry action regression corrupts track 2 of a three-track private fixture, waits for the playlist to stop at index 1, repairs the local fixture, then resumes track 2 and track 3. No songs are bundled in the APK.

## Amplifier profiles

| Profile | Current/future output | GPIO33 PWM | Live volume/fade |
|---|---|---|---|
| 0, default | External amplifier / jack | 0 | Unavailable |
| 1 | rev0.4 TDA7053A DC volume circuit | Configured level/envelope | Available |
| 2 | Dedicated fixed-gain TDA7053 board | 0 | Unavailable |

Verified rev0.4 board nets: GPIO33 -> VOL_PWM -> R6 10k -> AMP_VC -> U6 pins 2/8, with R5 5.6k and C5 10u to GND. The profile is persisted on the ESP, not inferred from the name of the attached amplifier. The profile selection does not rewire the board.

The firmware fade is nonblocking and keeps the SPC running. It decreases amplifier PWM over the supplied duration and leaves it at zero. The next PLAY resets the envelope to the configured level. Mute, STOP, loading and errors output zero. Changing initial DSP gain still reloads the SPC and is not used for fading. ID666 fade time is used inside the total tagged duration; missing/zero fade time uses the last two seconds. Current external output does not audibly fade.

Hardware protocol test: with a one-second fade and target duty 160, sampled written duties were 128, 96, 64, 32, then 0. Next PLAY restored 160. Profiles 0/2 held zero and rejected their unsupported fade/volume requests. The test restored profile 0 and left the real Rainbow Road SPC playing. This verifies firmware control state; an actual TDA7053A is still needed for acoustic validation.

Compile-time C++ checks cover input/mute restrictions, completion/reset and millis rollover. Android unit tests: 20 passed; lint and debug APK builds passed. The updated firmware was flashed and verified by esptool.

## Free GPIO on the existing 30-pin DevKit

The KiCad data leaves GPIO34/35/36/39 and GPIO12 unconnected. GPIO34-39 are input-only without internal pulls; GPIO12 is a boot strapping pin. TX0/RX0 are also unconnected on the carrier but used by the DevKit USB serial interface. GPIO33 is reserved for amplifier control; GPIO2 now drives the verified onboard activity LED. A carrier pilot LED can share that LED signal without needing a new GPIO. An I2C display needs two suitable output-capable lines and a reviewed allocation, not merely two unconnected pins.

Primary references: [Espressif GPIO documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html), [NXP TDA7053A datasheet](https://www.nxp.com/docs/en/data-sheet/TDA7053A.pdf), [Philips TDA7053 datasheet](https://dtsheet.com/doc/260133/philips-tda7053).


## Android document-picker visibility

The Xiaomi contained 862 SPC files in `/sdcard/Download/SHVC-SPC`, in 18 game/source folders. The MediaStore.Files collection contained all file entries with MIME `chemical/x-galactic-spc`, but SPC entries had `is_download=0`. The Downloads collection showed only the 18 folders, explaining the empty document-picker folders. Direct mutation of is_download was ignored by the provider. A scoped `content call --uri content://media --method scan_file --arg /storage/emulated/0/Download/SHVC-SPC` rescan registered all 862 files in the Downloads collection. File contents and names were unchanged. The copy tool now performs that rescan and checks every expected path in Downloads after SHA verification, with optional explicit ADB serial selection.

Final controller regressions passed: manual retry resumed track 2 and then track 3; the two-track background-playlist test issued a fade for both tracks in the DC amplifier profile. The test restored the external amplifier profile. The final injected-error retry test restored the real Rainbow Road file and started native SPC playback with zero dropped messages.

The user reopened the document picker and confirmed that the SPC files are now visible.
