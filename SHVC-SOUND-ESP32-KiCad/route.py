"""SHVC-SOUND-ESP32.dsn に電源系の太線クラスを足して Freerouting で自動配線する(ふつうのpythonで実行)。"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DSN = os.path.join(HERE, "SHVC-SOUND-ESP32.dsn")
SES = os.path.join(HERE, "SHVC-SOUND-ESP32.ses")
TOOLS = os.path.join(HERE, "..", "..", "tools", "freerouting")
POWER = ["GND", "+5V", "+3V3", "AMP_VP", "AMP_OUT_L", "AMP_OUT_R", "OUT_L_RC", "OUT_R_RC", "JACK_L", "JACK_R"]

text = open(DSN, encoding="utf-8").read()
m = re.search(r"\(class kicad_default(.*?)\(circuit", text, re.S)
nets = m.group(1).split()
rest = [n for n in nets if n not in POWER]
cls = ("(class kicad_default " + " ".join(rest) + "\n      (circuit\n        (use_via \"Via[0-1]_600:300_um\")\n      )\n"
       "      (rule\n        (width 250)\n        (clearance 200)\n      )\n    )\n"
       "    (class power " + " ".join(POWER) + "\n      (circuit\n        (use_via \"Via[0-1]_600:300_um\")\n      )\n"
       "      (rule\n        (width 600)\n        (clearance 250)\n      )\n    )")
start = m.start()
end = text.index(")\n    )", text.index("(rule", m.end())) + len(")\n    )")
text = text[:start] + cls + text[end:]
open(DSN, "w", encoding="utf-8").write(text)

java = next(os.path.join(TOOLS, d, "bin", "java.exe") for d in os.listdir(TOOLS) if d.startswith("jdk"))
jar = os.path.join(TOOLS, "freerouting-2.4.1.jar")
cmd = [java, "-jar", jar, "-de", DSN, "-do", SES, "-mp", "40", "--gui.enabled=false"] + sys.argv[1:]
print(" ".join(cmd), flush=True)
sys.exit(subprocess.call(cmd))
