# midi2spc — MIDIをSHVC-SOUND(SPC700 / S-DSP)で鳴らす

MIDIファイルを、スーファミ音源(S-DSP)の制約に落とし込んで演奏するツール。
**PC上のソフトウェアモデル**でも、**実機のSHVC-SOUND**でも鳴らせる。

## 使い方(GUI)

配布用の実行ファイルは `dist/MIDI-to-SHVC-SOUND.exe`。Pythonのインストールは不要。

ソースから起動する場合:

```bash
python midi_gui.py
```

タブ構成:

- **変換・再生** — MIDIを選んで「変換」、そのまま再生 / WAV保存。音量倍率などの設定もここ
- **DSPイベント** — 変換結果として S-DSP に送るレジスタ操作の時系列を一覧表示
- **音色バンク** — BRRサンプルの一覧。選んで「試聴」でドレミが鳴る

起動時に音色バンクのBRRエンコード(十数秒)が走る。終わるまで「変換」は押せない。

exeを作り直すとき:

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name "MIDI-to-SHVC-SOUND" --collect-all sounddevice midi_gui.py
```

## 使い方(コマンドライン)

```bash
python -m midi2spc song.mid
```

```bash
python -m midi2spc song.mid -o out.wav
```

```bash
python -m midi2spc song.mid --dump-events
```

```bash
python -m midi2spc --list-instruments
```

主なオプション:

| オプション | 意味 |
|---|---|
| `-o FILE` | WAVに書き出す(省略時はその場で再生) |
| `--master N` | ボイス音量の全体倍率 0.0-1.0(既定 0.55)。和音が多い曲で歪むなら下げる |
| `--gain N` | 出力全体のゲイン |
| `--tail N` | 曲末尾に足す余韻の秒数 |
| `--dump-events [N]` | S-DSPに送るイベント列を表示 |
| `--no-audio` | 音を出さず変換だけ確認 |

必要なもの: `numpy`(必須)、`sounddevice`(その場で再生する場合のみ)。

## 実機で鳴らす

### 1. Arduinoにファームウェアを書き込む

`spc_realtime/spc_realtime.ino` を書き込む。これは `spc_uploader.ino` の**上位互換**で、
従来の .spc 転送コマンドもそのまま残っているので `spc_gui.py` / `spc_play.py` も
このファームのまま動く。ピン配置は従来と同一。

```bash
arduino-cli compile --fqbn arduino:avr:nano spc_realtime
arduino-cli upload -p COM3 --fqbn arduino:avr:nano spc_realtime
```

### 2. 鳴らす

GUIの「実機で再生」欄でシリアルポートを選び、変換後に「実機へ転送して再生」。
コマンドラインなら:

```bash
python -m midi2spc song.mid --port COM3
```

### 実機再生時に起きること

1. SPC700をリセットしてIPL ROMの転送モードに入る
2. BRRサンプル(約13KB)・サンプルディレクトリ・常駐ドライバをARAMへ転送
3. 常駐ドライバへジャンプ
4. DSPを初期化(エコー無効・DIR設定・マスター音量)
5. レジスタ書き込みイベントをArduinoへストリーム送信

ARAMのメモリマップ:

| アドレス | 内容 |
|---|---|
| `$0200-$0216` | 常駐ドライバ(23バイト) |
| `$0300-$034F` | サンプルディレクトリ(1音色4バイト × 20) |
| `$0400-$3900` | BRRサンプル本体(約13KB) |

### 常駐ドライバ(23バイト)

S-DSPのレジスタはSPC700からしか触れず、ホスト(Arduino)から見えるのは
`$F4-$F7` の4バイトの窓だけ。そこで「`$F5`のレジスタ番号と`$F6`の値をDSPへ
書き写すだけ」のループをSPC700に常駐させ、Arduinoはその窓越しに指示を出す。

```asm
        clrp                    ; ダイレクトページを$00xxに固定
        mov  x,#$00
        mov  $F4,x              ; ACKラッチを初期化
loop:   cmp  x,$F4              ; ホストからの新しい指示待ち
        beq  loop
        mov  x,$F4              ; 新しいシーケンス値
        mov  a,$F5              ; DSPレジスタ番号
        mov  $F2,a              ;   -> DSPADDR
        mov  a,$F6              ; 書き込む値
        mov  $F3,a              ;   -> DSPDATA
        mov  $F4,x              ; ACK(シーケンス値を返す)
        bra  loop
