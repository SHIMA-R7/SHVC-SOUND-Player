"""
ESP32版 SHVC-SOUND プレーヤーの回路図(KiCad 10形式)を生成する。

  U1 ESP32 DevKit V1(DOIT互換 30ピン)
  U2 74HCT541N  データ線 書き込み方向(3.3V→5V)
  U3 74HCT541N  制御線 A0/A1//WR//RD//RESET(3.3V→5V)
  U4 74LVC245N  データ線 読み出し方向(5V→3.3V)
  J4 SHVC-SOUND 24ピン
  U6 TDA7053A   ステレオアンプ(周辺回路は既存のArduino版回路図から流用。音量分圧だけ3.3V用に変更)

配線は各ピンにネット名のラベルを置く方式(同じ名前のラベル同士がつながる)。
実行: python gen_schematic.py → SHVC-SOUND-ESP32.kicad_sch
"""
import uuid

LIB = "SHVC-ESP32"
G = 2.54


def uid():
    return str(uuid.uuid4())


def fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


FONT = "(effects (font (size 1.27 1.27)))"
FONT_HIDE = "(effects (font (size 1.27 1.27)) (hide yes))"

# ---- シンボル定義 -------------------------------------------------------------
# 各シンボルは (名前, 本体の幅(グリッド数), 左ピン[(番号,名前,種類)], 右ピン[...])
# 左ピンは上から、右ピンも上から並べる。None は空き行。


def ic(left, right, width=8):
    return {"left": left, "right": right, "width": width}


# ESP32 DevKit V1 (DOIT互換, 30ピン)。アンテナを上・USBを下にして部品面から見た並び
_L = ["EN", "IO36", "IO39", "IO34", "IO35", "IO32", "IO33", "IO25", "IO26", "IO27", "IO14", "IO12", "IO13", "GND", "VIN"]
_R = ["IO23", "IO22", "TX0/IO1", "RX0/IO3", "IO21", "IO19", "IO18", "IO5", "TX2/IO17", "RX2/IO16", "IO4", "IO2", "IO15",
      "GND", "3V3"]


def _esp_type(name):
    if name in ("GND", "VIN"):
        return "power_in"
    if name == "3V3":
        return "power_out"
    return "input" if name in ("EN", "IO36", "IO39", "IO34", "IO35") else "bidirectional"


ESP32_LEFT = [(str(i + 1), n, _esp_type(n)) for i, n in enumerate(_L)]
ESP32_RIGHT = [(str(i + 16), n, _esp_type(n)) for i, n in enumerate(_R)]


def esp_pin(name):
    """GPIO名(IO13 など)からピン番号を引く。TX2/IO17 のような別名付きも IO17 で引ける。"""
    for num, pname, _ in ESP32_LEFT + ESP32_RIGHT:
        if pname == name or pname.split("/")[-1] == name:
            return num
    raise KeyError(name)


HCT541_LEFT = [("1", "~{OE1}", "input"), ("19", "~{OE2}", "input"), None] + \
    [(str(n), f"A{n - 1}", "input") for n in range(2, 10)] + [None, ("20", "VCC", "power_in"), ("10", "GND", "power_in")]
HCT541_RIGHT = [None, None, None] + [(str(19 - k), f"Y{k}", "tri_state") for k in range(1, 9)]

LVC245_LEFT = [("1", "DIR", "input"), ("19", "~{OE}", "input"), None] + \
    [(str(n), f"A{n - 1}", "bidirectional") for n in range(2, 10)] + [None, ("20", "VCC", "power_in"), ("10", "GND", "power_in")]
LVC245_RIGHT = [None, None, None] + [(str(19 - k), f"B{k}", "bidirectional") for k in range(1, 9)]

SHVC_NAMES = {1: "GND", 2: "VCC", 3: "A0", 4: "A1", 5: "~{WR}", 6: "~{RD}", 7: "D0", 8: "D1", 9: "D2", 10: "D3",
              11: "D4", 12: "D5", 13: "D6", 14: "D7", 15: "~{RESET}", 16: "NC", 17: "NC", 18: "VCC", 19: "GND",
              20: "~{MUTE}", 21: "AUDIO_L", 22: "AUDIO_R", 23: "GND", 24: "VCC"}
