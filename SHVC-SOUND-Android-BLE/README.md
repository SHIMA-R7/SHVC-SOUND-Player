# SHVC Sound Deck

Native Android Bluetooth LE controller for the ESP32 SHVC-SOUND player. Android 8.0 or later; Bluetooth LE required. The existing USB Android project is separate.

## Use

1. Power the ESP32 and SHVC-SOUND board. Disconnect other Bluetooth clients.
2. Open **SHVC Sound Deck**, choose **CONNECT**, grant Nearby devices permission and select SHVC-SOUND Player.
3. Add a local SPC, MIDI or WAV file using the Android document picker. Select it, then transfer and play.
4. DECK controls playback and mute. MIDI provides a keyboard, channel, instrument, volume, pan and expression. SETUP controls SPC gain, loop and standalone boot playback.

Transfer progress has two stages: phone-to-ESP upload, then ESP-to-SHVC loading (about 2.1 seconds for SPC on the tested rev0.4 board). Firmware with load-progress capability reports successfully acknowledged chip-transfer bytes, displayed as a percentage. Older firmware shows an indeterminate bar for that stage. The ESP retains its committed song and can play without the phone. A file in the phone library is not automatically uploaded.

SPC gain changes the snapshot's initial DSP master volume and restarts the track. Already saturated master volume cannot be increased further; game code may overwrite it. WAV accepts 16-bit PCM, mono or stereo, and streams the complete file as BRR. Select 16 or 32 kHz and mono or stereo before playback; mono input can be duplicated into stereo. The phone must remain connected for the whole WAV. WAV streaming does not replace the saved standalone song. MIDI accepts SMF type 0/1 with PPQ timing. SPC, WAV and MIDI share the physical sound chip.

## Build

Run `python tools/setup_build.py` to download verified official JDK, Gradle and Android SDK tools into a dedicated temporary directory. Then run `python tools/build.py`. Set `SHVC_ANDROID_WORK_ROOT` to a spacious ASCII directory to relocate the build and Gradle cache. The debug APK is copied to `artifacts/shvc-sound-deck-debug.apk`.

Build requirements: JDK 17, Gradle 8.13, Android SDK 36. Build tasks include JVM codec interoperability tests and Android lint. Tests use synthetic audio and register snapshots, without commercial song data.

No accounts, servers or internet permission are used. Local document URI permissions persist for the library. Bluetooth commands follow the firmware's acknowledgement protocol, size/CRC checks and staged song commit. SPC playlists and WAV playback use a connected-device foreground service and a CPU wake lock for background playback. Loss of the connection stops WAV streaming. The screen stays awake while a visible operation is running.

## Version 0.2.2

SETUP now selects an output profile stored on the ESP: external/jack output (default), rev0.4 TDA7053A DC-controlled amplifier, or a dedicated fixed-gain TDA7053 board. GPIO33 remains LOW for both profiles without DC control. TDA7053A enables live amplifier volume and a firmware-timed fade, without changing the loaded SPC or restarting its CPU. The DC amplifier volume is independent of the initial DSP gain slider. Switching the profile during an active playlist is disabled.

A playlist fades over its text ID666 fade duration; tracks with no positive fade duration use the last two seconds. The fade fits inside the existing total track time. The next successful PLAY restores the configured amplifier level. STOP, loading, errors and mute silence the amplifier. The external jack and fixed-gain profiles retain normal SPC playback and retry, with the fade control disabled. This does not make their audio fade.

The fade envelope/protocol can be tested on the current external-output setup, but audible amplifier fading still needs the actual DC-controlled amplifier. PWM duty is not an audio amplitude percentage, and the reachable control voltage depends on fitted divider resistors. Future amplifier installation must match the actual board and amplifier pinout; selecting a profile only changes software control.

## Version 0.2.1

SPC/MIDI transfers automatically retry up to three total attempts after device validation/storage/chip errors or BLE transport failures. Each attempt uploads the complete song and waits for successful chip loading. BLE timeouts and disconnections trigger a reconnect; retries wait one, then two seconds. Invalid local files, unsupported commands and explicit cancellation are not automatically retried. Exhausted retries show a retransfer button. A failed playlist retains its queue and index, so manual retry resumes that song and the following tracks rather than starting the queue over. Playback time begins after successful chip loading.

SPC DSP gain changes patch the initial DSP settings and reload the song. An external amplifier connected only through an audio jack has no software volume control through this board. In the external and fixed-gain profiles, the ID666 fade field only contributes to the timer. A runtime DSP fade in those profiles needs sound-driver support or a validated hook inside the loaded SPC program.

## Version 0.2.0

SPC playlists run from the connected phone. Add selected SPC files to the queue, reorder them, and start continuous playback. Text ID666 duration/fade tags determine each track time when enabled; missing tags use the configured duration. The next track still needs chip loading, so playback is not gapless.

WAV conversion uses bounded input and BRR buffers, separate predictor history for each stereo channel, and a producer running ahead of BLE transfer. The firmware uses two equal 29,952-byte rings for stereo, starting both DSP voices with one KON write. CRC-protected BLE windows validate offsets and retry missing packets. A buffer underrun stops playback instead of replaying old ring contents. 32 kHz stereo requires sustained 36,000 BRR bytes/s; successful playback depends on the actual connection and board timing.

Hardware measurements and experiment outcomes are recorded in `../docs/stereo-stream-performance-2026-10-04.md`.

## Version 0.1.1

Fixes a crash at the upload-to-chip-loading transition: deferred Compose drawing/semantics callbacks captured a nullable, changing UI progress value. The indicator now captures an immutable value for each composition. Instrumented regression coverage repeatedly switches between determinate and indeterminate progress.

Firmware retains the existing 20-byte reply format. Flags bit 4 advertises loading progress. In mode 4, received/total describe chip-transfer bytes. Unsolicited sequence 0/op 0 replies report progress, while the original sequence/op reply still completes the command. Normal upload counters resume after loading.

`tools/copy_spc_to_phone.py` copies only SPC files from explicitly specified document roots into phone Downloads, preserving subfolders and verifying every SHA-256. It then rescans the copied directory and checks that every file is registered in the Android Downloads index; physical copies without that registration can appear as empty folders in the document picker. Use `--serial` when more than one phone is attached. It does not embed songs into the APK.


For local ADB automation, start the saved queue with an explicit MainActivity intent using action `com.shvc.sounddeck.action.PLAY_PLAYLIST` and string extra `deviceAddress`. The activity connects to the supplied BLE address and starts the existing persisted queue; playback then runs in the app with its foreground service. No instrumentation process is needed during playback. The optional debug instrumentation `PlaylistSetupTest` imports SPCs from `/data/local/tmp/shvc-playlist/0.spc`, etc., using UTF-8 JSON names supplied in base64 via `playlistNamesBase64`. It preserves existing library entries and stores the imported files in app-private storage.
