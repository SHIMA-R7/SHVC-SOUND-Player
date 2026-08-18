#!/usr/bin/env python3
"""
midi_gui.py - MIDI to SHVC-SOUND 変換GUI

MIDIファイルをスーファミ音源(SPC700 / S-DSP)の制約に落とし込んで演奏する
デスクトップアプリ。spc_gui.py と同じくTkinter製。

起動:
    python midi_gui.py

必要なもの:
    pip install numpy sounddevice
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
import wave
from tkinter import ttk, filedialog, messagebox, scrolledtext

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from midi2spc import engine, hardware, instruments, render, smf

try:
    import serial.tools.list_ports as list_ports
except Exception:
    list_ports = None

try:
    import sounddevice as sd
except Exception:
    # PortAudioのDLLが見つからない環境ではImportError以外も飛んでくる。
    # 音が出せなくても変換とWAV保存はできるので、ここでは落とさない。
    sd = None


APP_TITLE = "MIDI to SHVC-SOUND"


class MidiConverterApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("980x720")
        root.minsize(820, 600)

        # ワーカースレッドとの通信用
        self.msg_queue = queue.Queue()
        self.worker = None

        # 変換結果
        self.bank = None
        self.midi_path = None
        self.events = None
        self.audio = None
        self.stats = None

        # 再生位置表示用
        self.play_started_at = None
        self.play_after_id = None

        # 実機再生の中断フラグ
        self.hw_cancel = threading.Event()

        self._build_ui()
        self._refresh_ports()
        self.root.after(100, self._pump_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 音色バンクの構築(BRRエンコード)は数秒かかるので裏で先に済ませておく
        self._start_bank_build()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_convert = ttk.Frame(nb)
        self.tab_events = ttk.Frame(nb)
        self.tab_bank = ttk.Frame(nb)
        nb.add(self.tab_convert, text="  変換・再生  ")
        nb.add(self.tab_events, text="  DSPイベント  ")
        nb.add(self.tab_bank, text="  音色バンク  ")

        self._build_convert_tab(self.tab_convert)
        self._build_events_tab(self.tab_events)
        self._build_bank_tab(self.tab_bank)

    def _build_convert_tab(self, parent):
        # --- 入力ファイル ---
        src = ttk.LabelFrame(parent, text="入力MIDI")
        src.pack(fill="x", padx=6, pady=(6, 4))

        row = ttk.Frame(src)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Button(row, text="MIDIファイルを選択...", command=self._choose_midi).pack(side="left")
        self.midi_var = tk.StringVar(value="(未選択)")
        ttk.Label(row, textvariable=self.midi_var, foreground="#555").pack(side="left", padx=8)

        self.midi_info_var = tk.StringVar(value="")
        ttk.Label(src, textvariable=self.midi_info_var, foreground="#777").pack(
            anchor="w", padx=8, pady=(0, 8))

        # --- 中段: 設定 + ログ ---
        mid = ttk.Frame(parent)
        mid.pack(fill="both", expand=True, padx=6, pady=4)

        opt = ttk.LabelFrame(mid, text="変換設定")
        opt.pack(side="left", fill="y")

        ttk.Label(opt, text="ボイス音量の全体倍率").pack(anchor="w", padx=8, pady=(8, 0))
        self.master_var = tk.DoubleVar(value=0.55)
        self.master_label = ttk.Label(opt, text="0.55")
        ttk.Scale(opt, from_=0.1, to=1.0, variable=self.master_var, orient="horizontal",
                  length=240, command=self._on_master).pack(fill="x", padx=8)
        self.master_label.pack(anchor="e", padx=8)
        ttk.Label(opt, text="S-DSPの音量は符号付き8bitなので、和音が重なると\n"
                            "飽和します。歪むときはここを下げてください。",
                  foreground="#777", justify="left").pack(anchor="w", padx=8, pady=(0, 6))

        ttk.Label(opt, text="出力ゲイン").pack(anchor="w", padx=8, pady=(6, 0))
        self.gain_var = tk.DoubleVar(value=1.0)
        self.gain_label = ttk.Label(opt, text="1.00")
        ttk.Scale(opt, from_=0.2, to=3.0, variable=self.gain_var, orient="horizontal",
                  length=240, command=self._on_gain).pack(fill="x", padx=8)
        self.gain_label.pack(anchor="e", padx=8)

        ttk.Label(opt, text="曲末尾の余韻(秒)").pack(anchor="w", padx=8, pady=(6, 0))
        self.tail_var = tk.DoubleVar(value=1.0)
        self.tail_label = ttk.Label(opt, text="1.0 秒")
        ttk.Scale(opt, from_=0.0, to=5.0, variable=self.tail_var, orient="horizontal",
                  length=240, command=self._on_tail).pack(fill="x", padx=8)
        self.tail_label.pack(anchor="e", padx=8, pady=(0, 10))

        stat = ttk.LabelFrame(opt, text="変換結果")
        stat.pack(fill="x", padx=8, pady=(0, 8))
        self.stat_vars = {}
        for key, label in [("notes", "ノート数"), ("events", "DSPイベント"),
                           ("stolen", "ボイス不足"), ("duration", "長さ"),
                           ("peak", "ピーク")]:
            r = ttk.Frame(stat)
            r.pack(fill="x", padx=8, pady=1)
            ttk.Label(r, text=f"{label}:", width=12, anchor="e").pack(side="left")
            var = tk.StringVar(value="-")
            self.stat_vars[key] = var
            ttk.Label(r, textvariable=var, anchor="w").pack(side="left")
        ttk.Frame(stat).pack(pady=3)

        logf = ttk.LabelFrame(mid, text="ログ")
        logf.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.log_text = scrolledtext.ScrolledText(logf, height=10, wrap="word",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text.configure(state="disabled")

        # --- 実機で再生 ---
        hw = ttk.LabelFrame(parent, text="実機で再生 (SHVC-SOUND)")
        hw.pack(fill="x", padx=6, pady=(4, 2))

        hwrow = ttk.Frame(hw)
        hwrow.pack(fill="x", padx=8, pady=8)
        ttk.Label(hwrow, text="シリアルポート:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(hwrow, textvariable=self.port_var, width=22)
        self.port_combo.pack(side="left", padx=4)
        ttk.Button(hwrow, text="更新", command=self._refresh_ports, width=6).pack(side="left")
        self.hw_play_btn = ttk.Button(hwrow, text="実機へ転送して再生",
                                      command=self._on_hw_play, width=20, state="disabled")
        self.hw_play_btn.pack(side="left", padx=(12, 4))
        self.hw_stop_btn = ttk.Button(hwrow, text="実機を停止",
                                      command=self._on_hw_stop, width=12)
        self.hw_stop_btn.pack(side="left")

        ttk.Label(hw, text="Arduinoに spc_realtime.ino を書き込んでおくこと"
                           "(従来の spc_uploader.ino では実機再生できません)。",
                  foreground="#777").pack(anchor="w", padx=8, pady=(0, 8))

        # --- 操作 + 進捗 ---
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill="x", padx=6, pady=(4, 2))
        self.convert_btn = ttk.Button(ctrl, text="変換", command=self._on_convert, width=12)
        self.convert_btn.pack(side="left")
        self.play_btn = ttk.Button(ctrl, text="▶ 再生", command=self._on_play,
                                   width=12, state="disabled")
        self.play_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(ctrl, text="■ 停止", command=self._on_stop,
                                   width=12, state="disabled")
        self.stop_btn.pack(side="left")
        self.save_btn = ttk.Button(ctrl, text="WAVで保存...", command=self._on_save,
                                   width=14, state="disabled")
        self.save_btn.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="起動中...")
        ttk.Label(ctrl, textvariable=self.status_var).pack(side="left", padx=12)

        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=6, pady=(2, 6))

    def _build_events_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="変換後にS-DSPへ送るレジスタ操作の時系列です。"
                            "実機接続時はこの列をそのままシリアルへ流します。",
                  foreground="#555").pack(side="left")

        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        cols = ("time", "voice", "kind", "inst", "pitch", "vol", "adsr")
        headings = {"time": "時刻(秒)", "voice": "ボイス", "kind": "操作",
                    "inst": "音色", "pitch": "PITCH", "vol": "VOLL/VOLR", "adsr": "ADSR"}
        widths = {"time": 90, "voice": 60, "kind": 80, "inst": 90,
                  "pitch": 80, "vol": 110, "adsr": 90}

        self.event_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.event_tree.heading(c, text=headings[c])
            self.event_tree.column(c, width=widths[c], anchor="center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.event_tree.yview)
        self.event_tree.configure(yscrollcommand=sb.set)
        self.event_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.event_note_var = tk.StringVar(value="(まだ変換していません)")
        ttk.Label(parent, textvariable=self.event_note_var,
                  foreground="#777").pack(anchor="w", padx=8, pady=(0, 6))

    def _build_bank_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="実機のARAMへ転送するBRRサンプルそのものです。"
                            "選んで「試聴」でドレミを鳴らせます。",
                  foreground="#555").pack(side="left")

        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        cols = ("name", "size", "natural", "adsr", "loop")
        headings = {"name": "音色名", "size": "BRRサイズ", "natural": "素の周波数",
                    "adsr": "ADSRレジスタ", "loop": "ループ"}
        widths = {"name": 120, "size": 100, "natural": 110, "adsr": 110, "loop": 70}

        self.bank_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.bank_tree.heading(c, text=headings[c])
            self.bank_tree.column(c, width=widths[c], anchor="center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.bank_tree.yview)
        self.bank_tree.configure(yscrollcommand=sb.set)
        self.bank_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.bank_tree.bind("<Double-Button-1>", lambda e: self._on_preview())

        btns = ttk.Frame(parent)
        btns.pack(fill="x", padx=6, pady=(0, 8))
        self.preview_btn = ttk.Button(btns, text="♪ 試聴", command=self._on_preview,
                                      width=12, state="disabled")
        self.preview_btn.pack(side="left")
        self.bank_total_var = tk.StringVar(value="")
        ttk.Label(btns, textvariable=self.bank_total_var,
                  foreground="#555").pack(side="left", padx=12)

    # ------------------------------------------------------- UI イベント

    def _on_master(self, _=None):
        self.master_label.configure(text=f"{self.master_var.get():.2f}")

    def _on_gain(self, _=None):
        self.gain_label.configure(text=f"{self.gain_var.get():.2f}")

    def _on_tail(self, _=None):
        self.tail_label.configure(text=f"{self.tail_var.get():.1f} 秒")

    def _choose_midi(self):
        path = filedialog.askopenfilename(
            title="MIDIファイルを選択",
            filetypes=[("MIDIファイル", "*.mid *.midi"), ("すべてのファイル", "*.*")])
        if not path:
            return
        self.midi_path = path
        self.midi_var.set(os.path.basename(path))
        self.midi_info_var.set("")
        self._log(f"選択: {path}")
        # 中身の概要だけ先に読んでおく(軽い処理なのでその場で)
        try:
            events, info = smf.parse_midi(path)
            self.midi_info_var.set(
                f"SMF format {info['format']} / {info['tracks']}トラック / "
                f"分解能 {info['division']} / MIDIイベント {len(events)}件")
        except (OSError, smf.MidiParseError) as e:
            self.midi_info_var.set(f"読み込めません: {e}")
            self._log(f"読み込みエラー: {e}")
            self.midi_path = None
            return
        self._invalidate_result()

    def _invalidate_result(self):
        """MIDIや設定が変わったので、前回の変換結果を無効にする。"""
        self.events = None
        self.audio = None
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.hw_play_btn.configure(state="disabled")

    # ------------------------------------------------------ 実機で再生

    def _refresh_ports(self):
        ports = []
        if list_ports is not None:
            ports = [p.device for p in list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _on_hw_play(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "処理中です。完了までお待ちください。")
            return
        if self.events is None:
            messagebox.showerror(APP_TITLE, "先に変換してください。")
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror(APP_TITLE, "シリアルポートを指定してください。")
            return

        self._stop_playback()   # PC側の再生と重ならないように
        self.hw_cancel.clear()
        self.progress["value"] = 0
        self._set_hw_busy(True)
        self.status_var.set("実機へ転送中...")
        self._log(f"=== 実機で再生: {port} ===")

        self.worker = threading.Thread(
            target=self._hw_worker, args=(port, self.events), daemon=True)
        self.worker.start()

    def _hw_worker(self, port, events):
        def log(msg):
            self.msg_queue.put(("log", msg))

        def progress(done, total):
            self.msg_queue.put(("progress", done, total))

        try:
            hardware.play_on_hardware(port, events, self.bank,
                                      log=log, progress=progress,
                                      cancelled=self.hw_cancel.is_set)
            self.msg_queue.put(("hw_done", None))
        except Exception as e:
            self.msg_queue.put(("hw_done", str(e)))

    def _on_hw_stop(self):
        port = self.port_var.get().strip()
        if not port:
            return
        if self.worker and self.worker.is_alive():
            # 転送中なら中断を要求する。停止処理はワーカー終了後に走る。
            self.hw_cancel.set()
            self._log("実機再生の中止を要求しました...")
            return

        def work():
            try:
                hardware.stop_hardware(port, log=lambda m: self.msg_queue.put(("log", m)))
                self.msg_queue.put(("status", "実機を停止しました"))
            except Exception as e:
                self.msg_queue.put(("log", f"実機の停止に失敗: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _set_hw_busy(self, busy):
        self.hw_play_btn.configure(state="disabled" if busy else "normal")
        self.convert_btn.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------ 音色バンク

    def _start_bank_build(self):
        self.status_var.set("音色バンクを構築中(BRRエンコード)...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.convert_btn.configure(state="disabled")

        def work():
            try:
                bank = instruments.build_bank()
                self.msg_queue.put(("bank", bank))
            except Exception as e:
                self.msg_queue.put(("bank_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_bank_ready(self, bank):
        self.bank = bank
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.convert_btn.configure(state="normal")
        self.preview_btn.configure(state="normal")
        self.status_var.set("待機中")

        total = 0
        for name, inst in bank.items():
            total += len(inst.brr_data)
            self.bank_tree.insert("", "end", values=(
                name, f"{len(inst.brr_data)} B", f"{inst.natural_hz:.1f} Hz",
                f"${inst.adsr1:02X} ${inst.adsr2:02X}",
                "あり" if inst.loop else "なし"))
        self.bank_total_var.set(
            f"合計 {total} バイト ({total / 1024:.1f} KB) — SPC700のARAMは64KBなので余裕あり")
        self._log(f"音色バンクを構築しました({len(bank)}音色 / 合計{total}バイト)。")

    def _on_preview(self):
        """選択中の音色でドミソを鳴らす。"""
        if self.bank is None or sd is None:
            if sd is None:
                messagebox.showinfo(APP_TITLE, "試聴には sounddevice が必要です。")
            return
        sel = self.bank_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "音色を選択してください。")
            return
        name = self.bank_tree.item(sel[0], "values")[0]
        inst = self.bank[name]

        # 試聴用のDSPイベントをその場で組み立てる
        events = []
        for i, note in enumerate((60, 64, 67, 72)):
            t = i * 0.45
            if inst.loop:
                hz = engine.note_to_hz(note)
            else:
                hz = inst.natural_hz  # 打楽器は素の速さで
            pitch = max(1, min(engine.PITCH_MAX,
                               int(round(engine.PITCH_UNITY * hz / inst.natural_hz))))
            events.append(engine.KeyOn(t, 0, name, pitch, 90, 90, inst.adsr1, inst.adsr2))
            events.append(engine.KeyOff(t + 0.38, 0))

        audio, _ = render.render(events, self.bank, tail=0.8)
        self._stop_playback()
        sd.play(audio, render.SAMPLE_RATE)

    # ---------------------------------------------------------- 変換

    def _on_convert(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "変換中です。完了までお待ちください。")
            return
        if self.bank is None:
            messagebox.showinfo(APP_TITLE, "音色バンクの構築が終わるまでお待ちください。")
            return
        if not self.midi_path:
            messagebox.showerror(APP_TITLE, "MIDIファイルを選択してください。")
            return

        self._stop_playback()
        self._invalidate_result()
        self.progress["value"] = 0
        self.convert_btn.configure(state="disabled")
        self.status_var.set("変換中...")
        self._log(f"=== 変換開始: {os.path.basename(self.midi_path)} ===")

        master = round(self.master_var.get(), 2)
        gain = round(self.gain_var.get(), 2)
        tail = round(self.tail_var.get(), 1)

        self.worker = threading.Thread(
            target=self._convert_worker, args=(self.midi_path, master, gain, tail),
            daemon=True)
        self.worker.start()

    def _convert_worker(self, path, master, gain, tail):
        def log(msg):
            self.msg_queue.put(("log", msg))

        try:
            log("MIDIを解析中...")
            midi_events, info = smf.parse_midi(path)
            log(f"  MIDIイベント {len(midi_events)}件")

            log("S-DSPイベント列に変換中...")
            events, stats = engine.convert(midi_events, self.bank, master_volume=master)
            log(f"  ノート {stats['notes']}個 → DSPイベント {stats['events']}件")
            if stats["stolen"]:
                log(f"  ボイス不足で打ち切った音: {stats['stolen']}個"
                    f"(S-DSPは8音までなので多重和音では発生します)")

            log("波形を合成中...")

            def progress(done, total):
                self.msg_queue.put(("progress", done, total))

            audio, peak = render.render(events, self.bank, tail=tail,
                                        master_volume=gain, progress=progress)
            log(f"  合成完了 ({len(audio) / render.SAMPLE_RATE:.1f}秒, ピーク {peak:.2f})")
            if peak > 1.0:
                log("  振り切れたので全体を正規化しました(音量倍率を下げると回避できます)")

            self.msg_queue.put(("converted", events, stats, audio, peak))
        except Exception as e:
            self.msg_queue.put(("convert_error", str(e)))

    def _on_converted(self, events, stats, audio, peak):
        self.events = events
        self.stats = stats
        self.audio = audio

        self.progress["value"] = 100
        self.convert_btn.configure(state="normal")
        self.play_btn.configure(state="normal" if sd is not None else "disabled")
        self.save_btn.configure(state="normal")
        self.hw_play_btn.configure(state="normal")
        self.status_var.set("変換完了")

        self.stat_vars["notes"].set(f"{stats['notes']} 個")
        self.stat_vars["events"].set(f"{stats['events']} 件")
        self.stat_vars["stolen"].set(f"{stats['stolen']} 個")
        self.stat_vars["duration"].set(f"{len(audio) / render.SAMPLE_RATE:.1f} 秒")
        self.stat_vars["peak"].set(f"{peak:.2f}")

        self._fill_event_tree(events)

    def _fill_event_tree(self, events, limit=3000):
        self.event_tree.delete(*self.event_tree.get_children())
        for ev in events[:limit]:
            if isinstance(ev, engine.KeyOn):
                row = (f"{ev.time:.3f}", f"V{ev.voice}", "KEYON", ev.instrument,
                       f"${ev.pitch:04X}", f"{ev.voll} / {ev.volr}",
                       f"${ev.adsr1:02X}${ev.adsr2:02X}")
            elif isinstance(ev, engine.KeyOff):
                row = (f"{ev.time:.3f}", f"V{ev.voice}", "KEYOFF", "", "", "", "")
            elif isinstance(ev, engine.SetPitch):
                row = (f"{ev.time:.3f}", f"V{ev.voice}", "PITCH", "",
                       f"${ev.pitch:04X}", "", "")
            else:
                row = (f"{ev.time:.3f}", f"V{ev.voice}", "VOL", "", "",
                       f"{ev.voll} / {ev.volr}", "")
            self.event_tree.insert("", "end", values=row)

        if len(events) > limit:
            self.event_note_var.set(
                f"全{len(events)}件のうち先頭{limit}件を表示しています。")
        else:
            self.event_note_var.set(f"全{len(events)}件。")

    # ---------------------------------------------------------- 再生

    def _on_play(self):
        if self.audio is None:
            return
        if sd is None:
            messagebox.showinfo(APP_TITLE, "再生には sounddevice が必要です。\n"
                                           "pip install sounddevice")
            return
        try:
            sd.play(self.audio, render.SAMPLE_RATE)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"再生に失敗しました:\n\n{e}")
            return

        self.play_started_at = time.monotonic()
        self.play_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("再生中")
        self.progress["value"] = 0
        self._tick_playback()

    def _tick_playback(self):
        if self.play_started_at is None or self.audio is None:
            return
        total = len(self.audio) / render.SAMPLE_RATE
        elapsed = time.monotonic() - self.play_started_at
        if elapsed >= total:
            self._stop_playback()
            self.status_var.set("再生終了")
            self.progress["value"] = 100
            return
        self.progress["value"] = elapsed / total * 100
        self.status_var.set(f"再生中  {elapsed:5.1f} / {total:.1f} 秒")
        self.play_after_id = self.root.after(100, self._tick_playback)

    def _on_stop(self):
        self._stop_playback()
        self.status_var.set("停止しました")

    def _stop_playback(self):
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass
        if self.play_after_id is not None:
            self.root.after_cancel(self.play_after_id)
            self.play_after_id = None
        self.play_started_at = None
        self.stop_btn.configure(state="disabled")
        if self.audio is not None:
            self.play_btn.configure(state="normal")

    # ---------------------------------------------------------- 保存

    def _on_save(self):
        if self.audio is None:
            return
        default = "output.wav"
        if self.midi_path:
            default = os.path.splitext(os.path.basename(self.midi_path))[0] + ".wav"
        path = filedialog.asksaveasfilename(
            title="WAVで保存", defaultextension=".wav", initialfile=default,
            filetypes=[("WAVファイル", "*.wav")])
        if not path:
            return
        try:
            pcm16 = (np.clip(self.audio, -1.0, 1.0) * 32767.0).astype("<i2")
            with wave.open(path, "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(render.SAMPLE_RATE)
                w.writeframes(pcm16.tobytes())
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"保存に失敗しました:\n\n{e}")
            return
        self._log(f"WAVを保存しました: {path}")
        self.status_var.set("保存しました")

    # ------------------------------------------------------ キュー処理

    def _pump_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    self.progress["value"] = (done / total * 100) if total else 0
                elif kind == "bank":
                    self._on_bank_ready(msg[1])
                elif kind == "bank_error":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.status_var.set("エラー")
                    self._log(f"音色バンクの構築に失敗: {msg[1]}")
                    messagebox.showerror(APP_TITLE, f"音色バンクの構築に失敗しました:\n\n{msg[1]}")
                elif kind == "converted":
                    self._on_converted(msg[1], msg[2], msg[3], msg[4])
                elif kind == "hw_done":
                    self._set_hw_busy(False)
                    if msg[1] is None:
                        self.progress["value"] = 100
                        self.status_var.set("実機での再生が完了しました")
                    else:
                        self.progress["value"] = 0
                        self.status_var.set("エラー")
                        self._log(f"実機再生エラー: {msg[1]}")
                        messagebox.showerror(APP_TITLE,
                                             f"実機での再生に失敗しました:\n\n{msg[1]}")
                elif kind == "convert_error":
                    self.progress["value"] = 0
                    self.convert_btn.configure(state="normal")
                    self.status_var.set("エラー")
                    self._log(f"エラー: {msg[1]}")
                    messagebox.showerror(APP_TITLE, f"変換に失敗しました:\n\n{msg[1]}")
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------ 終了

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(APP_TITLE, "変換中です。終了しますか?"):
                return
        self._stop_playback()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    MidiConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