SHVC_LEFT = [(str(n), SHVC_NAMES[n], "passive") for n in range(1, 13)]
SHVC_RIGHT = [(str(n), SHVC_NAMES[n], "passive") for n in range(13, 25)]

# TDA7053A のピン名は既存回路図の接続から機能を推定したもの(データシートで要確認)
TDA_LEFT = [("1", "P1", "passive"), ("2", "VC_A", "passive"), ("3", "P3", "passive"), ("4", "IN_A", "passive"),
            ("5", "VP", "passive"), ("6", "IN_B", "passive"), ("7", "GND", "power_in"), ("8", "VC_B", "passive")]
TDA_RIGHT = [("16", "OUT_B", "passive"), ("15", "P15", "passive"), ("14", "GND", "power_in"),
             ("13", "GND", "power_in"), ("12", "GND", "power_in"), ("11", "P11", "passive"),
             ("10", "GND", "power_in"), ("9", "OUT_A", "passive")]

SYMBOLS = {
    "ESP32_DevKit_30": ("U", ic(ESP32_LEFT, ESP32_RIGHT, 12)),
    "74HCT541": ("U", ic(HCT541_LEFT, HCT541_RIGHT, 8)),
    "74LVC245": ("U", ic(LVC245_LEFT, LVC245_RIGHT, 8)),
    "SHVC-SOUND": ("J", ic(SHVC_LEFT, SHVC_RIGHT, 10)),
    "TDA7053A": ("U", ic(TDA_LEFT, TDA_RIGHT, 8)),
    # PJ-324M: 1=スリーブ(GND)、2=接点+3=そのスイッチ、4=接点+5=そのスイッチ(4が奥側=チップ(L)、2=リング(R)と推定)
    "PJ-324M": ("J", ic([("1", "SLEEVE", "passive"), ("4", "TIP", "passive"), ("5", "TIP_SW", "passive"),
                         ("2", "RING", "passive"), ("3", "RING_SW", "passive")], [], 6)),
    "Conn_2": ("J", ic([("1", "1", "passive"), ("2", "2", "passive")], [], 4)),
    # 電源入力コネクタ(ERCで「電源の供給元」として扱わせるため power_out)
    "PowerIn_2": ("J", ic([("1", "V+", "power_out"), ("2", "GND", "power_out")], [], 4)),
    "PowerIn_2B": ("J", ic([("1", "V+", "power_out"), ("2", "GND", "passive")], [], 4)),
    # MINMAX M78AR05-0.5: 7805互換ピン配置のDC-DCコンバータ(12V→5V 0.5A、発熱ほぼなし)
    "M78AR05-0.5": ("U", ic([("1", "+VIN", "power_in"), ("2", "GND", "power_in")], [("3", "VOUT", "power_out")], 8)),
}


def ic_geometry(spec):
    rows = max(len(spec["left"]), len(spec["right"]))
    w = spec["width"] * G / 2
    top = (rows - 1) * G / 2
    pins = []   # (num, name, type, x, y, angle)
    for i, p in enumerate(spec["left"]):
        if p:
            pins.append((*p, -w - G, top - i * G, 0))
    for i, p in enumerate(spec["right"]):
        if p:
            pins.append((*p, w + G, top - i * G, 180))
    return pins, w, top + G, -(top + G)


def lib_symbol_ic(name, ref, spec):
    pins, w, ytop, ybot = ic_geometry(spec)
    out = [f'(symbol "{LIB}:{name}" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)',
           f'(property "Reference" "{ref}" (at 0 {fmt(ytop + 1.27)} 0) {FONT})',
           f'(property "Value" "{name}" (at 0 {fmt(ybot - 1.27)} 0) {FONT})',
           f'(property "Footprint" "" (at 0 0 0) {FONT_HIDE})',
           f'(property "Datasheet" "" (at 0 0 0) {FONT_HIDE})',
           f'(symbol "{name}_0_1" (rectangle (start {fmt(-w)} {fmt(ytop)}) (end {fmt(w)} {fmt(ybot)}) '
           f'(stroke (width 0.254) (type default)) (fill (type background))))',
           f'(symbol "{name}_1_1"']
    for num, pname, ptype, x, y, ang in pins:
        out.append(f'(pin {ptype} line (at {fmt(x)} {fmt(y)} {ang}) (length {G}) '
                   f'(name "{pname}" {FONT}) (number "{num}" {FONT}))')
    out.append("))")
    return "\n".join(out), pins


