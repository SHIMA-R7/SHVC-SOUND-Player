#!/usr/bin/env python3
"""
rom_tools.py - スーファミROM(カセットから吸い出したもの)の解析

現状できること:
  - コピア(吸い出し機)ヘッダの検出と除去
  - LoROM / HiROM / ExHiROM の自動判別
  - 内部ヘッダ(タイトル、マッパ、ROM/RAM容量、リージョン、チェックサム)の読み取り
  - チェックサムの再計算による整合性チェック

できないこと(重要):
  ROMの中に .spc ファイルは入っていない。.spc はSPC700の64KB ARAM +
  DSPレジスタ + CPUレジスタの「実行中のある瞬間のスナップショット」であり、
  ROMに入っているのはサウンドドライバのコードとBRRサンプルと曲データ。
  そこから.spcを作るには、実際にゲームを動かして(=SNESをエミュレートして)
  music再生中のARAMをダンプする必要がある。詳しくは extraction_note() を参照。
"""

REGIONS = {
    0x00: "日本", 0x01: "北米", 0x02: "欧州", 0x03: "スウェーデン/スカンジナビア",
    0x04: "フィンランド", 0x05: "デンマーク", 0x06: "フランス", 0x07: "オランダ",
    0x08: "スペイン", 0x09: "ドイツ", 0x0A: "イタリア", 0x0B: "中国",
    0x0C: "インドネシア", 0x0D: "韓国", 0x0F: "カナダ", 0x10: "ブラジル",
    0x11: "オーストラリア",
}

# 内部ヘッダの候補位置(コピアヘッダ除去後のオフセット)
HEADER_CANDIDATES = [
    ("LoROM", 0x7FC0),
    ("HiROM", 0xFFC0),
    ("ExHiROM", 0x40FFC0),
]


def strip_copier_header(data: bytes):
    """
    吸い出し機が付ける512バイトのヘッダがあれば取り除く。
    (ROM本体は必ず1KBの倍数なので、512余ったらコピアヘッダとみなすのが定石)
    戻り値: (ヘッダ除去後のデータ, ヘッダがあったか)
    """
    if len(data) % 1024 == 512:
        return data[512:], True
    return data, False


def _score_header(data: bytes, offset: int) -> int:
    """
    その位置が本物の内部ヘッダらしいかを採点する。
    複数の候補位置から最もそれらしいものを選ぶために使う。
    """
    if offset + 0x30 > len(data):
        return -1

    score = 0
    hdr = data[offset:offset + 0x30]

    # チェックサムと、その補数の関係が成立していれば非常に強い証拠
    checksum = hdr[0x2E] | (hdr[0x2F] << 8)
    complement = hdr[0x2C] | (hdr[0x2D] << 8)
    if checksum ^ complement == 0xFFFF:
        score += 8

    # タイトル21文字が印字可能なASCIIか
    title = hdr[0x00:0x15]
    printable = sum(1 for c in title if 0x20 <= c <= 0x7E)
    score += printable // 4

    # リセットベクタが妥当な範囲($8000以上)を指しているか
    if offset + 0x3C + 2 <= len(data):
        reset_vec = data[offset + 0x3C] | (data[offset + 0x3D] << 8)
        if reset_vec >= 0x8000:
            score += 4

    # ROM容量の指数が現実的な範囲か
    if 0x08 <= hdr[0x17] <= 0x0D:
        score += 2

    return score


def analyze(path: str) -> dict:
    """ROMファイルを解析して結果をdictで返す。"""
    with open(path, "rb") as f:
        raw = f.read()

    data, had_copier = strip_copier_header(raw)

    best_name, best_off, best_score = None, None, -1
    for name, off in HEADER_CANDIDATES:
        s = _score_header(data, off)
        if s > best_score:
            best_name, best_off, best_score = name, off, s

    info = {
        "path": path,
        "file_size": len(raw),
        "rom_size": len(data),
        "copier_header": had_copier,
        "mapper": best_name,
        "header_offset": best_off,
        "header_score": best_score,
    }

    if best_off is None or best_score < 0:
        info["error"] = "内部ヘッダを検出できませんでした(SNESのROMではないかもしれません)"
        return info

    hdr = data[best_off:best_off + 0x30]
    raw_title = hdr[0x00:0x15]
    try:
        title = raw_title.decode("cp932").strip()
    except UnicodeDecodeError:
        title = raw_title.decode("latin-1").strip()

    checksum = hdr[0x2E] | (hdr[0x2F] << 8)
    complement = hdr[0x2C] | (hdr[0x2D] << 8)

    info.update({
        "title": title.rstrip("\x00").strip(),
        "map_mode": hdr[0x15],
        "fast_rom": bool(hdr[0x15] & 0x10),
        "chipset": hdr[0x16],
        "rom_size_kb": 1 << hdr[0x17] if hdr[0x17] < 32 else None,
        "ram_size_kb": (1 << hdr[0x18]) if hdr[0x18] and hdr[0x18] < 32 else 0,
        "region_code": hdr[0x19],
        "region": REGIONS.get(hdr[0x19], f"不明(0x{hdr[0x19]:02X})"),
        "developer_id": hdr[0x1A],
        "version": hdr[0x1B],
        "checksum": checksum,
        "checksum_complement": complement,
        "checksum_pair_ok": (checksum ^ complement) == 0xFFFF,
    })

    info["checksum_actual"] = compute_checksum(data)
    info["checksum_ok"] = info["checksum_actual"] == checksum
    return info