```

曲の解釈はすべてPC側に残るので、SPC700側はこれで足りる。
**音楽ドライバをアセンブリで書く必要はない**のがこの構成の要点。

### 演奏タイミング

発音タイミングはArduinoが持つ。PCは4バイトのレコード
`[待ち時間LE16(100µs単位)][レジスタ番号][値]` を送り、Arduinoは48段の
リングバッファに積んで `micros()` で時刻どおりに実行する。待ち時間は
前のイベントの**予定時刻**から積み上げるので、誤差が累積してテンポがずれない。

PCが送りすぎないよう、Arduinoは1レコード消化するごとにクレジットバイトを返す。
PCは32レコードまで先行送信できる(Arduinoの受信バッファ64バイトとリングバッファ
48段の両方に収まる値)。

## 設計

```
song.mid
   │  smf.py          SMFパーサ(依存ライブラリなし)      ← midi_gui.py / __main__.py が呼ぶ
   ▼
MIDIイベント列
   │  engine.py       ★変換の本体
   ▼
S-DSPレジスタ操作イベント列
   │
   ├─ render.py       S-DSPのソフトウェアモデル → PCで音を出す
   └─ hardware.py     Arduino経由で実チップを鳴らす
```

`engine.py` が出すのは「どのボイスに、どのサンプルを、どのピッチ・音量・ADSRで
キーオンするか」という時系列で、これは実機のS-DSPレジスタ書き込みと1対1に対応する。
つまり `render.py` を差し替えれば、同じ変換結果をそのままハードウェアに流せる。

音色(`instruments.py`)も飾りではなく、実際に **BRR(4bit ADPCM)にエンコードして
デコードし直した波形**を鳴らしている。実機に載せるときはこの `brr_data` を
そのままARAMへ転送すればよい。バンク全体で約14KB、64KBのARAMに十分収まる。

## 再現していること / していないこと

再現している:

- BRRによる4bit量子化(実機と同じ量子化ノイズが乗る)
- 32kHz固定のサンプルレートと4タップ補間による高音のなまり
- **同時発音8ボイス**の制限と、足りないときの音の奪い合い
- 14bit PITCHレジスタ、ADSRエンベロープ、符号付き8bitのVOLL/VOLR
- MIDI側は NoteOn/Off、プログラムチェンジ、CC7/CC10/CC11/CC64、ピッチベンド、テンポチェンジ

再現していない(意図的な簡略化):

- サイクル精度のDSP動作(合成は「ノート単位」でまとめて行う)
- エコー / FIRフィルタ / ピッチモジュレーション / ノイズジェネレータ
- 補間テーブルは実機の512エントリ表そのものではなくガウス窓による近似
- ADSRのDECAY/SUSTAINは、実機の「周期ごとに `env -= (env>>8)+1`」を
  1サンプルあたりの減衰係数に直した閉じた形で計算している(形は同じ)

## テスト

```bash
python test_midi2spc.py
```

43件。実機がなくても確かめられるところを固めてある。特に常駐ドライバは
手でアセンブルした生バイト列なので、簡易SPC700シミュレータ(テスト内に同梱)で
実際に実行して、ACKハンドシェイク・シーケンス値の一周・キーオン1音ぶんの
レジスタ列が正しく届くことを検証している。

**実機での再生は2026-08-18に確認済み。** Arduino Uno + SHVC-SOUND で
rydeen.mid(9240ノート / 約4分半 / DSPレジスタ書き込み120120回)が
最後まで正常に再生できた。

## 実機で音が出ないときの切り分け

1. `spc_gui.py` で .spc が再生できるか — できなければ配線かバスタイミングの問題で、
   MIDI側とは無関係
2. GUIのログで「ドライバへジャンプ」の後にエラーが出るか —
   `常駐ドライバが応答しません` なら、ジャンプ自体かドライバの動作の問題
3. 転送は通るのに無音 — DSPの初期化(FLGのミュート解除、マスター音量)か、
   BRRサンプルのディレクトリ位置(`DIR`レジスタ)を疑う
4. 音は出るがノイズまみれ — エコーがARAMのサンプル領域を上書きしている可能性。
   `initial_dsp_writes()` がFLGのbit5(エコー書き込み禁止)を立てているか確認する