def lib_symbol_2pin(name, ref, kind, types=("passive", "passive")):
    body = {"R": '(rectangle (start -1.016 2.286) (end 1.016 -2.286) (stroke (width 0.254) (type default)) (fill (type none)))',
            "C": '(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) (type default)) (fill (type none)))'
                 ' (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) (stroke (width 0.508) (type default)) (fill (type none)))',
            "L": '(rectangle (start -1.016 2.286) (end 1.016 -2.286) (stroke (width 0.254) (type default)) (fill (type outline)))',
            # ダイオード: 1番=カソード(上)、2番=アノード(下)
            "D": '(polyline (pts (xy -1.27 1.016) (xy 1.27 1.016)) (stroke (width 0.254) (type default)) (fill (type none)))'
                 ' (polyline (pts (xy 0 1.016) (xy -1.27 -1.016) (xy 1.27 -1.016) (xy 0 1.016)) (stroke (width 0.254) (type default)) (fill (type none)))'}[kind]
    pins = [("1", "K", types[0], 0, 3.81, 270), ("2", "A", types[1], 0, -3.81, 90)]
    out = [f'(symbol "{LIB}:{name}" (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes)) (exclude_from_sim no) (in_bom yes) (on_board yes)',
           f'(property "Reference" "{ref}" (at 2.54 1.27 0) (effects (font (size 1.27 1.27)) (justify left)))',
           f'(property "Value" "{name}" (at 2.54 -1.27 0) (effects (font (size 1.27 1.27)) (justify left)))',
           f'(property "Footprint" "" (at 0 0 0) {FONT_HIDE})',
           f'(property "Datasheet" "" (at 0 0 0) {FONT_HIDE})',
           f'(symbol "{name}_0_1" {body})',
           f'(symbol "{name}_1_1"']
    for num, pname, ptype, x, y, ang in pins:
        out.append(f'(pin {ptype} line (at {fmt(x)} {fmt(y)} {ang}) (length 1.27) (name "{pname}" {FONT}) (number "{num}" {FONT}))')
    out.append("))")
    return "\n".join(out), pins


# ---- 回路 ------------------------------------------------------------------
ROOT = uid()
PROJECT = "SHVC-SOUND-ESP32"
lib_defs, pin_table = {}, {}
for n, (ref, spec) in SYMBOLS.items():
    lib_defs[n], pin_table[n] = lib_symbol_ic(n, ref, spec)
for n, ref, kind in (("R", "R", "R"), ("C", "C", "C"), ("FerriteBead", "FB", "L")):
    lib_defs[n], pin_table[n] = lib_symbol_2pin(n, ref, kind)
# 5Vレールへの逆流防止ダイオード。ERCで+5Vの供給元と見なせるようカソードを power_out にする
lib_defs["D_Schottky"], pin_table["D_Schottky"] = lib_symbol_2pin("D_Schottky", "D", "D", ("power_out", "power_in"))

items, labels, texts, noconn = [], [], [], []


# 基板で使うフットプリント(SHVC-ESP32: はこのフォルダの SHVC-ESP32.pretty)
FP_R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"
FP_C100N = "Capacitor_THT:C_Disc_D3.0mm_W1.6mm_P2.50mm"
FOOTPRINTS = {
    "U1": "SHVC-ESP32:ESP32-DevKit-30_Socket", "U2": "Package_DIP:DIP-20_W7.62mm",
    "U3": "Package_DIP:DIP-20_W7.62mm", "U4": "Package_DIP:DIP-20_W7.62mm", "U6": "Package_DIP:DIP-16_W7.62mm",
    "J4": "SHVC-ESP32:SHVC-SOUND-MB", "J1": "SHVC-ESP32:PJ-324M",
    "U7": "SHVC-ESP32:DCDC_SIP3_7805", "D1": "Diode_THT:D_DO-41_SOD81_P7.62mm_Horizontal",
    "C13": "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm",
    "J3": "SHVC-ESP32:PD_INPUT_MODULE_2P", "R10": FP_R,
    "R1": FP_R, "R2": FP_R, "R5": FP_R, "R6": FP_R, "R7": FP_R, "R8": FP_R, "R9": FP_R,
    "C3": FP_C100N, "C8": FP_C100N, "C9": FP_C100N, "C10": FP_C100N,
    "C6": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm", "C7": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
    "C5": "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm", "C1": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
    "C2": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm", "C12": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
    "C4": "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm", "C11": "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
}


