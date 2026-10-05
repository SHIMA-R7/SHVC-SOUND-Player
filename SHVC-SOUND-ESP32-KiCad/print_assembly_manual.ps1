# ESP32版 SHVC-SOUND 基板の組み立て説明書(A4 4ページ)を印刷する
#   powershell -ExecutionPolicy Bypass -File print_assembly_manual.ps1 -Geom geom.json -Bom BOM.csv -ImgParts a.png -ImgModule b.png [-Printer 名前 | -PdfOut 出力.pdf]
param(
    [Parameter(Mandatory = $true)][string]$Geom,
    [Parameter(Mandatory = $true)][string]$Bom,
    [Parameter(Mandatory = $true)][string]$ImgParts,
    [Parameter(Mandatory = $true)][string]$ImgModule,
    [string]$Printer = "",
    [string]$PdfOut = ""
)
Add-Type -AssemblyName System.Drawing
$g = Get-Content -Raw -Encoding UTF8 $Geom | ConvertFrom-Json
$bomRows = Import-Csv -Path $Bom -Encoding UTF8
$script:bmpParts = [System.Drawing.Image]::FromFile($ImgParts)
$script:bmpModule = [System.Drawing.Image]::FromFile($ImgModule)
$BW = 74.09; $BH = 66.5

$doc = New-Object System.Drawing.Printing.PrintDocument
if ($PdfOut) {
    $doc.PrinterSettings.PrinterName = "Microsoft Print to PDF"
    $doc.PrinterSettings.PrintToFile = $true
    $doc.PrinterSettings.PrintFileName = $PdfOut
} elseif ($Printer) { $doc.PrinterSettings.PrinterName = $Printer }
if (-not $doc.PrinterSettings.IsValid) { throw "プリンターが見つからない" }
$a4 = $doc.PrinterSettings.PaperSizes | Where-Object { $_.Kind -eq [System.Drawing.Printing.PaperKind]::A4 } | Select-Object -First 1
$doc.DefaultPageSettings.PaperSize = $a4
$doc.DefaultPageSettings.Landscape = $false
$doc.DocumentName = "SHVC-SOUND ESP32 assembly manual"
$script:page = 1

function F($size, $bold = $false) {
    $st = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    New-Object System.Drawing.Font "Yu Gothic UI", $size, $st, ([System.Drawing.GraphicsUnit]::Millimeter)
}
$black = [System.Drawing.Brushes]::Black
$gray = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(90, 90, 90))
$penThin = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.15
$penMid = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.35
$penGrid = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(160, 160, 160)), 0.12

function Header($gr, $title) {
    $gr.DrawString("SHVC-SOUND ESP32版 組み立て説明書  r0.3", (F 3.0), $gray, 15, 9)
    $gr.DrawString("$($script:page) / 4", (F 3.0), $gray, 180, 9)
    $gr.DrawLine($penThin, 15, 15, 195, 15)
    $gr.DrawString($title, (F 6.0 $true), $black, 15, 18)
}

function Fit-Image($gr, $img, $x, $y, $w, $h) {
    $r = [math]::Min($w / $img.Width, $h / $img.Height)
    $iw = $img.Width * $r; $ih = $img.Height * $r
    $gr.DrawImage($img, [single]($x + ($w - $iw) / 2), [single]($y + ($h - $ih) / 2), [single]$iw, [single]$ih)
}

# ---- 1ページ目: 外観
function Page1($gr) {
    Header $gr "1. 外観"
    Fit-Image $gr $script:bmpParts 15 30 180 112
    $gr.DrawString("部品面(裏面)。ESP32、IC、電源、アンプ、ジャックはすべてこちらに付ける。", (F 3.2), $black, 15, 143)
    Fit-Image $gr $script:bmpModule 15 152 180 100
    $gr.DrawString("モジュール面(表面)。SHVC-SOUNDのソケット(J4)だけ。SHVC-SOUNDは部品面を下にして挿す。", (F 3.2), $black, 15, 253)
    $y = 262
    foreach ($t in @(
            "基板 74.09 × 66.5mm 2層 / 電源: USB-PD 12V ひとつ(DC-DCで5Vを作る)",
            "ESP32 DevKit V1(30ピン)で SHVC-SOUND を制御、TDA7053A でヘッドホンを鳴らす",
            "固定穴: φ4.0mm(M3) と φ3.0mm(M2.5)。SHVC-SOUND の穴位置と同じ")) {
        $gr.DrawString("・" + $t, (F 3.0), $black, 18, $y); $y += 6
    }
}

