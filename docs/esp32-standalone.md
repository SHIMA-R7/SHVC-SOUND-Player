# ESP32単体でSPCを繰り返し再生

`SHVC-SOUND_python/esp32_spc_standalone`は、ESP32のフラッシュ内のSPCを
電源投入時にSHVC-SOUNDへ転送して再生する。PCからの曲送信は不要。
曲のSPC700プログラムをそのまま動かし、ホスト側の時間制限・フェードは適用しない。
そのため、元の曲にループがある場合はそのループが続く。任意の終了する曲を強制ループへ変える機能ではない。

## 作成と書込み

手元のSPCを用意し、`SHVC-SOUND_python`から実行する。

```powershell
python -m pip install pyserial
python tools/prepare_standalone_spc.py path\to\your-song.spc
powershell -ExecutionPolicy Bypass -File esp32_spc_standalone\build.ps1 -Port COM5
```

Arduino CLIとESP32コア3.3.12が必要。`-ArduinoCli` / `-ConfigFile`で環境を指定できる。
ビルドは日本語パスを避けて一時フォルダへコピーして実行する。
GPIO割当とバス制御はSPC転送用ファームの`spc_bus.h`を共用する。

生成した`spc_data.h`は曲のRAMと復元スタブを含むためGitから除外している。
ファームのビルド出力も曲を含む。曲データ入りのヘッダー・バイナリは公開しない。
このリポジトリの公開コードだけでは、曲を用意せずにビルドすることはできない。

## 電源と出力

PCの電源を落とした後も、別のUSB電源または基板の電源から給電を続ける。
PCがUSB給電を停止するとESP32も止まる。ESP32を再起動すると曲の転送からやり直す。
基板の5V/3.3V系が正しいことを確認して使う。

今回の実装はアンプPWMを0に設定し、[J5またはU6を抜いてバイパスしたJ1](esp32-playback-results.md)
を外部アンプのライン入力へつないで使う。U6の内蔵アンプを駆動する構成は未検証。
PC転送ファームとは別のスケッチで、シリアルは115200bpsのテキスト診断。
SPC GUIを使いたい場合は`esp32_spc_uploader`を書き戻す。

## 実機確認

2026-10-04に手元のSimCity / MegalopolisのSPCをローカル生成データへ変換し、
ビルド・フラッシュ書込みを行った。ビルド348627バイト、静的RAM22320バイト。
開始時のIPL AA/BB、全ブロックACK、復元スタブの開始ハンドシェイクとPLAYINGを[シリアル記録](standalone-boot-2026-10-04.txt)で確認した。ユーザーもスタンドアロンでの音声再生を確認した。
PCを実際にシャットダウンした状態での給電継続や長時間の音声ループは、ユーザー側で確認する。

既存の復元スタブがRAM $FC88-$FFBFを上書きする制限は残る。別のSPCでは
その領域の曲データに影響する可能性がある。転送・復元失敗時は消音し、5秒後に再試行する。