def place(sym, ref, value, x, y, nets, footprint=""):
    """nets: {ピン番号: ネット名}。ピン番号が無いピンは未接続扱い(×印)。"""
    footprint = footprint or FOOTPRINTS.get(ref, "")
    pins = pin_table[sym]
    inst = [f'(symbol (lib_id "{LIB}:{sym}") (at {fmt(x)} {fmt(y)} 0) (unit 1) (exclude_from_sim no) '
            f'(in_bom yes) (on_board yes) (dnp no) (uuid "{uid()}")',
            f'(property "Reference" "{ref}" (at {fmt(x)} {fmt(y - 2)} 0) {FONT})',
            f'(property "Value" "{value}" (at {fmt(x)} {fmt(y + 2)} 0) {FONT})',
            f'(property "Footprint" "{footprint}" (at {fmt(x)} {fmt(y)} 0) {FONT_HIDE})',
            f'(property "Datasheet" "" (at {fmt(x)} {fmt(y)} 0) {FONT_HIDE})']
    if sym in SYMBOLS:                 # IC類: 名前は本体の上、値は本体の下
        _, _, ytop, ybot = ic_geometry(SYMBOLS[sym][1])
        inst[1] = f'(property "Reference" "{ref}" (at {fmt(x)} {fmt(y - ytop - 1.27)} 0) {FONT})'
        inst[2] = f'(property "Value" "{value}" (at {fmt(x)} {fmt(y - ybot + 1.9)} 0) {FONT})'
    if sym in ("R", "C", "FerriteBead", "D_Schottky"):
        inst[1] = f'(property "Reference" "{ref}" (at {fmt(x + 2.54)} {fmt(y - 1.27)} 0) (effects (font (size 1.27 1.27)) (justify left)))'
        inst[2] = f'(property "Value" "{value}" (at {fmt(x + 2.54)} {fmt(y + 1.27)} 0) (effects (font (size 1.27 1.27)) (justify left)))'
    for num, *_ in pins:
        inst.append(f'(pin "{num}" (uuid "{uid()}"))')
    inst.append(f'(instances (project "{PROJECT}" (path "/{ROOT}" (reference "{ref}") (unit 1)))))')
    items.append("\n".join(inst))
    for num, pname, ptype, px, py, ang in pins:
        ax, ay = x + px, y - py       # シンボル座標(上が+)→回路図座標(下が+)
        if num in nets and nets[num]:
            net = nets[num]
            if ang == 0:       # 左向きに出ているピン → ラベルは左へ
                lab_ang, just = 180, "right"
            elif ang == 180:
                lab_ang, just = 0, "left"
            elif ang == 270:   # 上に出ているピン(2ピン部品の1番)
                lab_ang, just = 90, "left"
            else:
                lab_ang, just = 270, "right"
            labels.append(f'(label "{net}" (at {fmt(ax)} {fmt(ay)} {lab_ang}) (fields_autoplaced yes) '
                          f'(effects (font (size 1.27 1.27)) (justify {just} bottom)) (uuid "{uid()}"))')
        else:
            noconn.append(f'(no_connect (at {fmt(ax)} {fmt(ay)}) (uuid "{uid()}"))')


def text(s, x, y, size=1.8):
    texts.append(f'(text "{s}" (exclude_from_sim no) (at {fmt(x)} {fmt(y)} 0) '
                 f'(effects (font (size {size} {size})) (justify left bottom)) (uuid "{uid()}"))')


D3 = [f"D{i}_3V3" for i in range(8)]
D5 = [f"SHVC_D{i}" for i in range(8)]
ESP_DATA_GPIO = ["IO13", "IO14", "IO16", "IO17", "IO18", "IO19", "IO21", "IO22"]   # D0..D7

# U1 ESP32
esp = {"3V3": "+3V3", "VIN": "+5V", "IO32": "RESET_3V3", "IO33": "VOL_PWM", "IO25": "RD_3V3", "IO26": "A0_3V3",
       "IO27": "A1_3V3", "IO23": "WR_3V3", "IO4": "OE_W", "IO5": "OE_R"}