# ---- 2ページ目: パーツ表
function Page2($gr) {
    Header $gr "2. パーツ表"
    $cols = @(@("部品番号", 26), @("数", 8), @("品名・値", 40), @("仕様・形状", 58), @("役割・注意", 48))
    $x0 = 15; $y = 30
    $fh = F 2.6 $true; $fb = F 2.5
    $x = $x0
    $gr.FillRectangle((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(225, 225, 225))), 15, $y, 180, 6.5)
    foreach ($c in $cols) { $gr.DrawString($c[0], $fh, $black, [single]($x + 1), [single]($y + 1.2)); $x += $c[1] }
    $y += 6.5
    foreach ($r in $bomRows) {
        $vals = @($r.'部品番号', $r.'数量', $r.'品名・値', $r.'仕様・形状', $r.'備考')
        $h = 0
        for ($i = 0; $i -lt 5; $i++) {
            $sz = $gr.MeasureString([string]$vals[$i], $fb, [single]($cols[$i][1] - 2))
            $h = [math]::Max($h, $sz.Height)
        }
        $h += 1.6
        $x = $x0
        for ($i = 0; $i -lt 5; $i++) {
            $rect = New-Object System.Drawing.RectangleF ([single]($x + 1)), ([single]($y + 0.8)), ([single]($cols[$i][1] - 2)), ([single]$h)
            $gr.DrawString([string]$vals[$i], $fb, $black, $rect)
            $x += $cols[$i][1]
        }
        $y += $h
        $gr.DrawLine($penGrid, 15, [single]$y, 195, [single]$y)
    }
    $gr.DrawString("□ にチェックしながら揃えると抜けが防げます。任意(ICソケット・スペーサー)は無くても組めます。", (F 2.8), $gray, 15, [single]($y + 3))
}

# ---- 部品配置図(裏面=部品面から見た向き。左右反転)
function Placement($gr, $ox, $oy, $s) {
    $gr.DrawRectangle($penMid, [single]$ox, [single]$oy, [single]($BW * $s), [single]($BH * $s))
    $colors = @{ "U" = [System.Drawing.Color]::FromArgb(210, 225, 255); "C" = [System.Drawing.Color]::FromArgb(255, 235, 200);
        "R" = [System.Drawing.Color]::FromArgb(230, 255, 220); "J" = [System.Drawing.Color]::FromArgb(245, 220, 245);
        "D" = [System.Drawing.Color]::FromArgb(255, 220, 220)
    }
    foreach ($fp in $g.fps | Where-Object { $_.side -eq "B" } | Sort-Object { -($_.bb[2] * $_.bb[3]) }) {
        $k = $fp.ref.Substring(0, 1)
        $col = if ($colors.ContainsKey($k)) { $colors[$k] } else { [System.Drawing.Color]::White }
        $bx = $ox + ($BW - $fp.bb[0] - $fp.bb[2]) * $s; $by = $oy + $fp.bb[1] * $s
        $rw = $fp.bb[2] * $s; $rh = $fp.bb[3] * $s
        if ($fp.ref -eq "U1") {
            # ESP32は大きいので枠だけ(下の部品が見えるように)
            $pd = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(40, 70, 160)), 0.4
            $pd.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
            $gr.DrawRectangle($pd, [single]$bx, [single]$by, [single]$rw, [single]$rh)
            continue
        }
        $gr.FillRectangle((New-Object System.Drawing.SolidBrush $col), [single]$bx, [single]$by, [single]$rw, [single]$rh)
        $gr.DrawRectangle($penThin, [single]$bx, [single]$by, [single]$rw, [single]$rh)
    }
    foreach ($p in $g.pads) {
        $px = $ox + ($BW - $p.x) * $s; $py = $oy + $p.y * $s
        $d = [math]::Max($p.w, $p.h) * $s * 0.8
        if ($p.ref -like "H*") {
            $d = $p.w * $s
            $gr.DrawEllipse($penMid, [single]($px - $d / 2), [single]($py - $d / 2), [single]$d, [single]$d)
            continue
        }
        $br = if ($p.num -eq "1") { $black } else { [System.Drawing.Brushes]::DimGray }
        if ($p.num -eq "1") { $gr.FillRectangle($br, [single]($px - $d / 2), [single]($py - $d / 2), [single]$d, [single]$d) }
        else { $gr.FillEllipse($br, [single]($px - $d / 2), [single]($py - $d / 2), [single]$d, [single]$d) }
    }
    # 部品番号と値
    $fr = F 2.6 $true; $fv = F 2.0
    foreach ($fp in $g.fps | Where-Object { $_.side -eq "B" }) {
        $cx = $ox + ($BW - $fp.bb[0] - $fp.bb[2] / 2) * $s; $cy = $oy + ($fp.bb[1] + $fp.bb[3] / 2) * $s
        $val = ($fp.value -replace " \(.*\)$", "")
        if ($fp.ref -eq "U1") { $cx = $ox + ($BW - 16.7) * $s; $cy = $oy - 1.2 * $s; $val = "ESP32 DevKit V1(破線、USBは上)" }
        $t1 = $gr.MeasureString($fp.ref, $fr); $t2 = $gr.MeasureString($val, $fv)
        $wbg = [math]::Max($t1.Width, $t2.Width)
        $gr.FillRectangle((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(215, 255, 255, 255))), [single]($cx - $wbg / 2), [single]($cy - $t1.Height + 0.3), [single]$wbg, [single]($t1.Height + $t2.Height - 0.6))
        $gr.DrawString($fp.ref, $fr, $black, [single]($cx - $t1.Width / 2), [single]($cy - $t1.Height + 0.5))
        $gr.DrawString($val, $fv, $black, [single]($cx - $t2.Width / 2), [single]($cy - 0.2))
    }
}

