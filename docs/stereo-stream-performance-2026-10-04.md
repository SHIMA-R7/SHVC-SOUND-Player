# 32 kHz stereo WAV streaming experiments

Tested on ESP32-D0WD-V3, SHVC-SOUND ESP32 rev0.4 and Xiaomi 14T (XIG07). Source: local Fatamorgana WAV, 48 kHz stereo PCM16, 235.029 seconds. Music data is not included in this repository.

- BRR bandwidth needed: 32,000 samples/s × 9/16 bytes/sample × 2 channels = 36,000 bytes/s.
- Initial 16-packet transfer and single-thread conversion could not sustain playback.
- Input buffering, reduced encoder range search and a bounded background encoder reduced conversion waiting.
- Original SPC700 bulk command7 measured about 33.4 kB/s on the bus, below the required bandwidth.
- Page-bounded command9 removes per-byte page checks; all 256 start offsets and ring wrap passed the SPC700 simulator.
- Experimental 0.25-us writes reached about 43.5 kB/s on the bus but failed intermittently with pointer/communication errors. These timings were not retained.
- Bulk payload writes now use 0.5-us CPU-cycle delays. Control commands retain 1-us writes. Explicit PCM data reads use 4-us settling; ACK polling retains its established timing. Both external buffer OEs remain mutually exclusive.
- With safe control timing, the bus measured about 40.1 kB/s. Windows of 32 packets yielded about 35 kB/s including BLE confirmation and underrun after about 44 seconds.
- A 64-packet streaming window and 128-packet phone conversion buffer sustained the full track. The first packet is read back from each ARAM ring before playback.

Do not interpret successful initialization or average bus throughput as proof of stable complete playback. Full-track results follow below.

## Full-track result

32 kHz stereo Fatamorgana passed the real-device test: 8,461,062 BRR bytes, 235,029 ms of playback, no dropped-command count, and stopped mode at the end. Total test time including connection, prefill and saved-song restoration was 243.511 seconds. The user confirmed both channels sounded correct and the complete track finished without problems.

Typical 29,952-byte streaming windows took about 790–804 ms plus a few milliseconds of conversion waiting. The complete stream requires the phone to stay connected; it is not stored for standalone boot playback.

Final Android version: 0.2.0. The WAV format selector offers 16/32 kHz and mono/stereo. Twelve JVM tests passed, including paired-block size, mono duplication, independent left/right audio and truncated WAV rejection. Android lint and builds passed.
