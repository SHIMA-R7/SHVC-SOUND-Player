# ESP32 r0.4：PCからSPCを再生する手順（2026-10-04）

対象は30ピンのESP32 DevKit V1（DOIT、ESP32-WROOM-32）を載せる基板。
ESP32-C6／S3／WROVER用ではない。

## 使うファーム

- `SHVC-SOUND_python/esp32_spc_uploader/`：今回追加したSPCファイル転送用。
- `SHVC-SOUND_python/esp32_ble_midi/`：既存のBLE／USB MIDI演奏用。SPCファイル転送とは別のファーム。

転送用は既存の`spc_play.py`・`spc_gui.py`と同じ500000bpsのバイナリ通信を使う。
RESET、SETADDR、SENDBYTES、READPORT、SETVOLUME、WRITEPORTに対応する。
64バイトごとの転送応答も維持。バス制御は既存のr0.4用`spc_bus.h`をコピーしたもの。
GPIO33でアンプPWM音量を制御し、起動時は音量0・MUTE有効。
RESETは消音し、実行開始コマンドでMUTEを解除する。

## 準備と書き込み

Python 3とpyserial、GUIを使う場合はTkinterを用意する。
`python -m pip install pyserial`で依存ライブラリを入れる。
Arduino CLIにESP32コアをインストールする。実機確認したバージョンは3.3.12。
`arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json`
の後、`arduino-cli core install esp32:esp32@3.3.12`を実行する。
COM番号は`python -m serial.tools.list_ports -v`で確認する。

PowerShellで`SHVC-SOUND_python/esp32_spc_uploader`へ移動して実行する：

```powershell
# ビルドのみ
powershell -ExecutionPolicy Bypass -File .\build.ps1

# ESP32をUSB接続してポートを確認した後、ビルドして書き込む
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Port COM5
```

`COM5`は例。実際のESP32のCOMポートに置き換える。
CLIはPATH上の`arduino-cli`を使う。`-ArduinoCli`で実行ファイル、`-ConfigFile`で設定を指定できる。
日本語パスを避けるため、一時フォルダのASCIIパスにソースをコピーしてビルドする。
生成した`.bin`は`esp32_spc_uploader/build/`にも保存する。
書き込みが接続待ちになる場合はESP32のBOOTボタンを押しながら再試行する。
シリアルモニターやGUIがCOMポートを開いている場合は先に閉じる。

## 組み立て後の確認順

基板の組み立て・通電確認は既存の組み立て説明書に従う。
以下はソフトウェア側の確認手順。

1. 書き込み後、`SHVC-SOUND_python`で`python tools/esp32_check.py --port COM5`を実行する。
   `IPL ports: AA BB`と`IPL OK`が出れば、リセット・読み出し・音量コマンドの往復を確認できた。
   モジュールが接続されていなければRESETはエラーになる。成功を装うドライランは設けていない。
2. テスト音を送る。アンプ音量32は小さい値から試すための初期値で、可聴音量は現物で調整する。

```powershell
python .\spc_play.py COM5 your-song.spc --test --only-stub --amp-volume 32
```

3. テスト音が出たら、`python spc_gui.py`でGUIを開き、同じCOMポートと手元のSPCを指定する。
   またはCLIで次を実行する：

```powershell
python .\spc_play.py COM5 your-song.spc --amp-volume 32
```

4. 停止はGUIの停止ボタン。または次を実行する：

```powershell
python -c "from spc_play import stop; stop('COM5')"
```

## 残る制限

2026-10-04：Arduino-ESP32 3.3.12、FQBN `esp32:esp32:esp32doit-devkit-v1`でビルド・書込み成功。
基板PCBのU1端子と既存バスドライバのGPIO割り当てを照合した。
新しい基板で全体転送3回連続成功。曲とWAVの可聴再生はユーザーが確認した。

内蔵アンプの正常動作は未確認。今回の確認はアンプを通らない出力で行った。
アンプの型番違い、J1バイパス、WAVの手順は[実機確認結果](esp32-playback-results.md)を参照。
既存のPC側復元スタブは通常再生時824バイトで、RAMの`$FC88-$FFBF`を上書きする。
この領域を使う曲は壊れる可能性がある。今回のESP32移植はこの問題を修正していない。
付属SPCは解析時に「Super Mario World / Title」、RAM65536バイト・DSP128バイトと確認済み。
ビルド成功やIPL応答だけでは曲の再生成功までは保証しない。
