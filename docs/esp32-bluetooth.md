# ESP32 Bluetooth Player

WindowsからBLEでSPC・短いWAV・MIDIファイルの保存・再生、リアルタイムMIDI演奏とパラメータ操作を行う。
SPCとMIDIシンセは同じSPC700を使うため、同時再生ではなくモードを切り替える。
SPC再生には動作確認済みのESP32用バス制御を共用する。

## Windows操作

```powershell
python -m pip install bleak mido pyserial numpy
python SHVC-SOUND_python/tools/ble_player_gui.py
```

この端末では`SHVC-SOUND_python/start_ble_player.cmd`のダブルクリックでも起動できる。
必要ライブラリは`tools/ble_requirements.txt`にもまとめている。

ESP32へ下記のファームを書き込んでから、WindowsのBluetoothを有効にして「Bluetooth接続」を押す。
接続名は`SHVC-SOUND Player`。操作画面がBLEサービスから自動検出する。
通常のBluetooth設定画面でCOMポートを作る方式ではない。

ESP32 DevKit V1上の青LED（D2、ボード定義の`LED_BUILTIN`=GPIO2）は動作状態を表示する。

|状態|LED|
|---|---|
|PCからESP32へ曲を受信中|ゆっくり点滅（0.5秒ON / 0.5秒OFF）|
|ESP32からSHVC-SOUNDへ転送中|高速点滅（約75 ms ON / 75 ms OFF）|
|SPC・MIDI再生モード|点灯|
|停止・エラー|消灯|

SHVC転送の高速点滅は受信表示より優先する。受信中止・完了・切断・タイムアウト後は現在の再生状態の表示へ戻る。
LEDは独立タスクで制御するため、約50秒のSHVC転送処理中も点滅を継続する。
再生中のミュートでも点灯する。WAVのワンショット終了後やMIDIライブ待機中も、再生モードの間は点灯する。

「SPC / MIDI / WAVを選ぶ」→「送信して再生」で曲をESP32内へ保存して再生する。
SPCは保存完了後、SHVC-SOUNDへの64 KB転送に約50秒かかる。その間は消音し、完了後に曲が鳴る。
最後に正常保存した曲は、給電を続ければPC切断後も動作し、電源を入れ直したときも再生する。
「電源投入時に再生」を解除すると自動再生を停止する。
初期曲をローカルで組み込んだ場合、まだ受信曲がないときは初期曲を使う。

|操作|SPC|MIDI|
|---|---|---|
|再生・停止・ミュート|対応|対応|
|音量|保存曲のDSP初期値を0〜4倍で変更し再読み込み。0倍は即時消音|全体音量、チャンネル音量(CC7)、expression(CC11)|
|パン・サステイン|曲プログラムに従う|CC10、CC64|
|音色・ピッチベンド|曲プログラムに従う|Program Change、Pitch Bend|
|ループ|元の曲のループ|ファイル末尾から再開。設定を保存|

「SPC / WAV再生音量」で0〜4倍を指定して「音量を反映・曲頭から再生」を押す。
変更時はESP32に保存済みの曲を読み直すため、PCからの再送信は不要。ただし曲頭に戻り約50秒かかる。
0倍は即時に出力を消音し、曲側の音量更新があっても無音を維持する。倍率はNVSに保存し、再起動後も適用する。
1倍は保存された元の値。左右のマスター音量とエコー音量を同じ倍率で変更し、
符号（位相）を保持して-128〜127で飽和させる。ボイスごとの音量・パンは変更しない。
したがって4倍でも音が4倍になるとは限らず、元の音量が最大ならそれ以上は増えない。
設定は原本から毎回計算するので、倍率を何度変更しても累積しない。
初期DSP値だけの変更で、曲が音量レジスタを書き直すと効果が変わるため、
汎用的なリアルタイム音量・テンポ操作ではない。再生中の曲プログラムは改変しない。
送信前の音量倍率は別設定。通常は1倍にして保存し、再生音量を使う。
初期DSPを書き込む標準の復元スタブを持たない独自HSP1は、1倍以外の音量変更を拒否する。
MIDIの設定もファイル内のCC・音色イベントで上書きされる場合がある。