esp.update(zip(ESP_DATA_GPIO, D3))
esp = {esp_pin(k): v for k, v in esp.items()}
esp.update({"14": "GND", "29": "GND"})
place("ESP32_DevKit_30", "U1", "ESP32 DevKit V1 (30pin)", 60.96, 101.6, esp)

# U2 74HCT541 データ書き込み
u2 = {"1": "OE_W", "19": "GND", "20": "+5V", "10": "GND"}
for k in range(8):
    u2[str(2 + k)] = D3[k]
    u2[str(18 - k)] = D5[k]
place("74HCT541", "U2", "74HCT541N (data write)", 147.32, 60.96, u2)

# U4 74LVC245 データ読み出し
u4 = {"1": "GND", "19": "OE_R", "20": "+3V3", "10": "GND"}
for k in range(8):
    u4[str(2 + k)] = D3[k]
    u4[str(18 - k)] = D5[k]
place("74LVC245", "U4", "74LVC245N (data read, DIR=B->A)", 147.32, 119.38, u4)

# U3 74HCT541 制御線
u3 = {"1": "GND", "19": "GND", "20": "+5V", "10": "GND",
      "2": "A0_3V3", "3": "A1_3V3", "4": "WR_3V3", "5": "RD_3V3", "6": "RESET_3V3", "7": "GND", "8": "GND", "9": "GND",
      "18": "SHVC_A0", "17": "SHVC_A1", "16": "SHVC_WR", "15": "SHVC_RD", "14": "SHVC_RESET"}
place("74HCT541", "U3", "74HCT541N (control)", 147.32, 177.8, u3)

# J4 SHVC-SOUND
shvc = {"1": "GND", "2": "+5V", "3": "SHVC_A0", "4": "SHVC_A1", "5": "SHVC_WR", "6": "SHVC_RD",
        "15": "SHVC_RESET", "18": "+5V", "19": "GND", "20": "+5V", "21": "AUDIO_L", "22": "AUDIO_R",
        "23": "GND", "24": "+5V"}
for k in range(8):
    shvc[str(7 + k)] = D5[k]
place("SHVC-SOUND", "J4", "SHVC-SOUND module", 233.68, 101.6, shvc)

# プルアップ(3.3V)
for ref, net, x in (("R7", "OE_W", 101.6), ("R8", "OE_R", 109.22), ("R9", "RESET_3V3", 116.84)):
    place("R", ref, "10k", x, 30.48, {"1": "+3V3", "2": net})

# パスコン
for ref, val, x, y, vcc in (("C8", "100n", 175.26, 30.48, "+5V"), ("C10", "100n", 175.26, 147.32, "+3V3"),
                             ("C9", "100n", 175.26, 205.74, "+5V"), ("C11", "470u", 205.74, 142.24, "+5V"),
                             ("C12", "100u", 30.48, 30.48, "+5V")):
    place("C", ref, val, x, y, {"1": vcc, "2": "GND"})

# アンプ(既存回路図から流用。R5だけ3.3V PWM用に 3.3k → 5.6k)
place("TDA7053A", "U6", "TDA7053A", 330.2, 101.6,
      {"2": "AMP_VC", "8": "AMP_VC", "4": "AMP_IN_L", "6": "AMP_IN_R", "5": "AMP_VP",
       "7": "GND", "10": "GND", "12": "GND", "13": "GND", "14": "GND", "9": "AMP_OUT_L", "16": "AMP_OUT_R"})
place("C", "C6", "470n", 281.94, 76.2, {"1": "AUDIO_L", "2": "AMP_IN_L"})
place("C", "C7", "470n", 292.1, 76.2, {"1": "AUDIO_R", "2": "AMP_IN_R"})
place("R", "R6", "10k", 281.94, 132.08, {"1": "VOL_PWM", "2": "AMP_VC"})
place("R", "R5", "5.6k", 292.1, 132.08, {"1": "AMP_VC", "2": "GND"})
place("C", "C5", "10u", 302.26, 132.08, {"1": "AMP_VC", "2": "GND"})
place("R", "R1", "330", 365.76, 76.2, {"1": "AMP_OUT_L", "2": "OUT_L_RC"})
place("C", "C1", "100u", 375.92, 76.2, {"1": "OUT_L_RC", "2": "JACK_L"})
place("R", "R2", "330", 365.76, 127.0, {"1": "AMP_OUT_R", "2": "OUT_R_RC"})
place("C", "C2", "100u", 375.92, 127.0, {"1": "OUT_R_RC", "2": "JACK_R"})
place("PJ-324M", "J1", "PJ-324M", 391.16, 101.6, {"1": "GND", "4": "JACK_L", "2": "JACK_R"})

