"""
SHVC-SOUND-ESP32.dsn に線幅クラスを足して Freerouting で自動配線する(ふつうのpythonで実行)。

  ・5V系は0.8mm、GND(両面ベタあり)・12V・3.3V・アンプ出力は0.6mm、音声は 0.4mm、その他の信号は 0.25mm
  ・GNDの表裏は build_pcb.py import のスティッチングビアでつなぐ
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DSN = os.path.join(HERE, "SHVC-SOUND-ESP32.dsn")
SES = os.path.join(HERE, "SHVC-SOUND-ESP32.ses")
TOOLS = os.path.join(HERE, "..", "..", "tools", "freerouting")

CLASSES = [   # (名前, 線幅um, クリアランスum, ネット)
    ("power8", 800, 250, ["+5V", "REG_5V"]),
    ("power6", 600, 250, ["GND", "+12V", "+3V3", "AMP_VP", "AMP_OUT_L", "AMP_OUT_R", "OUT_L_RC", "OUT_R_RC",
                          "JACK_L", "JACK_R"]),
    ("audio", 400, 250, ["AUDIO_L", "AUDIO_R", "AMP_IN_L", "AMP_IN_R", "LOUT_L", "LOUT_R", "LINE_L", "LINE_R"]),
]
def klass(name, width, clearance, nets):
    return (f"(class {name} " + " ".join(nets) + "\n      (circuit\n        (use_via \"Via[0-1]_600:300_um\")\n      )\n"
            f"      (rule\n        (width {width})\n        (clearance {clearance})\n      )\n    )")


text = open(DSN, encoding="utf-8").read()
m = re.search(r"\(class kicad_default(.*?)\(circuit", text, re.S)
nets = m.group(1).split()
special = {n for _, _, _, ns in CLASSES for n in ns}
rest = [n for n in nets if n not in special]
blocks = [klass("kicad_default", 250, 200, rest)]
for name, w, c, ns in CLASSES:
    present = [n for n in ns if n in nets]
    if present:
        blocks.append(klass(name, w, c, present))
end = text.index(")\n    )", text.index("(rule", m.end())) + len(")\n    )")
text = text[:m.start()] + "\n    ".join(blocks) + text[end:]

args = [a for a in sys.argv[1:] if a != "--no-layer-pref"]
open(DSN, "w", encoding="utf-8").write(text)

java = next(os.path.join(TOOLS, d, "bin", "java.exe") for d in os.listdir(TOOLS) if d.startswith("jdk"))
jar = os.path.join(TOOLS, "freerouting-2.4.1.jar")
cmd = [java, "-jar", jar, "-de", DSN, "-do", SES, "-mp", "40", "--gui.enabled=false"] + args
print(" ".join(cmd), flush=True)
sys.exit(subprocess.call(cmd))
