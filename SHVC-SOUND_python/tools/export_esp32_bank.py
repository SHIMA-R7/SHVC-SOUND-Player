"""
midi2spc の音色バンク(BRRサンプル・ADSR・GM割り当て)と SPC700常駐ドライバを、
ESP32ファーム(esp32_ble_midi)用の C ヘッダに書き出す。

  python tools/export_esp32_bank.py   → esp32_ble_midi/bank_data.h

音色を変えたら(midi2spc/instruments.py)、これを実行してからファームをビルドし直す。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.dirname(HERE)
sys.path.insert(0, PY_DIR)
from midi2spc import hardware, instruments  # noqa: E402

OUT = os.path.join(PY_DIR, "esp32_ble_midi", "bank_data.h")


def c_bytes(name, data, per_line=16):
    lines = [f"static const uint8_t {name}[{len(data)}] = {{"]
    for i in range(0, len(data), per_line):
        lines.append("    " + ", ".join(f"0x{b:02X}" for b in data[i:i + per_line]) + ",")
    lines.append("};")
    return "\n".join(lines)


def c_u8_table(name, values, per_line=16):
    lines = [f"static const uint8_t {name}[{len(values)}] = {{"]
    for i in range(0, len(values), per_line):
        lines.append("    " + ", ".join(str(v) for v in values[i:i + per_line]) + ",")
    lines.append("};")
    return "\n".join(lines)


def main():
    bank = instruments.build_bank()
    blob, directory, srcn_map = hardware.build_sample_image(bank)
    problems = hardware.check_memory_map(len(blob), len(directory))
    if problems:
        raise SystemExit("\n".join(problems))
    names = list(bank.keys())
    index = {n: i for i, n in enumerate(names)}

    inst_rows = []
    for n in names:
        inst = bank[n]
        inst_rows.append(f'    {{"{n}", {srcn_map[n]}, 0x{inst.adsr1:02X}, 0x{inst.adsr2:02X}, '
                         f'{inst.natural_hz:.1f}f, {"true" if inst.loop else "false"}}},')

    gm = [index[instruments.GM_PROGRAM_TO_NAME[p]] for p in range(128)]
    drum = [index[instruments.DRUM_NOTE_TO_NAME[n]] for n in range(128)]

    text = f"""// 自動生成: tools/export_esp32_bank.py (midi2spc の音色バンクから)。手で編集しないこと。
#pragma once
#include <Arduino.h>

// ---- ARAMのメモリマップ(midi2spc/hardware.py と同じ) ----
static const uint16_t SPC_DRIVER_ADDR = 0x{hardware.DRIVER_ADDR:04X};
static const uint16_t SPC_DIR_ADDR = 0x{hardware.DIR_ADDR:04X};
static const uint16_t SPC_SAMPLE_ADDR = 0x{hardware.SAMPLE_ADDR:04X};

// SPC700常駐ドライバ: $F5=レジスタ番号, $F6=値 を置いて $F4 を変えると DSP へ書き、$F4 に同じ値を返す
{c_bytes("SPC_DRIVER", hardware.DRIVER_CODE)}

// サンプルディレクトリ(1音色4バイト: 開始アドレス, ループアドレス)
{c_bytes("SPC_DIR", directory)}

// BRRサンプル本体({len(blob)} バイト)
{c_bytes("SPC_BRR", blob)}

struct InstrumentDef {{
    const char *name;
    uint8_t srcn;      // サンプル番号(ディレクトリの何番目か)
    uint8_t adsr1;     // DSP $x5
    uint8_t adsr2;     // DSP $x6
    float naturalHz;   // ピッチ比1.0で鳴る周波数
    bool loop;
}};

static const uint8_t NUM_INSTRUMENTS = {len(names)};
static const InstrumentDef INSTRUMENTS[{len(names)}] = {{
{chr(10).join(inst_rows)}
}};

// GM音色番号(0-127) → INSTRUMENTS の添字
{c_u8_table("GM_PROGRAM_TO_INST", gm)}

// GMドラム(チャンネル10)のノート番号 → INSTRUMENTS の添字
{c_u8_table("DRUM_NOTE_TO_INST", drum)}

static const uint8_t TOM_INST = {index["tom"]};
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"音色 {len(names)} 種 / BRR {len(blob)} バイト / ディレクトリ {len(directory)} バイト → {OUT}")


if __name__ == "__main__":
    main()
