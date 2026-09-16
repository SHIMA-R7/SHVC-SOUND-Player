import pcbnew, json
b = pcbnew.LoadBoard("SHVC-SOUND-ESP32.kicad_pcb")
T = pcbnew.ToMM
OX, OY = 100.0, 100.0
out = {"edges": [], "circles": [], "pads": [], "fps": []}
for d in b.GetDrawings():
    if d.GetLayerName() != "Edge.Cuts": continue
    if d.GetShapeStr() == "Circle":
        c = d.GetCenter(); out["circles"].append([T(c.x)-OX, T(c.y)-OY, T(d.GetRadius())])
    else:
        out["edges"].append([T(d.GetStart().x)-OX, T(d.GetStart().y)-OY, T(d.GetEnd().x)-OX, T(d.GetEnd().y)-OY])
for fp in b.GetFootprints():
    p = fp.GetPosition()
    bb = fp.GetBoundingBox(False)
    out["fps"].append({"ref": fp.GetReference(), "side": "B" if fp.IsFlipped() else "F",
        "x": T(p.x)-OX, "y": T(p.y)-OY,
        "bb": [T(bb.GetX())-OX, T(bb.GetY())-OY, T(bb.GetWidth()), T(bb.GetHeight())]})
    for pad in fp.Pads():
        q = pad.GetPosition(); s = pad.GetSize(pcbnew.F_Cu) if hasattr(pad, "GetSize") else pad.GetSize()
        out["pads"].append({"ref": fp.GetReference(), "num": pad.GetNumber(), "x": T(q.x)-OX, "y": T(q.y)-OY,
            "w": T(s.x), "h": T(s.y), "drill": T(pad.GetDrillSizeX()), "smd": pad.GetAttribute()==pcbnew.PAD_ATTRIB_SMD,
            "rot": pad.GetOrientationDegrees(), "net": pad.GetNetname(), "fn": pad.GetPinFunction()})
import sys
json.dump(out, open(sys.argv[1],"w"), indent=0)
print(len(out["pads"]), len(out["edges"]), len(out["circles"]))