# 電源入力
# PD入力(12V)ひとつで全体が動く: 12V → M78AR05(5V) → 1N5819 → +5V(ESP32 VIN・SHVC-SOUND・74HCT541)
# USBをつないだままでも、ダイオードでDC-DC側へは逆流しない(ESP32ボード側にもUSB→VINのダイオードがある前提)
place("PowerIn_2", "J3", "12V in (USB-PD)", 281.94, 172.72, {"1": "+12V", "2": "GND"})
place("M78AR05-0.5", "U7", "M78AR05-0.5", 190.5, 208.28, {"1": "+12V", "2": "GND", "3": "REG_5V"})
place("C", "C13", "10u", 170.18, 208.28, {"1": "+12V", "2": "GND"})
place("D_Schottky", "D1", "1N5819", 213.36, 208.28, {"1": "+5V", "2": "REG_5V"})
# 12V入力のノイズ除去: 10Ω と C4(220µF) で約72Hzのローパス(フェライトビーズの代わり)
place("R", "R10", "10", 297.18, 172.72, {"1": "+12V", "2": "AMP_VP"})
place("C", "C3", "100n", 322.58, 172.72, {"1": "AMP_VP", "2": "GND"})
place("C", "C4", "220u", 337.82, 172.72, {"1": "AMP_VP", "2": "GND"})

text("SHVC-SOUND player - ESP32 version (74HCT541N x2 + 74LVC245N + TDA7053A)", 20.32, 20.32, 2.5)
notes = [
    "Data bus: U2(HCT541, write 3.3V->5V) and U4(LVC245 DIR=GND, read 5V->3.3V) are in parallel.",
    "Firmware must never assert OE_W and OE_R (both active low) at the same time.",
    "R7/R8 keep both buffers disabled while the ESP32 boots. R9 keeps /RESET inactive.",
    "ESP32 DevKit V1 30pin (DOIT type). GPIO16/17 are PSRAM on WROVER boards - use WROOM-32.",
    "Amp circuit copied from SHVC-SOUND-KiCad (Arduino version). R5 3.3k -> 5.6k for 3.3V PWM, ferrite bead FB1 -> R10 10 ohm.",
    "TDA7053A pin names are inferred from the existing schematic; check the datasheet.",
    "12V (USB-PD) -> U7 M78AR05-0.5 -> D1 1N5819 -> +5V. USB on ESP32 can stay connected (board has VIN diode - check yours).",
    "Tie all grounds together at one point. Use electrolytics with correct polarity for C1/C2/C4/C5/C11/C12.",
]
for i, n in enumerate(notes):
    text(n, 20.32, 228.6 + i * 5.08, 1.5)

sch = [f'(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0") (uuid "{ROOT}") (paper "A3")',
       f'(title_block (title "SHVC-SOUND Player ESP32") (rev "0.1"))',
       "(lib_symbols"] + list(lib_defs.values()) + [")"] + items + labels + noconn + texts + \
      ['(sheet_instances (path "/" (page "1")))', ")"]

with open("SHVC-SOUND-ESP32.kicad_sch", "w", encoding="utf-8") as f:
    f.write("\n".join(sch) + "\n")
lib = ["(kicad_symbol_lib (version 20251024) (generator \"gen_schematic\") (generator_version \"10.0\")"]
lib += [d.replace(f'(symbol "{LIB}:', '(symbol "', 1) for d in lib_defs.values()] + [")"]
with open(f"{LIB}.kicad_sym", "w", encoding="utf-8") as f:
    f.write("\n".join(lib) + "\n")
with open("sym-lib-table", "w", encoding="utf-8") as f:
    f.write(f'(sym_lib_table (version 7)\n  (lib (name "{LIB}") (type "KiCad") '
            f'(uri "${{KIPRJMOD}}/{LIB}.kicad_sym") (options "") (descr ""))\n)\n')
print(f"部品 {len(items)} / ラベル {len(labels)} / 未接続 {len(noconn)} -> SHVC-SOUND-ESP32.kicad_sch")
