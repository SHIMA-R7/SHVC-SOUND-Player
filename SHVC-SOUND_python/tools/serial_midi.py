"""
ESP32(esp32_ble_midi)に、USBシリアル経由で生のMIDIバイトを流してテストする。
BLE鍵盤が無くても、発音ロジックや実機の鳴り方を確かめられる。
ESP32 側の表示(ドライラン時のDSP書き込みログなど)もそのまま画面に出す。

  python tools/serial_midi.py --port COM5 demo            … 音階と和音、ピッチベンド、ドラムを少し鳴らす
  python tools/serial_midi.py --port COM5 file 曲.mid     … MIDIファイルをタイミングどおりに流す
  python tools/serial_midi.py --port COM5 log             … ESP32の表示を見るだけ(BLEで弾きながら確認)
"""
import argparse
import os
import sys
import threading
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from midi2spc import smf  # noqa: E402


def open_port(name):
    ser = serial.Serial()
    ser.port = name
    ser.baudrate = 115200
    ser.timeout = 0.1
    ser.dtr = False      # 開いたときにESP32がリセットされにくいようにする(基板によってはそれでもリセットされる)
    ser.rts = False
    ser.open()
    return ser


def reader(ser, stop):
    buf = b""
    while not stop.is_set():
        data = ser.read(256)
        if not data:
            continue
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            print("  [ESP32] " + line.decode("utf-8", "replace").rstrip(), flush=True)


def wait_ready(ser, timeout):
    """起動メッセージ("BLE:" の行)が出るまで待つ。開いた拍子にリセットされなかった場合はそのまま進む。"""
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        data = ser.read(256)
        if data:
            buf += data
            text = buf.decode("utf-8", "replace")
            for line in text.splitlines():
                print("  [ESP32] " + line, flush=True)
            buf = b""
            if "BLE:" in text:
                return True
    return False


def send(ser, *msg):
    ser.write(bytes(msg))


def demo(ser):
    note_len = 0.25
    send(ser, 0xC0, 0)                         # ピアノ
    for n in (60, 62, 64, 65, 67, 69, 71, 72):
        send(ser, 0x90, n, 100)
        time.sleep(note_len)
        send(ser, 0x80, n, 0)
    time.sleep(0.3)
    send(ser, 0xC0, 48)                        # パッドで和音
    for n in (60, 64, 67, 71):
        send(ser, 0x90, n, 90)
    time.sleep(1.2)
    for v in list(range(8192, 16383, 512)) + list(range(16383, 8191, -512)):   # ピッチベンド
        send(ser, 0xE0, v & 0x7F, v >> 7)
        time.sleep(0.03)
    for n in (60, 64, 67, 71):
        send(ser, 0x80, n, 0)
    time.sleep(0.3)
    for n in (36, 42, 38, 42, 36, 36, 38, 46):  # ドラム(チャンネル10)
        send(ser, 0x99, n, 110)
        time.sleep(0.2)
    send(ser, 0xB0, 123, 0)


def play_file(ser, path):
    events = smf.parse_midi(path)
    start = time.perf_counter()
    for ev in events:
        wait = start + ev.time - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        ch = ev.channel & 0x0F
        if isinstance(ev, smf.NoteOn):
            send(ser, 0x90 | ch, ev.note, ev.velocity)
        elif isinstance(ev, smf.NoteOff):
            send(ser, 0x80 | ch, ev.note, 0)
        elif isinstance(ev, smf.ControlChange):
            send(ser, 0xB0 | ch, ev.controller & 0x7F, ev.value & 0x7F)
        elif isinstance(ev, smf.ProgramChange):
            send(ser, 0xC0 | ch, ev.program & 0x7F)
        elif isinstance(ev, smf.PitchBend):
            v = ev.value + 8192
            send(ser, 0xE0 | ch, v & 0x7F, (v >> 7) & 0x7F)
    for ch in range(16):
        send(ser, 0xB0 | ch, 123, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--wait", type=float, default=15.0, help="ESP32の起動を待つ最大秒数")
    ap.add_argument("--quiet", action="store_true", help="ESP32の発音ログを止める(チャンネル16 CC119=0)")
    ap.add_argument("mode", choices=["demo", "file", "log"])
    ap.add_argument("path", nargs="?")
    args = ap.parse_args()

    ser = open_port(args.port)
    wait_ready(ser, args.wait)
    stop = threading.Event()
    t = threading.Thread(target=reader, args=(ser, stop), daemon=True)
    t.start()
    if args.quiet:
        send(ser, 0xBF, 119, 0)
    try:
        if args.mode == "demo":
            demo(ser)
        elif args.mode == "file":
            if not args.path:
                raise SystemExit("MIDIファイルを指定してください")
            play_file(ser, args.path)
        else:
            print("表示を見ています。Ctrl+C で終わります")
            while True:
                time.sleep(1)
        time.sleep(1.0)
    except KeyboardInterrupt:
        for ch in range(16):
            send(ser, 0xB0 | ch, 123, 0)
    finally:
        stop.set()
        t.join(timeout=1)
        ser.close()


if __name__ == "__main__":
    main()
