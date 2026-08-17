# SHVC-SOUND Android アプリ (作業中)

PCを使わず、Android端末とArduinoをUSB(OTG)で直結して`.spc`を再生するためのアプリ。
`SHVC-SOUND_python/spc_play.py` と同じロジックをKotlinへ移植している。

実体のAndroid Studioプロジェクトは `C:\Users\<user>\AndroidStudioProjects\SHVCSoundPlayer`
にある。このフォルダはソースコードの参照・バックアップ用。

## 進捗

- [x] プロジェクト作成 (Empty Views Activity, Kotlin, minSdk 26, package `com.shvc.soundplayer`)
- [x] `usb-serial-for-android` 依存関係の追加 (JitPack経由)
- [x] `AndroidManifest.xml` に `android.hardware.usb.host` の feature 宣言を追加
- [x] `SpcFile.kt` — `.spc`ファイル解析 (Python版 `SpcFile` クラス相当)
- [x] `SpcController.kt` — Arduinoとの通信プロトコル (`spc_uploader.ino`と同一プロトコル)
- [x] `StubBuilder.kt` — DSPレジスタ復元コード生成 (Python版 `build_final_stub`/`boost_master_volume`相当)
- [x] 上記3ファイルのビルド確認 (`BUILD SUCCESSFUL`、実機Android Studioで確認済み)
- [ ] `MainActivity.kt` + レイアウト(UI)
- [ ] USBデバイス接続・パーミッション処理
- [ ] 実機での動作確認(Arduino実機とのUSB直結)

## 既知の注意点

- `UsbSerialPort.write()` はこのバージョンのライブラリでは戻り値なし(書き込みバイト数を
  返さない)。全バイト書き終わるかタイムアウトで例外を投げるまでブロックする前提で実装している。
- プロトコル定数(CMD/ACK値、PING_INTERVAL=64、ボーレート500000)は
  `SHVC-SOUND_python/spc_uploader/spc_uploader.ino` と完全に一致させること。
  どちらか一方だけ変更すると通信できなくなる。
