# SHVC-SOUND スタンドアロンプレイヤー

Arduino Nano (Type-C / ATmega328P) で SHVC-SOUND(スーファミ音源モジュール: S-SMP + S-DSP + ARAM + DAC)を駆動し、
`.spc` ファイルを実チップで再生するプロジェクト。音声は TDA7053A(ステレオBTL)で増幅し3.5mmジャックへ出力する。

## 構成

| ディレクトリ | 内容 |
|---|---|
| `SHVC-SOUND-KiCad_project/` | 基板設計(KiCad)。スキーマ・PCB・カスタムフットプリント |
| `SHVC-SOUND_python/` | 再生ソフト一式 |
| `SHVC-SOUND_python/spc_play.py` | PC側。`.spc` を解析しシリアル経由でArduinoへ転送する |
| `SHVC-SOUND_python/spc_uploader/` | Arduino Nano側。シリアルコマンドをSPC700 IPL ROMプロトコルへ変換する |

## 使い方

Arduino IDE で `spc_uploader/spc_uploader.ino` を Nano に書き込み、以下を実行する。

```bash
python spc_play.py COM3 song.spc
```

`pyserial` が必要:

```bash
pip install pyserial
```

診断用フラグ: `--test`(強制ノイズ再生)、`--skip-bulk`、`--low-addr`、`--only-stub`

## 配線 (Arduino Nano ⇔ SHVC-SOUND 24pin)

| Nano | SHVC-SOUND pin | 信号 |
|---|---|---|
| D2-D9 | 7-14 | D0-D7 |
| A0 | 3 | A0 |
| A1 | 4 | A1 |
| A2 | 5 | /WR |
| A3 | 6 | /RD |
| A4 | 15 | /RESET |
| D10 | 20 | /MUTE(常時HIGH固定) |
| - | 2 / 1 | CS→+5V / /CS→GND 直結 |
| - | 18, 24 | VCC, VS → +5V |
| - | 19, 23 | GND |
| - | 21, 22 | Audio-L / Audio-R → アンプ入力 |

ロジック系(5V)とアンプ系(12V)は別電源。Arduinoのレギュレータからアンプ用12Vを取らないこと。

## 既知の問題

- **復元スタブが曲データを上書きする**: `spc_play.py` のDSP復元スタブは約800バイトあり `$FFC0` 直下(≒`$FC9B`)に配置されるが、
  この領域はメインRAM転送範囲(`$0100-$FFBF`)と重なるため曲データを約800バイト破壊する。
  この領域をサンプルやエコーバッファに使う曲ではノイズが出る。エコーバッファ領域への配置か、スタブのループ化による小型化が要検討。
- **基板のDRC違反が未修正**: シルク重なり2件、シルクが銅箔にかかる6件、フットプリント型不一致1件、ライブラリ不一致1件。
- 実機での動作確認は未完了。

## ライセンス / 帰属

基板設計の一部は [OpenSFC](https://github.com/starlightk7/OpenSFC)(© 2025 starlightk7、CERN-OHL-S)に由来する。
詳細と再頒布時の義務は `SHVC-SOUND-KiCad_project/SHVC-SOUND-KiCad/THIRD_PARTY_NOTICE_OpenSFC.txt` を参照。
公開・頒布する場合は CERN-OHL-S 3.3 に従い、改変内容の要約を同NOTICEに追記すること。
