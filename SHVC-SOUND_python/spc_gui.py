#!/usr/bin/env python3
"""
spc_gui.py - SHVC-SOUND スタンドアロンプレイヤー GUI

好きな .spc ファイルを実機(SHVC-SOUND)で再生するためのデスクトップアプリ。
Tkinter(Python標準)製なのでブラウザもインストールも不要。

起動:
    python spc_gui.py

必要なもの:
    pip install pyserial
    Arduino側に spc_uploader.ino を書き込んでおくこと
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spc_play
import rom_tools

try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None


APP_TITLE = "SHVC-SOUND Player"
WATCH_INTERVAL_MS = 3000


class SpcPlayerApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("960x700")
        root.minsize(760, 560)

        # ワーカースレッドとの通信用
        self.msg_queue = queue.Queue()
        self.worker = None
        self.cancel_event = threading.Event()

        # プレイリスト(表示名ではなく実パスを保持する)
        self.playlist = []
        self.current_index = None

        # フォルダ監視
        self.watch_dir = None
        self.watch_seen = set()

        # 自動送り用タイマーID
        self.advance_after_id = None

        self._build_ui()
        self._refresh_ports()
        self.root.after(100, self._pump_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_play = ttk.Frame(nb)
        self.tab_rom = ttk.Frame(nb)
        nb.add(self.tab_play, text="  再生  ")
        nb.add(self.tab_rom, text="  ROM解析  ")

        self._build_play_tab(self.tab_play)
        self._build_rom_tab(self.tab_rom)

    def _build_play_tab(self, parent):
        # --- 接続設定 ---
        conn = ttk.LabelFrame(parent, text="接続")
        conn.pack(fill="x", padx=6, pady=(6, 4))

        ttk.Label(conn, text="シリアルポート:").pack(side="left", padx=(8, 4), pady=8)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var, width=28)
        self.port_combo.pack(side="left", pady=8)
        ttk.Button(conn, text="更新", command=self._refresh_ports, width=6).pack(side="left", padx=4)
        ttk.Label(conn, text="(一覧に出ない場合は COM4 のように直接入力できます)",
                  foreground="#555").pack(side="left", padx=8)

        # --- 中段: プレイリスト + 右ペイン ---
        mid = ttk.Frame(parent)
        mid.pack(fill="both", expand=True, padx=6, pady=4)

        # プレイリスト
        pl = ttk.LabelFrame(mid, text="プレイリスト")
        pl.pack(side="left", fill="both", expand=True)

        lb_frame = ttk.Frame(pl)
        lb_frame.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.listbox = tk.Listbox(lb_frame, activestyle="dotbox")
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_play())

        btns = ttk.Frame(pl)
        btns.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btns, text="ファイル追加", command=self._add_files).pack(side="left")
        ttk.Button(btns, text="フォルダ追加", command=self._add_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="削除", command=self._remove_selected).pack(side="left")
        ttk.Button(btns, text="全消去", command=self._clear_list).pack(side="left", padx=4)

        watch = ttk.Frame(pl)
        watch.pack(fill="x", padx=6, pady=(0, 6))
        self.watch_var = tk.StringVar(value="フォルダ監視: オフ")
        ttk.Button(watch, text="フォルダを監視", command=self._choose_watch_dir).pack(side="left")
        ttk.Button(watch, text="監視解除", command=self._stop_watch).pack(side="left", padx=4)
        ttk.Label(watch, textvariable=self.watch_var, foreground="#555").pack(side="left", padx=6)

        # 右ペイン
        right = ttk.Frame(mid)
        right.pack(side="left", fill="y", padx=(8, 0))

        info = ttk.LabelFrame(right, text="曲情報 (ID666タグ)")
        info.pack(fill="x")
        self.info_vars = {}
        for key, label in [("title", "タイトル"), ("game", "ゲーム"), ("artist", "作曲"),
                           ("dumper", "ダンパー"), ("seconds", "長さ(秒)")]:
            row = ttk.Frame(info)
            row.pack(fill="x", padx=8, pady=2)
            ttk.Label(row, text=f"{label}:", width=10, anchor="e").pack(side="left")
            var = tk.StringVar(value="-")
            self.info_vars[key] = var
            ttk.Label(row, textvariable=var, width=30, anchor="w").pack(side="left")
        ttk.Frame(info).pack(pady=3)

        vol = ttk.LabelFrame(right, text="音量")
        vol.pack(fill="x", pady=(8, 0))

        ttk.Label(vol, text="DSP音量倍率 (音源チップ側)").pack(anchor="w", padx=8, pady=(6, 0))
        self.dsp_vol = tk.DoubleVar(value=1.0)
        self.dsp_vol_label = ttk.Label(vol, text="1.00 倍")
        ttk.Scale(vol, from_=1.0, to=3.0, variable=self.dsp_vol, orient="horizontal",
                  command=self._on_dsp_vol).pack(fill="x", padx=8)
        self.dsp_vol_label.pack(anchor="e", padx=8)
        ttk.Label(vol, text="上げすぎるとDSP内部で歪みます",
                  foreground="#777", wraplength=260).pack(anchor="w", padx=8)

        self.use_amp = tk.BooleanVar(value=False)
        ttk.Checkbutton(vol, text="アンプ音量(PWM)を設定する", variable=self.use_amp,
                        command=self._on_amp_toggle).pack(anchor="w", padx=8, pady=(8, 0))
        self.amp_vol = tk.IntVar(value=128)
        self.amp_scale = ttk.Scale(vol, from_=0, to=255, variable=self.amp_vol,
                                   orient="horizontal", command=self._on_amp_vol)
        self.amp_scale.pack(fill="x", padx=8)
        self.amp_vol_label = ttk.Label(vol, text="128 / 255")
        self.amp_vol_label.pack(anchor="e", padx=8)
        ttk.Label(vol, text="TDA7053Aを配線している場合のみ有効",
                  foreground="#777", wraplength=260).pack(anchor="w", padx=8, pady=(0, 6))
        self._on_amp_toggle()

        opt = ttk.LabelFrame(right, text="オプション")
        opt.pack(fill="x", pady=(8, 0))
        self.auto_advance = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="曲の長さで自動的に次の曲へ",
                        variable=self.auto_advance).pack(anchor="w", padx=8, pady=6)

        # --- 操作 + 進捗 ---
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill="x", padx=6, pady=(4, 2))
        self.play_btn = ttk.Button(ctrl, text="▶ 再生", command=self._on_play, width=12)
        self.play_btn.pack(side="left")
        self.stop_btn = ttk.Button(ctrl, text="■ 停止", command=self._on_stop, width=12)
        self.stop_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(ctrl, text="転送中止", command=self._on_cancel,
                                     width=12, state="disabled")
        self.cancel_btn.pack(side="left")

        self.status_var = tk.StringVar(value="待機中")
        ttk.Label(ctrl, textvariable=self.status_var).pack(side="left", padx=12)

        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=6, pady=2)

        logf = ttk.LabelFrame(parent, text="ログ")
        logf.pack(fill="both", expand=True, padx=6, pady=(4, 6))
        self.log_text = scrolledtext.ScrolledText(logf, height=9, wrap="word",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text.configure(state="disabled")

    def _build_rom_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Button(top, text="ROMファイルを選択...", command=self._choose_rom).pack(side="left")
        self.rom_path_var = tk.StringVar(value="(未選択)")
        ttk.Label(top, textvariable=self.rom_path_var, foreground="#555").pack(side="left", padx=8)

        res = ttk.LabelFrame(parent, text="解析結果")
        res.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.rom_text = scrolledtext.ScrolledText(res, height=12, wrap="word",
                                                  font=("Consolas", 9))
        self.rom_text.pack(fill="both", expand=True, padx=4, pady=4)

        note = ttk.LabelFrame(parent, text="ROMから .spc を取り出したい場合")
        note.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        note_text = scrolledtext.ScrolledText(note, height=14, wrap="word")
        note_text.pack(fill="both", expand=True, padx=4, pady=4)
        note_text.insert("1.0", rom_tools.extraction_note())
        note_text.configure(state="disabled")

    # ------------------------------------------------------- UI イベント

    def _on_dsp_vol(self, _=None):
        self.dsp_vol_label.configure(text=f"{self.dsp_vol.get():.2f} 倍")

    def _on_amp_vol(self, _=None):
        self.amp_vol_label.configure(text=f"{int(self.amp_vol.get())} / 255")

    def _on_amp_toggle(self):
        state = "normal" if self.use_amp.get() else "disabled"
        self.amp_scale.configure(state=state)

    def _refresh_ports(self):
        ports = []
        if list_ports is not None:
            ports = [p.device for p in list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="SPCファイルを選択",
            filetypes=[("SPCファイル", "*.spc"), ("すべてのファイル", "*.*")])
        self._add_paths(paths)

    def _add_folder(self):
        d = filedialog.askdirectory(title="SPCファイルのあるフォルダを選択")
        if not d:
            return
        found = [os.path.join(d, n) for n in sorted(os.listdir(d))
                 if n.lower().endswith(".spc")]
        if not found:
            messagebox.showinfo(APP_TITLE, "そのフォルダに .spc ファイルが見つかりませんでした。")
            return
        self._add_paths(found)

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            if p not in self.playlist:
                self.playlist.append(p)
                self.listbox.insert("end", os.path.basename(p))
                added += 1
        if added:
            self._log(f"{added}件をプレイリストに追加しました。")

    def _remove_selected(self):
        sel = list(self.listbox.curselection())
        for i in reversed(sel):
            self.listbox.delete(i)
            del self.playlist[i]

    def _clear_list(self):
        self.listbox.delete(0, "end")
        self.playlist.clear()
        self._clear_info()

    def _on_select(self, _=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._show_info(self.playlist[sel[0]])

    def _clear_info(self):
        for var in self.info_vars.values():
            var.set("-")

    def _show_info(self, path):
        try:
            spc = spc_play.SpcFile(path)
        except Exception as e:
            self._clear_info()
            self._log(f"読み込めません: {os.path.basename(path)} ({e})")
            return
        tags = spc.tags or {}
        for key, var in self.info_vars.items():
            var.set(tags.get(key) or "-")

    # ------------------------------------------------------ フォルダ監視

    def _choose_watch_dir(self):
        d = filedialog.askdirectory(title="監視するフォルダを選択(エミュレータのSPC出力先など)")
        if not d:
            return
        self.watch_dir = d
        # 監視開始時点にあるファイルは「既知」にして、以後の新規分だけ拾う
        self.watch_seen = {n for n in os.listdir(d) if n.lower().endswith(".spc")}
        self.watch_var.set(f"監視中: {os.path.basename(d) or d}")
        self._log(f"フォルダ監視を開始: {d}")
        self._poll_watch()

    def _stop_watch(self):
        if self.watch_dir:
            self._log("フォルダ監視を解除しました。")
        self.watch_dir = None
        self.watch_var.set("フォルダ監視: オフ")

    def _poll_watch(self):
        if not self.watch_dir:
            return
        try:
            names = {n for n in os.listdir(self.watch_dir) if n.lower().endswith(".spc")}
            new = sorted(names - self.watch_seen)
            if new:
                self.watch_seen = names
                self._add_paths([os.path.join(self.watch_dir, n) for n in new])
                self._log(f"新しいSPCを検出: {', '.join(new)}")
        except OSError as e:
            self._log(f"監視エラー: {e}")
            self.watch_dir = None
            self.watch_var.set("フォルダ監視: オフ")
            return
        self.root.after(WATCH_INTERVAL_MS, self._poll_watch)

    # ---------------------------------------------------------- 再生制御

    def _selected_path(self):
        sel = self.listbox.curselection()
        if sel:
            return sel[0], self.playlist[sel[0]]
        if self.playlist:
            return 0, self.playlist[0]
        return None, None

    def _on_play(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "転送中です。完了までお待ちください。")
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror(APP_TITLE, "シリアルポートを指定してください。")
            return
        idx, path = self._selected_path()
        if not path:
            messagebox.showerror(APP_TITLE, "プレイリストに .spc ファイルを追加してください。")
            return

        self._cancel_advance()
        self.current_index = idx
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self._show_info(path)

        amp = int(self.amp_vol.get()) if self.use_amp.get() else None
        factor = round(self.dsp_vol.get(), 2)

        self.cancel_event.clear()
        self.progress["value"] = 0
        self._set_busy(True)
        self.status_var.set(f"転送中: {os.path.basename(path)}")
        self._log(f"=== 再生開始: {os.path.basename(path)} ===")

        self.worker = threading.Thread(
            target=self._play_worker, args=(port, path, factor, amp), daemon=True)
        self.worker.start()

    def _play_worker(self, port, path, factor, amp):
        def log(msg):
            self.msg_queue.put(("log", msg))

        def progress(done, total):
            self.msg_queue.put(("progress", done, total))

        try:
            spc_play.play(port, path, volume_factor=factor, amp_volume=amp,
                          log=log, progress=progress,
                          cancelled=self.cancel_event.is_set)
            self.msg_queue.put(("done", None))
        except spc_play.TransferCancelled:
            self.msg_queue.put(("done", "cancelled"))
        except Exception as e:
            self.msg_queue.put(("done", str(e)))

    def _on_stop(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "転送中です。先に「転送中止」を押してください。")
            return
        port = self.port_var.get().strip()
        if not port:
            return
        self._cancel_advance()

        def work():
            try:
                spc_play.stop(port, log=lambda m: self.msg_queue.put(("log", m)))
                self.msg_queue.put(("status", "停止しました"))
            except Exception as e:
                self.msg_queue.put(("log", f"停止に失敗: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _on_cancel(self):
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self._log("転送の中止を要求しました...")

    def _set_busy(self, busy):
        self.play_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    # ------------------------------------------------------- 自動送り

    def _schedule_advance(self):
        if not self.auto_advance.get() or self.current_index is None:
            return
        path = self.playlist[self.current_index]
        seconds = 120
        try:
            tags = spc_play.SpcFile(path).tags or {}
            if tags.get("seconds", "").isdigit():
                seconds = max(5, int(tags["seconds"]))
        except Exception:
            pass
        self._log(f"{seconds}秒後に次の曲へ進みます。")
        self.advance_after_id = self.root.after(seconds * 1000, self._advance)

    def _cancel_advance(self):
        if self.advance_after_id is not None:
            self.root.after_cancel(self.advance_after_id)
            self.advance_after_id = None

    def _advance(self):
        self.advance_after_id = None
        if not self.playlist or self.current_index is None:
            return
        nxt = (self.current_index + 1) % len(self.playlist)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(nxt)
        self._on_play()

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
                elif kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "done":
                    self._on_worker_done(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def _on_worker_done(self, error):
        self._set_busy(False)
        if error is None:
            self.progress["value"] = 100
            self.status_var.set("再生中")
            self._schedule_advance()
        elif error == "cancelled":
            self.progress["value"] = 0
            self.status_var.set("転送を中止しました")
            self._log("転送を中止しました。")
        else:
            self.progress["value"] = 0
            self.status_var.set("エラー")
            self._log(f"エラー: {error}")
            messagebox.showerror(APP_TITLE, f"再生に失敗しました:\n\n{error}")

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ---------------------------------------------------------- ROM解析

    def _choose_rom(self):
        path = filedialog.askopenfilename(
            title="スーファミROMを選択",
            filetypes=[("SNES ROM", "*.sfc *.smc *.fig *.swc"), ("すべてのファイル", "*.*")])
        if not path:
            return
        self.rom_path_var.set(path)
        self.rom_text.delete("1.0", "end")
        try:
            report = rom_tools.format_report(rom_tools.analyze(path))
        except Exception as e:
            report = f"解析に失敗しました: {e}\n"
        self.rom_text.insert("1.0", report)

    # ------------------------------------------------------------ 終了

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(APP_TITLE, "転送中です。終了しますか?"):
                return
            self.cancel_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    SpcPlayerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
