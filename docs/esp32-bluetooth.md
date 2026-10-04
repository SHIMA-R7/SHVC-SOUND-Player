# ESP32 Bluetooth Player

WindowsからBLEでSPCの保存・再生、MIDIファイルの保存・再生、リアルタイムMIDI演奏とパラメータ操作を行う。
SPCとMIDIシンセは同じSPC700を使うため、同時再生ではなくモードを切り替える。
SPC再生には動作確認済みのESP32用バス制御を共用する。

## Windows操作

```powershell
python -m pip install bleak mido pyserial
python SHVC-SOUND_python/tools/ble_player_gui.py
```

この端末では`SHVC-SOUND_python/start_ble_player.cmd`のダブルクリックでも起動できる。
必要ライブラリは`tools/ble_requirements.txt`にもまとめている。

ESP32へ下記のファームを書き込んでから、WindowsのBluetoothを有効にして「Bluetooth接続」を押す。
接続名は`SHVC-SOUND Player`。操作画面がBLEサービスから自動検出する。
通常のBluetooth設定画面でCOMポートを作る方式ではない。

「SPC / MIDIを選ぶ」→「送信して再生」で曲をESP32内へ保存して再生する。
SPCは保存完了後、SHVC-SOUNDへの64 KB転送に約50秒かかる。その間は消音し、完了後に曲が鳴る。
最後に正常保存した曲は、給電を続ければPC切断後も動作し、電源を入れ直したときも再生する。
「電源投入時に再生」を解除すると自動再生を停止する。
初期曲をローカルで組み込んだ場合、まだ受信曲がないときは初期曲を使う。

|操作|SPC|MIDI|
|---|---|---|
|再生・停止・ミュート|対応|対応|
|音量|送信前のSPC音量倍率でDSP初期値を変更|全体音量、チャンネル音量(CC7)、expression(CC11)|
|パン・サステイン|曲プログラムに従う|CC10、CC64|
|音色・ピッチベンド|曲プログラムに従う|Program Change、Pitch Bend|
|ループ|元の曲のループ|ファイル末尾から再開。設定を保存|

SPC音量倍率は初期DSP値だけを変更する。曲が音量レジスタを書き直すと効果が変わるため、
汎用的なリアルタイム音量・テンポ操作ではない。倍率変更は再送信が必要。
MIDIの設定もファイル内のCC・音色イベントで上書きされる場合がある。

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
python SHVC-SOUND_python/tools/ble_player.py mute 1
python SHVC-SOUND_python/tools/ble_player.py mute 0
python SHVC-SOUND_python/tools/ble_player.py midi
python SHVC-SOUND_python/tools/ble_player.py master 80
python SHVC-SOUND_python/tools/ble_player.py note
```

`--address`で対象ESP32のアドレスを指定できる。複数台がある場合は指定して使う。
SPCはWindowsで復元スタブを作り、RAMスナップショットとまとめて送る。
MIDIファイルはWindowsでテンポマップを適用して時刻付きイベントへ変換し、ESP32の時計で演奏する。
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
sequence、opcode、結果、受信済バイト数、総バイト数、モード、flags、MIDI音量、欠落数。
flags: bit0 mute、bit1 MIDI loop、bit2 boot autoplay。
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

## 2026-10-04の検証

- ESP32コア3.3.12でビルドし実機へ書込み。アプリ領域3 MB / LittleFS 896 KBのパーティションを確認。
- Windows / Bleak 3.0.2で接続、状態取得、ミュートON/OFF、MIDI master / CC / Program操作を確認。
- 標準BLE MIDI経由のノート送信、時刻付きMIDIファイルの保存・演奏・末尾停止を確認。ユーザーがド・ミ・ソを可聴確認。
- 不正offset、CRC不一致、受信途中で切断した場合に前の保存曲が残ることを確認。
- SPCを66376バイトBluetooth転送して保存・再生。ESP32のリセット後に保存曲の自動再生とBluetooth再接続を確認。ユーザーがMegalopolisを可聴確認。
- MIDIテンポマップ、タイプ2拒否、MTU23分割とCRC、状態flagsのオフラインテスト4件が成功。GUIの初期化・終了も確認。

ハードウェア回帰テストは`tools/ble_smoketest.py`。保存曲を書き換えるため明示的に実行する。
パラメータを長時間変更し続ける負荷試験や、他OS・BLE MIDI専用アプリ・複数クライアントは未検証。
