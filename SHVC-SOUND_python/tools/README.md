# tools — 実機向けの補助ツール

`spc_realtime.ino` を書き込んだ Arduino + SHVC-SOUND で使う。
いずれも `SHVC-SOUND_python` の `midi2spc` / `spc_play` を読み込むので、このフォルダに置いたまま実行する。

## 録音をそのまま鳴らす(BRRストリーミング)

| ツール | 内容 |
|---|---|
| `pcm_stream.py` | 録音をBRRに変換し、ARAMのリングバッファへ書き足しながら最後まで鳴らす。`--loop-whole` で短い音声をS-DSPだけでループ。`--selftest` でSPC700側ドライバをシミュレータ検証 |
| `pcm_clip_test.py` | ARAMに収まる数秒だけを一括転送して鳴らす(実現性確認用) |
| `zundamon_talk.py` | VOICEVOX(ずんだもん)でセリフを合成し、`pcm_stream.py --loop-whole` で鳴らす |
| `morning_call.py` | 指定時刻にモーニングコール → 曲のストリーミング再生(待機中はアイドルスリープを抑止) |

```bash
python pcm_stream.py song.wav --rate 8000 --peak 0.8
```

仕組み: ARAM `$0400-$FEFA` をBRRのリングバッファにし、ボイス0がバッファ末尾(loop+end)で先頭へ戻り続ける。
SPC700上のドライバ(`PCM_DRIVER`、IPLで `$0200` へ転送)は、ホストの `$F4` の変化を合図に `$F7` のコマンドで分岐する。

| `$F7` | 動作 |
|---|---|
| 0 | DSPレジスタ書き込み(`$F5`=レジスタ, `$F6`=値) |
| 1 / 2 | 1 / 2バイトをリングバッファへ書き、ポインタ(`$02-$03`)を進める |
| 3 | ポインタを返す |
| 4 | DSPレジスタ読み出し |
| 5 | ポインタ設定(起動直後、IPLジャンプの残りポート値を指示と誤認して1回書いてしまうので必ず合わせ直す) |
| 6 | ポインタ位置の1バイトを返す(読み返し検査用) |

Arduino側コマンド: `CMD_PCMCHUNK`(0x0C) / `CMD_DRVQUERY`(0x0D) / `CMD_DRVPEEK`(0x0E)。

注意: `midi2spc/brr.py` の予測フィルタの丸めは実機S-DSPと完全には一致しない。長い録音では `--filter0`(予測なし)も選べる。

VOICEVOXエンジンはリポジトリに含めない。`tools/voicevox_engine/` に展開するか、`--engine-dir` / 環境変数 `VOICEVOX_ENGINE_DIR` で場所を指定する。
音声を公開する場合はクレジット「VOICEVOX:ずんだもん」が必要。

## 自動採譜・MIDIの整理

| ツール | 内容 |
|---|---|
| `midi_reduce.py` | トラックを選んでチャンネル・音色を振り直す(オーケストラ譜の書き出し向け) |
| `separate_transcribe.py` | Demucsでパート分離 → Basic Pitchでパートごとに採譜(チューニング補正つき) |
| `score_transcribe.py` | 拍の升目にそろえてメロディ・和音・ベースを起こす |
| `vocal_melody.py` | 分離したボーカルからpYINで主旋律を取る |
| `midi_arrange.py` / `midi_thin.py` | 採譜結果をメロディ/和音/ベースに整理 / 重ねと音数を間引く |

楽器演奏の録音ならそこそこ使えるが、歌入りのポップスや合唱は崩れやすい。
必要なもの: basic-pitch(ONNX), librosa, pretty_midi, demucs + torch(CPU), soundfile。

## 診断

| ツール | 内容 |
|---|---|
| `port_probe.py` | リセット前後の `$F4-$F7` を読む(配線の化けの確認) |
| `probe_retry.py` | 正常な値が読めるまで繰り返す |