WAVは非圧縮16-bit PCMをモノラル8 kHzへ変換し、BRRとしてRAMへ一括転送して1回再生する。
操作画面の既定は先頭10秒。8 kHzでは約14秒まで、32 kHzでは約3.5秒までがRAM上限。
BRRへの変換には時間がかかる場合がある。線形補間での変換で、元WAVと同じ品質ではない。
長い音声のストリーミングや、WAVのシーク・一時停止・自動ループはこの版には含まれない。
保存・再起動時の再生はSPCと同じ仕組みを使う。内部の状態表示はSPCになる。
音量倍率は再送信時に適用。再生終了後も状態はSPCのままで、もう一度「保存曲を再生」で鳴らせる。

「MIDIモードに切替」で標準BLE MIDIサービスからの演奏を受け付ける。
8ボイス、既存のGM音色マッピング・ドラムバンクを使用する。
鍵盤の自動探索を行うセントラル機能はこのスケッチに含めていない。
WindowsのUSB MIDI鍵盤を橋渡しする場合:

```powershell
python -m pip install python-rtmidi
python -c "import mido; print(mido.get_input_names())"
python SHVC-SOUND_python/tools/ble_player.py midi-input --input "Your MIDI input"
```

## ファーム書込み

Arduino CLI、ESP32コア3.3.12、従来と同じDevKit V1を使う。

```powershell
powershell -ExecutionPolicy Bypass -File SHVC-SOUND_python/esp32_ble_player/build.ps1 -Port COM5
```

3 MBアプリ領域と896 KBのLittleFS領域を使う`huge_app`パーティションへ変更する。
OTA用の第2アプリ領域はない。最初の起動時のみ、曲用ファイルシステムが未作成なら初期化する。
いったん初期化したファイルシステムが後でマウント失敗しても自動消去しない。
曲保存は最大256000バイト、正常保存曲1つと受信中の候補1つを使う。
受信途中・CRC不一致・形式不正では、正常保存済みの曲への参照を変更しない。
保存完了後も現在の演奏は続き、再生指示で新曲へ切り替わる。

`esp32_spc_standalone/spc_data.h`が存在すれば初期曲として組み込む。
そのヘッダー、ビルドしたバイナリ、ESP32内へ保存した曲には曲のデータが含まれる。
権利のない曲入りデータは公開しない。公開ソースだけでも、初期曲なしでビルドできる。

GPIO33のアンプPWMは0に固定する。今回確認した[J5 / アンプ迂回出力](esp32-playback-results.md)を使用する。
任意のTDA7053をPWMで制御する機能は追加していない。
シリアル115200bpsは診断ログ。従来の500000bpsバイナリ転送プロトコルはこのスケッチに含めない。

## CLI

```powershell
python SHVC-SOUND_python/tools/ble_player.py scan
python SHVC-SOUND_python/tools/ble_player.py status
python SHVC-SOUND_python/tools/ble_player.py upload path/to/song.spc --play
python SHVC-SOUND_python/tools/ble_player.py upload path/to/song.mid --play
python SHVC-SOUND_python/tools/ble_player.py upload path/to/clip.wav --seconds 10 --rate 8000 --play
python SHVC-SOUND_python/tools/ble_player.py mute 1
python SHVC-SOUND_python/tools/ble_player.py mute 0
python SHVC-SOUND_python/tools/ble_player.py midi
python SHVC-SOUND_python/tools/ble_player.py master 80
python SHVC-SOUND_python/tools/ble_player.py spc-gain 2
python SHVC-SOUND_python/tools/ble_player.py spc-gain 0
python SHVC-SOUND_python/tools/ble_player.py spc-gain 1
python SHVC-SOUND_python/tools/ble_player.py note
```