# ---- 3ページ目: 部品面の配置
function Page3($gr) {
    Header $gr "3. 部品の配置(部品面=裏面から見た図)"
    $s = 2.35
    Placement $gr 18 32 $s
    $y = 32 + $BH * $s + 5
    $gr.DrawString("■ = 1番ピン(四角いパッド)   ○ = 固定穴   上辺側に ESP32 の USB が来る", (F 2.8), $black, 18, $y)
    $y += 7
    $gr.DrawString("向きに注意する部品", (F 3.6 $true), $black, 15, $y); $y += 6.5
    foreach ($t in @(
            "IC(U2 U3 U4 U6): 1番ピン(■)にICの切り欠き・丸印側を合わせる。U3はESP32の下になるのでソケットを使わず直付け",
            "電解コンデンサ(C1 C2 C4 C5 C11 C12 C13): ■のパッドが +(長い足)。帯のある足は反対側",
            "ダイオード D1(1N5819): ■のパッドが K(帯のある側)",
            "DC-DC U7: ■=IN(12V)、真ん中=GND、残り=OUT(5V)。本体は基板の内側(ESP32側)へ",
            "PDモジュール J3: 12V側が■。USB-C口は基板の下辺(外側)へ",
            "ESP32 ソケット U1: 1x15 を2本。ESP32 は USB を上辺側にして挿す",
            "ジャック J1: 差し込み口を基板の右辺(この図では左辺)の外へ。足5本は向きが決まっている")) {
        $rect = New-Object System.Drawing.RectangleF 18, ([single]$y), 177, 12
        $sz = $gr.MeasureString("・" + $t, (F 2.8), 177)
        $gr.DrawString("・" + $t, (F 2.8), $black, $rect)
        $y += $sz.Height + 1.2
    }
}

