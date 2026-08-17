# SHVC-SOUND スタンドアロンプレイヤー

Arduino Uno R3 / Nano (ATmega328P・5Vロジック) で SHVC-SOUND(スーファミ音源モジュール: S-SMP + S-DSP + ARAM + DAC)を駆動し、
`.spc` ファイルを実チップで再生するプロジェクト。音声は TDA7053A(ステレオBTL)で増幅し3.5mmジャックへ出力する。

## 構成

| ディレクトリ | 内容 |
|---|---|
| `SHVC-SOUND-KiCad_project/` | 基板設計(KiCad)。スキーマ・PCB・カスタムフットプリント |
| `SHVC-SOUND_python/` | 再生ソフト一式 |
| `SHVC-SOUND_python/spc_gui.py` | **GUIアプリ**(Tkinter製)。プレイリスト再生・音量調整・ROM解析 |
| `SHVC-SOUND_python/spc_play.py` | PC側。`.spc` を解析しシリアル経由でArduinoへ転送する(CLI/GUI共用) |
| `SHVC-SOUND_python/rom_tools.py` | スーファミROMの内部ヘッダ解析(マッパ判別・チェックサム検証) |
| `SHVC-SOUND_python/spc_uploader/` | Arduino側。シリアルコマンドをSPC700 IPL ROMプロトコルへ変換する |
| `SHVC-SOUND_python/hw_selftest/` | Arduino単体で動く自己診断。PCなしでノイズを鳴らして配線を検証する |
| `docs/minimal-bringup.md` | 最小構成での実機立ち上げ手順と配線表 |

## まず実機で音を確認する

いきなり `spc_play.py` を試す前に、アンプと12V系を外した最小構成で
`hw_selftest/hw_selftest.ino` を走らせる。ハードの問題か転送ソフトの問題かが一発で切り分けられる。
手順と配線表は [docs/minimal-bringup.md](docs/minimal-bringup.md) を参照。

## GUIアプリ

```bash
python spc_gui.py
```

- プレイリストに `.spc` をまとめて登録して再生。ID666タグ(曲名・ゲーム・作曲者)を表示
- DSP音量倍率とアンプPWM音量をスライダーで調整
- 転送はワーカースレッドで実行され、進捗バーとログをリアルタイム表示。中止も可能
- **フォルダ監視**: エミュレータのSPC出力先を指定しておくと、新しくダンプされた
  `.spc` を自動でプレイリストに追加する
- ROM解析タブ: 吸い出したROMのタイトル・マッパ(LoROM/HiROM/ExHiROM)・容量・
  リージョン・チェックサムを表示

### ROMからのSPC抽出について

**ROMの中に `.spc` は入っていない**ため、直接抽出はできない。
`.spc` はSPC700が曲を再生中の ARAM 64KB + DSPレジスタ + CPUレジスタの
スナップショットであり、ROMにあるのはサウンドドライバ・BRRサンプル・
シーケンスデータがバラバラに格納されたもの。ARAMの完成イメージは
ゲームを実際に起動して初めて組み上がる。

実用的な手順は、SPCダンプ機能を持つエミュレータ(Mesen2、bsnes/higan、
一部のSnes9xビルド)でROMを動かし、曲の再生中にダンプすること。
出力先をGUIの「フォルダを監視」に指定しておけば、ダンプした瞬間に
プレイリストへ入って実機で鳴らせる。

## CLIでの使い方

Arduino IDE で `spc_uploader/spc_uploader.ino` を書き込み、以下を実行する。

```bash
python spc_play.py COM3 song.spc
```

`pyserial` が必要:

```bash
pip install pyserial
```

診断用フラグ: `--test`(強制ノイズ再生)、`--skip-bulk`、`--low-addr`、`--only-stub`

## 配線 (Arduino ⇔ SHVC-SOUND 24pin)

| Arduino | SHVC-SOUND pin | 信号 |
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
- **基板のSHVC-SOUNDフットプリントに1番ピンの表示が無い**: `SHVC-SOUND-MB.kicad_mod` は
  パッド24個すべてが丸、シルクにピン番号も1番マーカーも無い(リファレンス指定子のみ)。
  コネクタ自体にキーが無く逆挿しできてしまうため、シルクに `1` の印字と極性マークを追加すべき。
- **基板はArduino Nanoフットプリント**(`Module:Arduino_Nano_WithMountingHoles`)。
  Uno R3はピン互換だがフットプリントが合わないため、基板に載せる場合は要変更。ジャンパ配線での検証には支障なし。

## ライセンス / 帰属

基板設計の一部は [OpenSFC](https://github.com/starlightk7/OpenSFC)(© 2025 starlightk7、CERN-OHL-S)に由来する。
詳細と再頒布時の義務は `SHVC-SOUND-KiCad_project/SHVC-SOUND-KiCad/THIRD_PARTY_NOTICE_OpenSFC.txt` を参照。
公開・頒布する場合は CERN-OHL-S 3.3 に従い、改変内容の要約を同NOTICEに追記すること。
