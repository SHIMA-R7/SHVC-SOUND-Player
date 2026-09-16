"""
ESP32版 SHVC-SOUND 基板(74.09 x 66.5mm、SHVC-SOUNDモジュールと同じ外形)を組み立てる。

  KiCad付属のpythonで実行:
    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" build_pcb.py place   … 部品配置だけ(配線なし)
    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" build_pcb.py import  … Freeroutingの結果(.ses)を取り込みGNDベタを貼る

  上面(F)  : SHVC-SOUND モジュールのコネクタ J4 だけ(モジュールはこの面に部品面を下にして載る)
  裏面(B)  : それ以外すべて(ESP32 DevKitC はソケット、DIP IC、アンプ回路、ジャック、電源入力)
  外形とJ4の位置は OpenSFC TCMK-77XR(SHVC-SOUND 互換モジュール)の基板データを裏返して求めた。
"""
import json
import math
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "SHVC-SOUND-ESP32"
PCB = os.path.join(HERE, NAME + ".kicad_pcb")
KICAD_FP = os.environ.get("KICAD10_FOOTPRINT_DIR", r"C:\Program Files\KiCad\10.0\share\kicad\footprints")

OX, OY = 100.0, 100.0          # 基板左上の座標
W, H = 74.09, 66.5
MM = pcbnew.FromMM

# (リファレンス, 面, 回転, 位置合わせに使うパッド, 上から見た位置x, y)
# 裏面の部品は左右反転するので、「そのパッドが来る場所」で指定する
PLACEMENT = [
    ("J4", "F", 180, None, 55.40, 6.59),
    ("U1", "B", 180, "1", 4.00, 39.56),          # USB側が上辺。1-15番列が x=4、16-30番列が x=29.4
    ("U3", "B", 0, "1", 20.50, 9.00),           # ESP32の下(ソケットの高さぶんの隙間)に入れる
    ("C9", "B", 0, "1", 12.00, 5.50),
    ("R7", "B", 0, "1", 21.00, 40.60),
    ("R8", "B", 0, "1", 21.00, 43.70),
    ("R9", "B", 0, "1", 21.00, 46.80),
    ("C12", "B", 0, "1", 37.50, 5.00),
    ("U7", "B", 270, "1", 10.50, 57.00),         # 12V→5V DC-DC(7805互換 SIP3)
    ("D1", "B", 0, "1", 10.62, 44.00),         # U7本体(基板内側へ倒す)の場所を空ける
    ("C13", "B", 0, "1", 4.80, 54.00),        # DC-DCの左(表から見て)、固定穴の上
    ("U2", "B", 0, "1", 43.62, 14.50),
    ("U4", "B", 0, "1", 56.12, 14.50),
    ("C8", "B", 0, "1", 38.50, 11.30),
    ("C10", "B", 0, "1", 51.00, 11.30),
    ("C11", "B", 0, "1", 67.50, 18.50),
    ("C6", "B", 0, "1", 53.50, 41.50),
    ("C7", "B", 0, "1", 53.50, 45.00),
    ("C3", "B", 0, "1", 61.50, 38.00),
    ("C4", "B", 0, "1", 71.30, 38.00),
    ("U6", "B", 0, "1", 43.62, 43.00),
    ("R6", "B", 0, "1", 72.50, 27.50),
    ("R5", "B", 0, "1", 72.50, 31.50),
    ("C5", "B", 0, "1", 62.00, 43.00),
    ("R10", "B", 0, "1", 72.50, 47.50),
    ("R1", "B", 0, "1", 55.62, 49.00),
    ("R2", "B", 0, "1", 55.62, 52.50),
    ("C1", "B", 0, "1", 49.75, 60.50),
    ("C2", "B", 0, "1", 56.75, 60.50),
    ("J1", "B", 0, None, 66.70, 59.10),        # 差し込み口が右辺から外に向く,
    ("J3", "B", 0, None, 24.00, 53.00),        # 12V入力(PDモジュール)。実物合わせで上へ8mm
]
# モジュール側の穴(TCMK-77XR の Edge.Cuts の円)を裏返した位置 (x, y, 直径)
HOLES = [(5.36, 62.06, 3.96), (10.84, 62.06, 2.98)]