# ---- 4ページ目: モジュール面と組み立て手順
function Page4($gr) {
    Header $gr "4. モジュール面と組み立て手順"
    $s = 1.25; $ox = 15; $oy = 32
    $gr.DrawRectangle($penMid, [single]$ox, [single]$oy, [single]($BW * $s), [single]($BH * $s))
    foreach ($p in $g.pads) {
        $px = $ox + $p.x * $s; $py = $oy + $p.y * $s
        if ($p.ref -like "H*") { $d = $p.w * $s; $gr.DrawEllipse($penMid, [single]($px - $d / 2), [single]($py - $d / 2), [single]$d, [single]$d); continue }
        $d = [math]::Max($p.w, $p.h) * $s * 0.7
        $br = if ($p.ref -eq "J4") { $black } else { [System.Drawing.Brushes]::Silver }
        $gr.FillEllipse($br, [single]($px - $d / 2), [single]($py - $d / 2), [single]$d, [single]$d)
    }
    $j4 = $g.pads | Where-Object { $_.ref -eq "J4" }
    $minx = ($j4 | Measure-Object x -Minimum).Minimum; $maxx = ($j4 | Measure-Object x -Maximum).Maximum
    $gr.DrawRectangle($penMid, [single]($ox + ($minx - 1.2) * $s), [single]($oy + 4.6 * $s), [single](($maxx - $minx + 2.4) * $s), [single](4.9 * $s))
    $gr.DrawString("J4", (F 3.0 $true), $black, [single]($ox + ($minx + 8) * $s), [single]($oy + 10.5 * $s))
    $tx = 112; $ty = 32
    foreach ($t in @(
            "J4 = 2.0mmピッチ 1x12 ピンソケット ×2",
            "・この面(表面)に立てて、裏面ではんだ付け",
            "・2本の列の間隔は 2.5mm(基板の穴に合わせる)",
            "・SHVC-SOUND は部品面を下にして挿す",
            "",
            "裏面の部品の足は、表面側で 1.5mm 以下に",
            "切りそろえる(モジュールに当たらないように)")) {
        $gr.DrawString($t, (F 2.8), $black, $tx, $ty); $ty += 5.2
    }
    $y = 122
    $gr.DrawString("組み立て手順(背の低い部品から)", (F 3.8 $true), $black, 15, $y); $y += 8
    $n = 1
    foreach ($t in @(
            "抵抗 R1 R2 R5〜R10 と ダイオード D1 を付ける(D1 は帯=K を■側)",
            "セラミックコンデンサ C3 C6 C7 C8 C9 C10 を付ける",
            "U3(74HCT541N)を直付け。1番ピンの向きを確認してからはんだ付け",
            "ICソケット(U2 U4 U6)を付ける。ソケットの切り欠きも1番ピン側へ",
            "電解コンデンサ C1 C2 C4 C5 C11 C12 C13 を付ける(■=+)",
            "DC-DC U7、PDモジュール J3、ジャック J1 を付ける",
            "ESP32用ソケット(1x15 ×2)を部品面に付ける",
            "表面に J4(1x12 ソケット ×2)を付ける。裏面の足を短く切る",
            "【通電チェック】IC・ESP32・SHVC-SOUND を挿さずに 12V を入れ、C11 の両端が約4.7V、J3 が12Vか測る",
            "電源を切って U2(74HCT541N) U4(74LVC245N) U6(TDA7053A) を挿す",
            "ESP32 を USB を上辺側にして挿す。もう一度通電し、ESP32 の 3V3 ピンが 3.3V か測る",
            "電源を切って SHVC-SOUND を J4 に挿し、固定穴をネジ・スペーサーで止める",
            "ジャックにプラグを挿し、テスターで 4番=L(チップ)、2番=R(リング)を確認")) {
        $rect = New-Object System.Drawing.RectangleF 24, ([single]$y), 170, 14
        $sz = $gr.MeasureString($t, (F 2.9), 170)
        $gr.DrawString("$n.", (F 2.9 $true), $black, 16, [single]$y)
        $gr.DrawString($t, (F 2.9), $black, $rect)
        $y += $sz.Height + 1.8; $n++
    }
    $gr.DrawString("注意: PD電源とESP32のUSBを同時につなぐのは、ESP32ボードのVINにダイオードがある場合だけ。", (F 2.7), $gray, 15, [single]($y + 3))
}

$doc.add_PrintPage({
        param($s, $e)
        $gr = $e.Graphics
        $gr.PageUnit = [System.Drawing.GraphicsUnit]::Millimeter
        $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $gr.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias
        $gr.TranslateTransform(-$e.PageSettings.HardMarginX * 0.254, -$e.PageSettings.HardMarginY * 0.254)
        switch ($script:page) { 1 { Page1 $gr } 2 { Page2 $gr } 3 { Page3 $gr } 4 { Page4 $gr } }
        $script:page++
        $e.HasMorePages = ($script:page -le 4)
    })
$doc.Print()
$script:bmpParts.Dispose(); $script:bmpModule.Dispose()
Write-Output "送信しました: $($doc.PrinterSettings.PrinterName) $PdfOut"
