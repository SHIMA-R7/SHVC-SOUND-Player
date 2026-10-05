"""Generate the rev0.4 parts list from the BOM after checking PCB references."""
import csv
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT.parent / "SHVC-SOUND-ESP32-BOM.csv"
PCB = PROJECT / "SHVC-SOUND-ESP32-KiCad/SHVC-SOUND-ESP32.kicad_pcb"
OUTPUT = Path(__file__).with_name("SHVC-SOUND-ESP32-r0.4-parts.md")

def parse_sexpr(text):
    stack = []
    root = None
    for token in re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text):
        if token == "(":
            item = []
            if stack:
                stack[-1].append(item)
            else:
                root = item
            stack.append(item)
        elif token == ")":
            stack.pop()
        else:
            stack[-1].append(token[1:-1] if token.startswith('"') else token)
    return root

pcb_text = PCB.read_text(encoding="utf-8")
assert "rev0.4" in pcb_text or "ESP32 r0.4" in pcb_text, "Wrong PCB revision"
components = {}
for item in parse_sexpr(pcb_text):
    if isinstance(item, list) and item and item[0] == "footprint":
        props = {p[1]: p[2] for p in item if isinstance(p, list) and p and p[0] == "property"}
        if "Reference" in props:
            components[props["Reference"]] = props.get("Value", "")
rows = list(csv.DictReader(SOURCE.open(encoding="utf-8-sig", newline="")))
covered = set()
for row in rows:
    refs = re.findall(r"(?:R|C|U|J|D|H)\d+", row["部品番号"])
    for ref in refs:
        assert ref in components, f"BOM reference missing on PCB: {ref}"
    covered.update(refs)
    if row["区分"] in ("抵抗", "コンデンサ", "IC", "電源") and refs:
        print(row["部品番号"], row["品名・値"], "PCB:", ", ".join(f"{r}={components[r]}" for r in refs))
missing = set(components) - covered
assert not missing, f"PCB references missing from BOM: {sorted(missing)}"

def table(headers, entries):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + ["| " + " | ".join(cell(v) for v in row) + " |" for row in entries])

parts = ["# SHVC-SOUND-ESP32 rev0.4 部品表", "",
         "対象：ESP32版 rev0.4（74.09 × 66.5mm）。2026-10-02時点。現行BOMから自動生成し、PCBの部品番号を照合。**実機動作は未検証**。", "",
         "Arduino Nano版の部品表ではありません。SHVC-SOUND音源モジュール本体、12V対応USB-PD電源・ケーブルは別途用意してください。", ""]
groups = [("1. IC・モジュール・電源", {"IC", "モジュール", "電源"}),
          ("2. 抵抗", {"抵抗"}), ("3. コンデンサ", {"コンデンサ"}),
          ("4. コネクタ・ソケット・基板", {"コネクタ", "基板"}),
          ("5. 任意のソケット・固定部品", {"機構部品(任意)"})]
for title, categories in groups:
    selected = [r for r in rows if r["区分"] in categories]
    parts += ["## " + title, "", table(["部品番号", "数量", "品名・値", "仕様・取り付け上の注意"],
        [(r["部品番号"], r["数量"], r["品名・値"], r["仕様・形状"] + ("。" + r["備考"] if r["備考"] else "")) for r in selected]), ""]
parts += ["## 6. 今回の代替部品と取り付けの注意", "",
          "以下は標準BOMとは別の代替メモです。標準の指定値は上の表に残しています。", "",
          table(["対象", "今回の扱い"], [
              ("R7・R8・R9", "3kΩへの代替可。3.3Vへのプルアップで、LOW時は約1.1mA。10kΩと混在しても可。R6の音量分圧抵抗とは区別する。"),
              ("D1", "標準は1N5819。1N4002は逆流防止として働くが電圧降下が増えるため、代替動作は未検証。採用する場合はUSBを外して基板電源だけで、D1通過後の電圧を確認する。"),
              ("U3", "ESP32の下に入るためICソケットを使わず直付け。"),
              ("R11～R15・C14/C15", "rev0.4に含まれる部品。R11～R15は立て付け。R11/R12はESP32の下なので高さ10mm以下。C14/C15は無極性。"),
              ("J1", "ジャックの端子対応は未検証。使用する現物で導通を確認し、一致しない場合は配線を現物に合わせる。")]), "",
          "## 7. 確認状況・元データ", "",
          table(["項目", "確認状況"], [("基板版数", "PCB内のrev0.4表記を確認"),
              ("部品番号", f"PCBの全{len(components)}個の部品番号がBOMに含まれることを照合"),
              ("部品の値・仕様", "現行BOMから自動転記。抵抗・コンデンサ・IC・電源のPCB値を生成時に出力し照合"),
              ("実機動作・代替ダイオード", "未検証。組み立て後に電源電圧・通信・発音を順番に確認")]), "",
          "- 元BOM：`SHVC-SOUND-ESP32-BOM.csv`（SHVC-SOUND直下）",
          "- 基板：`SHVC-SOUND-Player/SHVC-SOUND-ESP32-KiCad/SHVC-SOUND-ESP32.kicad_pcb`",
          "- この部品表：`SHVC-SOUND-Player/docs/SHVC-SOUND-ESP32-r0.4-parts.md`",
          "- 生成スクリプト：`SHVC-SOUND-Player/docs/build_rev04_parts.py`", ""]
OUTPUT.write_text("\n".join(parts), encoding="utf-8")
print("Wrote", OUTPUT)