def compute_checksum(data: bytes) -> int:
    """
    ROM全体のバイト単純加算(16bit)を求める。
    ヘッダ内のチェックサム2バイトと補数2バイトは、格納前の
    既定値($0000と$FFFF、合計$01FE)として扱うのが本来の定義だが、
    ここでは実用上のブレを避けるため素の総和を返す。
    サイズが2のべき乗でないROMは、本来ミラーリングを考慮する必要があり
    値がずれることがある。
    """
    return sum(data) & 0xFFFF


def format_report(info: dict) -> str:
    """analyze()の結果を人間が読める文字列にする。"""
    if "error" in info:
        return (f"ファイル: {info['path']}\n"
                f"サイズ: {info['file_size']:,} バイト\n\n"
                f"エラー: {info['error']}\n")

    lines = [
        f"ファイル       : {info['path']}",
        f"ファイルサイズ : {info['file_size']:,} バイト"
        + ("  (512バイトのコピアヘッダを検出・除去しました)" if info["copier_header"] else ""),
        "",
        f"タイトル       : {info['title']}",
        f"マッパ         : {info['mapper']}  (内部ヘッダ位置 ${info['header_offset']:06X})",
        f"高速ROM        : {'はい (FastROM)' if info['fast_rom'] else 'いいえ (SlowROM)'}",
        f"ROM容量        : {info['rom_size_kb']} KB (ヘッダ表記) / 実ファイル {info['rom_size'] // 1024} KB",
        f"セーブRAM      : {info['ram_size_kb']} KB" if info["ram_size_kb"] else "セーブRAM      : なし",
        f"リージョン     : {info['region']}",
        f"バージョン     : 1.{info['version']}",
        "",
        f"チェックサム   : ${info['checksum']:04X} / 補数 ${info['checksum_complement']:04X}"
        + ("  [対応OK]" if info["checksum_pair_ok"] else "  [対応が不正]"),
        f"実測値         : ${info['checksum_actual']:04X}"
        + ("  [一致]" if info["checksum_ok"] else "  [不一致: 吸い出し不良か、非2のべき乗サイズのROM]"),
    ]
    return "\n".join(lines) + "\n"


def extraction_note() -> str:
    """SPC抽出について、なぜ単純にはできないのかの説明文。"""
    return (
        "■ ROMから .spc を直接取り出すことはできません\n"
        "\n"
        ".spc ファイルは「SPC700が曲を再生している最中の状態まるごとのスナップショット」です。\n"
        "中身は ARAM 64KB + DSPレジスタ128バイト + CPUレジスタで構成されています。\n"
        "\n"
        "一方ROMに入っているのは、\n"
        "  ・サウンドドライバのプログラム(ゲームごとに異なる。N-SPC、Rare独自、コナミ独自…)\n"
        "  ・BRR形式の音色サンプル\n"
        "  ・曲のシーケンスデータ\n"
        "がバラバラに格納されたものです。ARAMの完成イメージはROMの中には存在せず、\n"
        "ゲームを実際に起動してドライバが組み立てて初めて出来上がります。\n"
        "\n"
        "つまり .spc を作るには「ゲームを実際に動かす」必要があり、\n"
        "それはSNESのエミュレーションそのものです。\n"
        "\n"
        "■ 実用的な手順\n"
        "\n"
        "SPCダンプ機能を持つエミュレータでROMを動かし、曲が鳴っている状態でダンプします。\n"
        "  ・Mesen2      … Tools → Sound → Save SPC\n"
        "  ・bsnes / higan … SPCダンプ対応\n"
        "  ・Snes9x      … ビルドによりSPCダンプ対応\n"
        "\n"
        "吐き出された .spc をこのアプリのプレイリストに入れれば、実機で鳴らせます。\n"
        "「フォルダを監視」を使うと、エミュレータの出力先を指定しておくだけで\n"
        "新しくダンプされた .spc が自動でプレイリストに追加されます。\n"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"使い方: {sys.argv[0]} <ROMファイル>")
        sys.exit(1)
    print(format_report(analyze(sys.argv[1])))