# +12V はアンプの消費(数十mA)だけなので細線でよい(遠い左下のJ3から引き回すため)
POWER_NETS = ["GND", "+5V", "+3V3", "AMP_VP", "AMP_OUT_L", "AMP_OUT_R", "OUT_L_RC", "OUT_R_RC",
              "JACK_L", "JACK_R"]


def write_project():
    path = os.path.join(HERE, NAME + ".kicad_pro")
    pro = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    pro.setdefault("meta", {"filename": NAME + ".kicad_pro", "version": 3})
    base = {"clearance": 0.2, "track_width": 0.25, "via_diameter": 0.7, "via_drill": 0.35,
            "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25, "wire_width": 6, "bus_width": 12, "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
            "schematic_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647}
    pro["net_settings"] = {
        "classes": [dict(base, name="Default"),
                    dict(base, name="Power", track_width=0.6, via_diameter=0.9, via_drill=0.45, priority=0)],
        "meta": {"version": 4},
        "netclass_patterns": [{"netclass": "Power", "pattern": n} for n in POWER_NETS],
    }
    json.dump(pro, open(path, "w", encoding="utf-8"), indent=2)


def sexpr(text):
    tokens = re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tokens:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def child(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


PIN_FUNCTIONS = {}


def parse_netlist():
    root = sexpr(open(os.path.join(HERE, NAME + ".net"), encoding="utf-8").read())
    comps = {}
    for c in child(child(root, "components")[0], "comp"):
        comps[child(c, "ref")[0][1]] = (child(c, "value")[0][1], child(c, "footprint")[0][1])
    pads = {}
    for n in child(child(root, "nets")[0], "net"):
        name = child(n, "name")[0][1].lstrip("/")
        for node in child(n, "node"):
            pads[(child(node, "ref")[0][1], child(node, "pin")[0][1])] = name
            pf = child(node, "pinfunction")
            if pf:
                PIN_FUNCTIONS[(child(node, "ref")[0][1], child(node, "pin")[0][1])] = re.sub(r"_\d+$", "", pf[0][1])
    return comps, pads


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = os.path.join(HERE, lib + ".pretty") if lib == "SHVC-ESP32" else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError(f"フットプリントが見つからない: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def pad_pos(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == num:
            return p.GetPosition()
    raise KeyError(num)


def place():
    write_project()
    comps, padnets = parse_netlist()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    nets = {}
    for net in sorted(set(padnets.values())):
        ni = pcbnew.NETINFO_ITEM(board, net)
        board.Add(ni)
        nets[net] = ni

    # 外形
    pts = [(0, 0), (W, 0), (W, H), (0, H)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(MM(OX + x1), MM(OY + y1)))
        s.SetEnd(pcbnew.VECTOR2I(MM(OX + x2), MM(OY + y2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)

    placed = {r for r, *_ in PLACEMENT}
    missing = set(comps) - placed
    if missing:
        raise RuntimeError(f"配置が決まっていない部品: {sorted(missing)}")
    for ref, side, rot, anchor, x, y in PLACEMENT:
        value, fpid = comps[ref]
        fp = load_fp(fpid)
        fp.SetReference(ref)
        fp.SetValue(value)
        board.Add(fp)
        target = pcbnew.VECTOR2I(MM(OX + x), MM(OY + y))
        fp.SetPosition(target)
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(target, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if anchor:
            p = pad_pos(fp, anchor)
            fp.Move(pcbnew.VECTOR2I(target.x - p.x, target.y - p.y))
        for pad in fp.Pads():
            net = padnets.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
            pad.SetPinFunction(PIN_FUNCTIONS.get((ref, pad.GetNumber()), ""))

    # 固定穴: 基板メーカーが確実にドリル加工するよう、外形線ではなくNPTH(メッキなし穴)で開ける
    for i, (x, y, d) in enumerate(HOLES, 1):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(f"H{i}")
        fp.SetValue(f"hole {d}mm")
        fp.SetFPID(pcbnew.LIB_ID("SHVC-ESP32", f"NPTH_Hole_{d}mm"))   # 名前が空だと自動配線の結果を取り込めない
        fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        pad = pcbnew.PAD(fp)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(MM(d), MM(d)))
        pad.SetDrillSize(pcbnew.VECTOR2I(MM(d), MM(d)))
        pad.SetLayerSet(pcbnew.PAD.UnplatedHoleMask())
        pad.SetLocalClearance(MM(0.8))     # GNDベタやネジ頭から離す
        fp.Add(pad)
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(MM(OX + x), MM(OY + y)))
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        # 穴のまわりに配線・ビア禁止エリア(自動配線はパッドの個別クリアランスを知らないため)
        ka = pcbnew.ZONE(board)
        ka.SetIsRuleArea(True)
        ka.SetDoNotAllowTracks(True)
        ka.SetDoNotAllowVias(True)
        ka.SetDoNotAllowZoneFills(False)
        ka.SetDoNotAllowPads(False)
        ka.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        ka.SetLayerSet(ls)
        ol = ka.Outline()
        ol.NewOutline()
        r = d / 2 + 1.0
        for k in range(16):
            a = math.pi * 2 * k / 16
            ol.Append(MM(OX + x + r * math.cos(a)), MM(OY + y + r * math.sin(a)))
        board.Add(ka)

    # 部品番号は小さめにして重なりを減らす
    for fp in board.GetFootprints():
        f = fp.Reference()
        f.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
        f.SetTextThickness(MM(0.12))
    for text, x, y, layer, size in (("SHVC-SOUND ESP32 r0.3", 37.0, 65.0, pcbnew.B_SilkS, 0.9),):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetPosition(pcbnew.VECTOR2I(MM(OX + x), MM(OY + y)))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(0.15))
        t.SetMirrored(True)
        board.Add(t)

    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = MM(0.2)
    ds.m_ViasMinSize = MM(0.6)
    ds.m_MinThroughDrill = MM(0.3)
    ds.m_CopperEdgeClearance = MM(0.4)
    pcbnew.SaveBoard(PCB, board)
    print("配置して保存:", PCB)
    for ref in ("U1", "J4"):
        fp = board.FindFootprintByReference(ref)
        for n in ("1", "15", "16", "30") if ref == "U1" else ("1", "2", "23", "24"):
            p = pad_pos(fp, n)
            print(f"  {ref}.{n} ({pcbnew.ToMM(p.x) - OX:.2f}, {pcbnew.ToMM(p.y) - OY:.2f}) {padnets.get((ref, n), '')}")


def add_zone(board, layer, net):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    ls.AddLayer(layer)
    z.SetLayerSet(ls)
    z.SetNet(board.FindNet(net))
    ol = z.Outline()
    ol.NewOutline()
    m = 0.3
    for x, y in ((m, m), (W - m, m), (W - m, H - m), (m, H - m)):
        ol.Append(MM(OX + x), MM(OY + y))
    z.SetLocalClearance(MM(0.25))
    z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.3))
    z.SetThermalReliefSpokeWidth(MM(0.5))
    board.Add(z)
    return z


def import_ses():
    board = pcbnew.LoadBoard(PCB)
    ses = os.path.join(HERE, NAME + ".ses")
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise RuntimeError("SESの取り込みに失敗")
    # GNDは配線でもつながっているので、ベタへのサーマルは1本でも可
    board.GetDesignSettings().m_MinResolvedSpokes = 1
    for z in list(board.Zones()):
        if not z.GetIsRuleArea():
            board.Remove(z)
    zones = [add_zone(board, pcbnew.F_Cu, "GND"), add_zone(board, pcbnew.B_Cu, "GND")]
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print("配線を取り込み、GNDベタを貼って保存:", len(board.GetTracks()), "本")


if __name__ == "__main__":
    {"place": place, "import": import_ses}[sys.argv[1]]()
