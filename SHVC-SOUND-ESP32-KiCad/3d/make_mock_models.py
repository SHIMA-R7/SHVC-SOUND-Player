"""
モックアップ用の簡易3Dモデル(直方体の組み合わせ)をSTEPで書き出す。
寸法はデータシート・実測の外形。細部は省略し「当たるかどうか」を見るための箱モデル。

座標はKiCadの3Dモデル座標: X=フットプリントのX、Y=フットプリントの-Y、Z=部品面から離れる向き(mm)。
実行: python make_mock_models.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def fp_box(x0, x1, y0, y1, z0, z1):
    """フットプリント座標(Y下向き)で指定した箱をモデル座標に直す。"""
    return (x0, x1, -y1, -y0, z0, z1)


MODELS = {
    # ESP32 DevKit V1(30ピン)。ソケット本体はKiCad標準モデルを別に付ける
    "esp32_devkit_v1_30.step": [
        fp_box(-1.27, 1.27, -1.27, 36.83, 8.5, 11.0),          # オスヘッダの樹脂(左列)
        fp_box(24.13, 26.67, -1.27, 36.83, 8.5, 11.0),         # オスヘッダの樹脂(右列)
        fp_box(-1.45, 26.85, -8.5, 43.0, 11.0, 12.6),          # DevKit基板 51.5×28.3
        fp_box(3.7, 21.7, -8.5, 17.0, 12.6, 15.8),             # WROOM-32(アンテナ側)
        fp_box(8.7, 16.7, 38.0, 44.0, 12.6, 15.4),             # micro USB(1mm はみ出し)
        fp_box(1.5, 5.5, 37.0, 40.0, 12.6, 14.1),              # EN/BOOTボタン
        fp_box(19.9, 23.9, 37.0, 40.0, 12.6, 14.1),
    ],
    # SOFNG PJ-324M: 本体14.2×11.5×6.3、ネジ部M6×3.5
    "pj-324m.step": [
        fp_box(-7.39, 6.81, -5.65, 5.85, 0.0, 6.3),
        fp_box(-10.9, -7.39, -2.65, 3.35, 0.15, 6.15),
    ],
    # 7805互換DC-DC(M78AR05-0.5 相当): 幅11.6×厚み7.5×高さ10.2。足は本体の片側寄り
    "dcdc_sip3.step": [
        fp_box(-6.5, 1.0, -3.26, 8.34, 0.0, 10.2),
    ],
    # USB-PDトリガーモジュール: 外形10.5×8.5、高さは部品込みの包絡(約6mm)
    "pd_module.step": [
        fp_box(-5.25, 5.25, -4.25, 4.25, 0.0, 6.0),
    ],
}


def step_file(name, boxes):
    ents = []

    def add(text):
        ents.append(text)
        return f"#{len(ents) + 99}"          # 番号は #100 から

    solids = []
    for (x0, x1, y0, y1, z0, z1) in boxes:
        xs, ys, zs = (x0, x1), (y0, y1), (z0, z1)
        vp = []
        for k in range(2):
            for j in range(2):
                for i in range(2):
                    pt = add(f"CARTESIAN_POINT('',({xs[i]:.4f},{ys[j]:.4f},{zs[k]:.4f}))")
                    vp.append((add(f"VERTEX_POINT('',{pt})"), (xs[i], ys[j], zs[k])))
        edges = {}

        def edge(a, b):
            if (a, b) in edges:
                return edges[(a, b)], ".T."
            if (b, a) in edges:
                return edges[(b, a)], ".F."
            pa, pb = vp[a][1], vp[b][1]
            d = [pb[n] - pa[n] for n in range(3)]
            length = sum(v * v for v in d) ** 0.5
            u = [v / length for v in d]
            p = add(f"CARTESIAN_POINT('',({pa[0]:.4f},{pa[1]:.4f},{pa[2]:.4f}))")
            dr = add(f"DIRECTION('',({u[0]:.1f},{u[1]:.1f},{u[2]:.1f}))")
            vec = add(f"VECTOR('',{dr},{length:.4f})")
            ln = add(f"LINE('',{p},{vec})")
            e = add(f"EDGE_CURVE('',{vp[a][0]},{vp[b][0]},{ln},.T.)")
            edges[(a, b)] = e
            return e, ".T."

        # 外側から見て反時計回り(法線, 頂点4つ)
        faces_def = [((0, 0, -1), (0, 2, 3, 1)), ((0, 0, 1), (4, 5, 7, 6)), ((0, -1, 0), (0, 1, 5, 4)),
                     ((0, 1, 0), (2, 6, 7, 3)), ((-1, 0, 0), (0, 4, 6, 2)), ((1, 0, 0), (1, 3, 7, 5))]
        faces = []
        for normal, loop in faces_def:
            oes = []
            for n in range(4):
                e, sense = edge(loop[n], loop[(n + 1) % 4])
                oes.append(add(f"ORIENTED_EDGE('',*,*,{e},{sense})"))
            el = add(f"EDGE_LOOP('',({','.join(oes)}))")
            fb = add(f"FACE_OUTER_BOUND('',{el},.T.)")
            o = vp[loop[0]][1]
            p = add(f"CARTESIAN_POINT('',({o[0]:.4f},{o[1]:.4f},{o[2]:.4f}))")
            nd = add(f"DIRECTION('',({normal[0]:.1f},{normal[1]:.1f},{normal[2]:.1f}))")
            ref = (1, 0, 0) if normal[0] == 0 else (0, 1, 0)
            rd = add(f"DIRECTION('',({ref[0]:.1f},{ref[1]:.1f},{ref[2]:.1f}))")
            ax = add(f"AXIS2_PLACEMENT_3D('',{p},{nd},{rd})")
            pl = add(f"PLANE('',{ax})")
            faces.append(add(f"ADVANCED_FACE('',({fb}),{pl},.T.)"))
        shell = add(f"CLOSED_SHELL('',({','.join(faces)}))")
        solids.append(add(f"MANIFOLD_SOLID_BREP('box',{shell})"))

    title = os.path.splitext(name)[0]
    head = [
        "#1=APPLICATION_CONTEXT('core data for automotive mechanical design processes');",
        "#2=APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#1);",
        "#3=PRODUCT_CONTEXT('',#1,'mechanical');",
        f"#4=PRODUCT('{title}','{title}','',(#3));",
        "#5=PRODUCT_DEFINITION_FORMATION('','',#4);",
        "#6=PRODUCT_DEFINITION_CONTEXT('part definition',#1,'design');",
        "#7=PRODUCT_DEFINITION('design','',#5,#6);",
        "#8=PRODUCT_DEFINITION_SHAPE('','',#7);",
        "#9=SHAPE_DEFINITION_REPRESENTATION(#8,#20);",
        "#10=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
        "#11=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));",
        "#12=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());",
        "#13=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#10,'distance_accuracy_value','confusion accuracy');",
        "#14=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#13))"
        "GLOBAL_UNIT_ASSIGNED_CONTEXT((#10,#11,#12))REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY'));",
        "#15=AXIS2_PLACEMENT_3D('',#16,#17,#18);",
        "#16=CARTESIAN_POINT('',(0.,0.,0.));",
        "#17=DIRECTION('',(0.,0.,1.));",
        "#18=DIRECTION('',(1.,0.,0.));",
        f"#20=ADVANCED_BREP_SHAPE_REPRESENTATION('{title}',(#15,{','.join(solids)}),#14);",
        "#21=PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#4));",
    ]
    body = [f"#{n + 100}={t};" for n, t in enumerate(ents)]
    return "\n".join(["ISO-10303-21;", "HEADER;", "FILE_DESCRIPTION(('mockup box model'),'2;1');",
                      f"FILE_NAME('{name}','2026-09-17T00:00:00',(''),(''),'','','');",
                      "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));", "ENDSEC;", "DATA;"]
                     + head + body + ["ENDSEC;", "END-ISO-10303-21;", ""])


if __name__ == "__main__":
    for name, boxes in MODELS.items():
        with open(os.path.join(HERE, name), "w", encoding="ascii") as f:
            f.write(step_file(name, boxes))
        print("書き出し:", name, len(boxes), "個の箱")