`--address`で対象ESP32のアドレスを指定できる。複数台がある場合は指定して使う。
SPCはWindowsで復元スタブを作り、RAMスナップショットとまとめて送る。
MIDIファイルはWindowsでテンポマップを適用して時刻付きイベントへ変換し、ESP32の時計で演奏する。
WAVはWindowsでBRRと小さなSPC700再生プログラムへ変換し、HSP1形式で送る。
CLIの`--brr-cache`は同じWAVを指定レートで事前にエンコードしたBRRを使う場合の省略手段。
この場合はキャッシュ全体を使い、`--seconds`による切出しは行わない。
タイプ0/1対応、タイプ2非対応。最大30000イベント・24時間、SysEx・クロック・圧力イベントは対象外。
密集したイベントはバス処理時間による遅延があり、厳密なサンプル単位のタイミングではない。

## BLEプロトコル v1

制御サービス: `89e30000-3c3b-4df7-a74a-25fdd879b40c`
WRITE指示: `89e30001-3c3b-4df7-a74a-25fdd879b40c`
READ/NOTIFY状態: `89e30002-3c3b-4df7-a74a-25fdd879b40c`
別サービスに標準BLE MIDI UUIDを持つ。制御サービスを広告する。
接続は1台を想定。ペアリングや暗号化を要求せず、接続できる端末が操作できる。

指示はlittle endianの`uint16 sequence, uint8 opcode, payload`。
WRITE応答だけを完了と扱わず、同じsequence/opcodeのNOTIFYを待って次の指示を送る。
最大244バイト。MTU23でも転送可能で、MTU交渉後はチャンクを拡大する。
状態は20バイトの`<HBBIIBBHI`:
sequence、opcode、結果、受信済バイト数、総バイト数、モード、flags、音量、欠落数。
flags: bit0 mute、bit1 MIDI loop、bit2 boot autoplay、bit3 SPC音量機能対応。
bit3がある場合、SPCモードまたはopcode11への応答の音量欄はSPC倍率のQ8値（256=1倍）。
それ以外は従来どおりMIDI master（0〜127）。旧ファームのSPC状態をQ8として解釈しない。
結果: 0成功、1不正指示/モード、2位置/CRC/曲形式不一致、3保存失敗、4ハードウェア失敗。

|Opcode|Payload|機能|
|---|---|---|
|1|なし|状態|
|2 / 3|なし|保存曲再生 / 停止|
|4|bool 1byte|mute|
|5|0..127 1byte|MIDI master|
|6|なし|リアルタイムMIDIモード|
|7|channel 0..15, CC, value|MIDI CC|
|8 / 9|bool 1byte|MIDI loop / boot autoplay|
|10|channel, program|MIDI音色|
|11|gain uint16（0〜1024、256=1倍）|SPC/WAV初期音量。SPC再生中は再読み込み、停止中は次回再生用に保存。MIDI再生中は拒否|
|16|size uint32, CRC32 uint32|受信開始|
|17|offset uint32, bytes|順序付きデータ|
|18 / 19|なし|CRC・形式検証して保存 / 中止|

CRC32はPythonの`zlib.crc32`と同じ。30秒データが来ない場合と切断時は未完了受信を破棄する。
BLEコールバックはキューに入れるだけで、SHVC-SOUNDバスとファイル操作はloop側で行う。
MIDIキューがあふれた場合は欠落数を増やして全ノートを止める。

曲形式は16バイトのヘッダーに続くデータ。詳細は`tools/ble_song.py`。
SPC: `<4sHHB4s3x`、magic HSP1、stub address、stub length、start signal、ports、65536バイトRAM、stub。
MIDI: `<4sIII`、magic HTM1、event count、duration ms、reserved。各イベントは`<IBBBx`の8バイト。
SPC復元スタブがRAM上部を上書きする既存の制約は残る。

