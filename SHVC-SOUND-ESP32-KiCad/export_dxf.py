"""
レーザーカッター用DXF(基板単品)を書き出す。KiCad付属のpythonで実行。
  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" export_dxf.py 出力.dxf

  ・単位mm、原寸。表面(SHVC-SOUNDが載る面)から見た向き。左下が(0,0)
  ・レイヤー HOLES  : 全部の穴(丸穴は円、長穴は輪郭線)。先に切る
  ・レイヤー OUTLINE: 基板外形。最後に切る
  ・DXF R12(ASCII)。どのレーザーソフトでも読める形式
"""
import math
import sys

import pcbnew

OX, OY, W, H = 100.0, 100.0, 74.09, 66.5
board = pcbnew.LoadBoard("SHVC-SOUND-ESP32.kicad_pcb")
T = pcbnew.ToMM
out = []


def xy(x, y):
    """基板座標(mm, Y下向き) → DXF座標(Y上向き、左下原点)"""
    return x - OX, H - (y - OY)


def line(layer, p, q):
    out.extend(["0", "LINE", "8", layer, "10", f"{p[0]:.4f}", "20", f"{p[1]:.4f}", "30", "0.0",
                "11", f"{q[0]:.4f}", "21", f"{q[1]:.4f}", "31", "0.0"])


def circle(layer, c, r):
    out.extend(["0", "CIRCLE", "8", layer, "10", f"{c[0]:.4f}", "20", f"{c[1]:.4f}", "30", "0.0", "40", f"{r:.4f}"])


holes = 0
for fp in board.GetFootprints():
    for pad in fp.Pads():
        dx, dy = T(pad.GetDrillSizeX()), T(pad.GetDrillSizeY())
        if dx <= 0:
            continue
        pos = pad.GetPosition()
        cx, cy = T(pos.x), T(pos.y)
        if abs(dx - dy) < 1e-6:
            circle("HOLES", xy(cx, cy), dx / 2)
        else:
            # 長穴: 長手方向の両端に半円、その間を直線でつないだ輪郭(折れ線で近似)
            ang = math.radians(-pad.GetOrientationDegrees())
            r = min(dx, dy) / 2
            half = (max(dx, dy) - min(dx, dy)) / 2
            base = 0.0 if dx > dy else math.pi / 2
            ux, uy = math.cos(base + ang), math.sin(base + ang)
            pts = []
            th = math.atan2(uy, ux)
            for end, a0 in ((1, th - math.pi / 2), (-1, th + math.pi / 2)):
                ex, ey = cx + ux * half * end, cy + uy * half * end
                for k in range(17):
                    a = a0 + math.pi * k / 16
                    pts.append(xy(ex + r * math.cos(a), ey + r * math.sin(a)))
            for p, q in zip(pts, pts[1:] + pts[:1]):
                line("HOLES", p, q)
        holes += 1

for d in board.GetDrawings():
    if d.GetLayerName() != "Edge.Cuts":
        continue
    if d.GetShapeStr() == "Circle":
        c = d.GetCenter()
        circle("OUTLINE", xy(T(c.x), T(c.y)), T(d.GetRadius()))
    else:
        line("OUTLINE", xy(T(d.GetStart().x), T(d.GetStart().y)), xy(T(d.GetEnd().x), T(d.GetEnd().y)))

dxf = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "9", "$MEASUREMENT", "70", "1", "0", "ENDSEC",
       "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "2",
       "0", "LAYER", "2", "HOLES", "70", "0", "62", "1", "6", "CONTINUOUS",
       "0", "LAYER", "2", "OUTLINE", "70", "0", "62", "5", "6", "CONTINUOUS",
       "0", "ENDTAB", "0", "ENDSEC",
       "0", "SECTION", "2", "ENTITIES"] + out + ["0", "ENDSEC", "0", "EOF"]
with open(sys.argv[1], "w", encoding="ascii", newline="\r\n") as f:
    f.write("\n".join(dxf) + "\n")
print(f"穴 {holes} 個 → {sys.argv[1]}")