ライブラリAPIは[Espressif BLE](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ble.html)と
[Bleak Client](https://bleak.readthedocs.io/en/latest/api/client.html)に準拠する。
音量処理は[S-DSPレジスタの仕様](https://snes.nesdev.org/wiki/S-DSP_registers)の符号付きマスター・エコー音量に従う。

## 2026-10-04の検証

- ESP32コア3.3.12でビルドし実機へ書込み。アプリ領域3 MB / LittleFS 896 KBのパーティションを確認。
- Windows / Bleak 3.0.2で接続、状態取得、ミュートON/OFF、MIDI master / CC / Program操作を確認。
- 標準BLE MIDI経由のノート送信、時刻付きMIDIファイルの保存・演奏・末尾停止を確認。ユーザーがド・ミ・ソを可聴確認。
- 不正offset、CRC不一致、受信途中で切断した場合に前の保存曲が残ることを確認。
- SPCを66376バイトBluetooth転送して保存・再生。ESP32のリセット後に保存曲の自動再生とBluetooth再接続を確認。ユーザーがMegalopolisを可聴確認。
- 短いWAV由来のBRRを含む66417バイトの曲データをBluetooth保存し、復元・再生開始の成功応答を確認。WAV自体の今回の可聴確認は未取得。
- MIDIテンポマップ、タイプ2拒否、MTU23分割とCRC、状態flags、WAVレイアウト・ワンショットフラグ・入力形式・RAM上限のオフラインテスト6件が成功。GUIの初期化・終了も確認。

ハードウェア回帰テストは`tools/ble_smoketest.py`。保存曲を書き換えるため明示的に実行する。
SPC音量の専用テストは`tools/ble_spc_gain_smoketest.py --final-gain 1`。
保存曲は変更せず、不正指示、0倍の即時消音、0.5倍と最終倍率の再読み込み、同一倍率の再読み込み省略、再接続を確認する。
`--final-gain 4`を指定すると試験後は最大倍率で再生する。
純粋な音量パッチ処理は`tools/test_spc_volume.cpp`をESP32のC++コンパイラで
`-std=gnu++17 -fsyntax-only`指定してコンパイル時に検証できる。

### SPC音量の追加検証（2026-10-04）

- 追加ファームをビルドしてCOM16へ書込み。保存曲の復元と起動時の1倍設定をUSBログで確認。
- Pythonの7件のオフラインテストとC++のコンパイル時テストが成功。
- 書込み後はBLE広告が見えてもGATTサービス取得がタイムアウトした。ESP再起動、キャッシュを使わない接続、USBを外した状態でも復旧せず、WindowsのBluetoothをOFF→ONにした後に復旧した。
- 不正な長さ・上限超過の倍率指示を拒否し、設定値が変わらないことを確認。
- 0倍の消音指示は0.03秒、0.5倍の再読み込みは45.78秒、同じ0.5倍の再指定は0.09秒、4倍の再読み込みは45.78秒で成功。
- BLE再接続後も4倍設定・SPC再生状態・欠落数0を確認。保存曲は試験中に変更していない。曲名はプロトコルから取得しておらず、その後ユーザーがSuper Mario Worldのタイトル曲と可聴確認した。Megalopolisを再生中という当初の報告は誤り。
- ユーザーは最大設定でも音量が変わらないと確認。手元のSuper Mario WorldタイトルSPC（`song.spc`）は左右マスター音量が元から127、エコー音量0。4倍指定でも上限127で止まり、このマスター音量方式では増幅の余地がない。イヤホンを駆動するアナログ出力の能力も増えない。
- 通常の自動検出接続とCLIのSPC倍率操作で、追加した分岐の配置が誤っていた不具合を修正。アドレスを指定した専用実機テストではこの不具合を検出できなかった。自動検出接続とCLI指示の回帰テストを追加。
- NVS保存の成功応答は確認したが、追加版の電源再投入後の倍率保持試験は未実施。

### LED表示の追加検証（2026-10-04）

- ユーザーが対象LEDをESP32 DevKit上の青LEDと確認。DevKit V1のボード定義はGPIO2、rev0.4のPCBではU1のIO2は他の回路に未接続と確認。
- 状態表示を別タスクで追加してビルド・COM16書込みを実施。既存のPython回帰テスト9件が成功。
- Super Mario WorldのタイトルSPCを66376バイト送信して保存・SHVC転送・再生開始が成功。欠落数0、SPC倍率4倍を確認。
- USBログで受信時の`LED state=1 pin=2`と再生開始後の`LED state=3 pin=2`を確認。高速点滅はSHVC転送中のLOADING状態で別タスクが生成する。実物LEDの目視確認はユーザー側で行う。
- ファーム再書込みに伴うESPリセット後も保存曲と4倍設定が維持された。

パラメータを長時間変更し続ける負荷試験や、他OS・BLE MIDI専用アプリ・複数クライアントは未検証。


## Android WAV streaming extension (2026-10-04)

Windows GUIの上記ワンショットWAVとは別に、Android 0.2.0は全曲のBRRストリーミングに対応する。
既存の20バイト応答を使い、mode 6がPCMストリーミング。flags bit5はウィンドウ転送、bit6はWAVストリーミング、bit7はパケットCRC付きファイル転送を示す。

|Opcode|Payload|用途|
|---|---|---|
|20|offset u32, bytes|従来の応答省略ファイルデータ|
|21|offset u32, chunk CRC32 u32, bytes|CRC付きファイルデータ。INFOでウィンドウを確認|
|22|offset u32|検証済み受信位置でファイル再送を開始|
|32|rate u16, BRR byte total u32, optional channels u8|WAV開始。rate 8000/16000/32000、channels省略時1、指定時1/2|
|33|offset u32, BRR bytes|応答付きWAVデータ|
|34|なし|プリフィル後、DSP再生を開始|
|36|offset u32, chunk CRC32 u32, BRR bytes|応答省略WAVデータ。INFOで受信位置を確認|
|37|offset u32|検証済み受信位置でWAV再送を開始|

ステレオのデータはBRR 9バイトを左・右の順に交互に並べる。各パケットは18バイトの整数倍。受信位置と総量は両チャンネルの合計。DSP voice0は左、voice1は右へ出し、同一pitchとKON=3で開始する。
ステレオARAMは左$0400-$78FF、右$7900-$EDFF、DIRは$F700。各リング末尾のBRRヘッダーにEND/LOOPを付け、次は各リング先頭へ戻る。残りのメモリーと$0200-$0357の常駐コードを上書きしない。
SPC700ドライバcommand9はページ内だけの3バイト転送。ページ末尾の1〜2バイトは既存command1/2で処理する。`tools/test_pcm_page_bulk.py`は全256オフセットとリング折返しを検証する。
プリフィルの最初のパケットはチャンネル別にARAMから読み戻して照合する。再生中の供給不足はmode5/code6で停止。切断も停止し、保存SPCは変更しない。


## Optional amplifier control (2026-10-05)

The default remains external/jack output. The rev0.4 KiCad netlist verifies GPIO33/VOL_PWM -> R6 10k -> AMP_VC, with R5 5.6k and C5 10u to GND, then U6 pins 2 and 8. NXP TDA7053A documentation defines those pins as DC volume controls. A fixed-gain TDA7053 is a separate output profile and does not enable that PWM control. See [NXP TDA7053A datasheet](https://www.nxp.com/docs/en/data-sheet/TDA7053A.pdf) and [Philips TDA7053 datasheet](https://dtsheet.com/doc/260133/philips-tda7053).

| Opcode | Payload | Behavior |
|---|---|---|
| 12 AMP_PROFILE | uint8 0/1/2 | External/DC TDA7053A/fixed-gain TDA7053. Persisted in NVS. |
| 13 AMP_LEVEL | uint8 0..255 | PWM level; only profile 1. Persisted. Does not restart SPC. |
| 14 AMP_FADE | uint32 LE 1..60000 ms | SPC-only fade to zero; profile 1. Acknowledges start immediately. |
| 15 AMP_STATE | empty | Read profile, target level and envelope state. Legacy firmware rejects with code 1. |

Replies keep the 20-byte format. For opcodes 12..15, the master field holds target level in bits 0..7, profile in 8..9, active fade in bit 10 and completed fade in bit 11. received holds the currently written PWM duty, total holds remaining fade milliseconds. All other replies retain previous meanings. STOP/new PLAY resets the envelope; loading/mute/error drives zero; only profile 1 can emit nonzero GPIO33 PWM. Default target level is 160/255. The waveform remains 20 kHz, 8-bit, as in the pre-existing firmware.

Android 0.2.2 starts amplifier fade within each track's timer (ID666 fade duration or final two seconds). Current external output has no controlled attenuation: do not interpret firmware duty tests as audible fading. The compile-time envelope check covers disabled/muted profiles and unsigned millis rollover. Initial DSP gain still requires a reload and is never used as a live fade.
