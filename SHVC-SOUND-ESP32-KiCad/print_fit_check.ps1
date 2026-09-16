# ESP32版基板の現物合わせ用シートをA4に原寸で印刷する(拡大縮小なし、定規チェック用スケール付き)
#   powershell -ExecutionPolicy Bypass -File print_fit_check.ps1 -Geom geom.json [-Printer "Brother DCP-J1270N Printer"] [-PdfOut out.pdf]
param(
    [Parameter(Mandatory = $true)][string]$Geom,
    [string]$Printer = "",
    [string]$PdfOut = ""
)
Add-Type -AssemblyName System.Drawing
$g = Get-Content -Raw -Encoding UTF8 $Geom | ConvertFrom-Json
$BW = 74.09; $BH = 66.5

$doc = New-Object System.Drawing.Printing.PrintDocument
if ($PdfOut) {
    $doc.PrinterSettings.PrinterName = "Microsoft Print to PDF"
    $doc.PrinterSettings.PrintToFile = $true
    $doc.PrinterSettings.PrintFileName = $PdfOut
} elseif ($Printer) {
    $doc.PrinterSettings.PrinterName = $Printer
}
if (-not $doc.PrinterSettings.IsValid) { throw "プリンターが見つからない: $($doc.PrinterSettings.PrinterName)" }
$a4 = $doc.PrinterSettings.PaperSizes | Where-Object { $_.Kind -eq [System.Drawing.Printing.PaperKind]::A4 } | Select-Object -First 1
if (-not $a4) { throw "A4用紙が選べない" }
$doc.DefaultPageSettings.PaperSize = $a4
$doc.DefaultPageSettings.Landscape = $false
$doc.DefaultPageSettings.Color = $false
$doc.DocumentName = "SHVC-SOUND ESP32 fit check"

$doc.add_PrintPage({
    param($s, $e)
    $gr = $e.Graphics
    $gr.PageUnit = [System.Drawing.GraphicsUnit]::Millimeter
    $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    # 印刷可能領域の左上が原点になるので、用紙の左上を原点に戻す
    $gr.TranslateTransform(-$e.PageSettings.HardMarginX * 0.254, -$e.PageSettings.HardMarginY * 0.254)

    $black = [System.Drawing.Brushes]::Black
    $thin = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.12
    $mid = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.25
    $gray = New-Object System.Drawing.Pen ([System.Drawing.Color]::Gray), 0.12
    $dash = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.2
    $dash.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
    $fT = New-Object System.Drawing.Font "Yu Gothic UI", 4.2, ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Millimeter)
    $fM = New-Object System.Drawing.Font "Yu Gothic UI", 2.8, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Millimeter)
    $fS = New-Object System.Drawing.Font "Yu Gothic UI", 1.8, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Millimeter)
    $fXS = New-Object System.Drawing.Font "Arial", 1.1, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Millimeter)

    $gr.DrawString("SHVC-SOUND ESP32版 基板  現物合わせシート(原寸 1:1)", $fT, $black, 15, 10)
    $gr.DrawString("拡大縮小なしで印刷。下の100mm/150mmスケールを定規で測り、ずれていないか先に確認してください。", $fM, $black, 15, 17)

    function Draw-View($ox, $oy, $mirror, $title, $highlight) {
        $gr.DrawString($title, $fM, $black, $ox, $oy - 11)
        $gr.DrawRectangle($mid, [single]$ox, [single]$oy, [single]$BW, [single]$BH)
        foreach ($c in $g.circles) {
            $cx = if ($mirror) { $BW - $c[0] } else { $c[0] }
            $gr.DrawEllipse($mid, [single]($ox + $cx - $c[2]), [single]($oy + $c[1] - $c[2]), [single](2 * $c[2]), [single](2 * $c[2]))
            $gr.DrawLine($thin, [single]($ox + $cx - 1), [single]($oy + $c[1]), [single]($ox + $cx + 1), [single]($oy + $c[1]))
            $gr.DrawLine($thin, [single]($ox + $cx), [single]($oy + $c[1] - 1), [single]($ox + $cx), [single]($oy + $c[1] + 1))
        }
        foreach ($p in $g.pads) {
            $px = if ($mirror) { $BW - $p.x } else { $p.x }
            $x = $ox + $px; $y = $oy + $p.y
            $hot = $highlight -contains $p.ref
            if ($p.smd) {
                $pw = $p.w; $ph = $p.h
                if ([math]::Abs($p.rot % 180) -gt 45) { $pw = $p.h; $ph = $p.w }
                if ($mirror) { } # 形は左右対称
                if (-not $mirror) { continue }   # SMD(ジャック)は裏面なので裏面図だけ
                $gr.DrawRectangle($gray, [single]($x - $pw / 2), [single]($y - $ph / 2), [single]$pw, [single]$ph)
                continue
            }
            $d = [math]::Max($p.w, $p.h)
            if ($p.ref -like "H*") {
                $gr.DrawEllipse($mid, [single]($x - $d / 2), [single]($y - $d / 2), [single]$d, [single]$d)
                $gr.DrawLine($thin, [single]($x - 1), [single]$y, [single]($x + 1), [single]$y)
                $gr.DrawLine($thin, [single]$x, [single]($y - 1), [single]$x, [single]($y + 1))
                continue
            }
            if ($hot) {
                $gr.FillEllipse($black, [single]($x - $d / 2), [single]($y - $d / 2), [single]$d, [single]$d)
                $gr.FillEllipse([System.Drawing.Brushes]::White, [single]($x - 0.25), [single]($y - 0.25), [single]0.5, [single]0.5)
            } else {
                $gr.DrawEllipse($gray, [single]($x - $d / 2), [single]($y - $d / 2), [single]$d, [single]$d)
            }
        }
    }

    # ---- 左: 表面(モジュールが載る面)
    $ox1 = 18; $oy1 = 45
    Draw-View $ox1 $oy1 $false "表面(SHVC-SOUNDが載る面)  黒丸=J4" @("J4")
    foreach ($p in $g.pads | Where-Object { $_.ref -eq "J4" -and @("1", "2", "23", "24") -contains $_.num }) {
        $dy = if ([int]$p.num % 2 -eq 1) { -2.9 } else { 1.0 }
        $gr.DrawString($p.num, $fXS, $black, [single]($ox1 + $p.x - 0.8), [single]($oy1 + $p.y + $dy))
    }
    $gr.DrawString("モジュールは部品面を下(ピン側)にして", $fS, $black, $ox1, $oy1 + $BH + 2)
    $gr.DrawString("この図の上に重ね、ピンと黒丸・外形・穴を合わせる", $fS, $black, $ox1, $oy1 + $BH + 4.5)

    # ---- 右: 裏面(部品面、左右反転)
    $ox2 = 118; $oy2 = 45
    Draw-View $ox2 $oy2 $true "裏面(部品面・左右反転)  黒丸=ESP32ソケット" @("U1")
    $u1 = $g.pads | Where-Object { $_.ref -eq "U1" -and $_.num -eq "1" }
    $p1x = $BW - $u1.x; $p1y = $u1.y
    # DevKitC本体(54.4 x 27.9mm)の外形 … 裏から見ると部品面が見える向き
    $gr.DrawRectangle($dash, [single]($ox2 + $p1x - 26.85), [single]($oy2 + $p1y - 43.0), [single]28.3, [single]51.5)
    $gr.DrawString("USB", $fS, $black, [single]($ox2 + $p1x - 15.5), [single]($oy2 + $p1y - 42.4))
    $gr.DrawString("ANT", $fS, $black, [single]($ox2 + $p1x - 15.5), [single]($oy2 + $p1y + 5.8))
    # 全ピンにシルクと同じGPIO名を書く(1-15番列は右側、16-30番列は左側に来る)
    foreach ($p in $g.pads | Where-Object { $_.ref -eq "U1" }) {
        $lbl = $p.fn -replace "^IO", "D" -replace "^TX0/IO1$", "TX0" -replace "^RX0/IO3$", "RX0" -replace "^TX2/IO17$", "TX2" -replace "^RX2/IO16$", "RX2" -replace "^IO36$", "VP" -replace "^IO39$", "VN"
        $lbl = $lbl -replace "^D36$", "VP" -replace "^D39$", "VN"
        $px = $ox2 + $BW - $p.x
        if ([int]$p.num -le 15) { $gr.DrawString("$lbl", $fXS, $black, [single]($px + 1.1), [single]($oy2 + $p.y - 0.65)) }
        else { $sz = $gr.MeasureString("$lbl", $fXS); $gr.DrawString("$lbl", $fXS, $black, [single]($px - 1.1 - $sz.Width), [single]($oy2 + $p.y - 0.65)) }
    }    # ---- 電源部品(U7 DC-DC / J3 PDモジュール / D1)の向き確認用の注記
    $red = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 0.35
    $u7 = @{}; foreach ($p in $g.pads | Where-Object { $_.ref -eq "U7" }) { $u7[$p.num] = $p }
    $u7lbl = @{ "1" = "IN"; "2" = "G"; "3" = "OUT" }
    foreach ($n in "1", "2", "3") {
        $p = $u7[$n]; $px = $ox2 + $BW - $p.x; $py = $oy2 + $p.y
        $gr.FillEllipse($black, [single]($px - 0.85), [single]($py - 0.85), [single]1.7, [single]1.7)
        $sz = $gr.MeasureString($u7lbl[$n], $fXS)
        $gr.DrawString($u7lbl[$n], $fXS, $black, [single]($px - $sz.Width / 2), [single]($py + 1.0))
    }
    # 本体(幅11.5mm・厚み約7mm)は基板の内側(上)に倒す想定で描く
    $cx = $ox2 + $BW - $u7["2"].x; $cy = $oy2 + $u7["2"].y
    $gr.DrawRectangle($red, [single]($cx - 5.8), [single]($cy - 6.5), [single]11.6, [single]7.5)
    $gr.DrawString("U7本体(約11.6×7.5)", $fXS, $black, [single]($cx - 5.2), [single]($cy - 5.6))
    $j3 = $g.pads | Where-Object { $_.ref -eq "J3" }
    foreach ($p in $j3) {
        $px = $ox2 + $BW - $p.x; $py = $oy2 + $p.y
        $gr.FillEllipse($black, [single]($px - 0.9), [single]($py - 0.9), [single]1.8, [single]1.8)
        $lbl = if ($p.num -eq "1") { "12V" } else { "GND" }
        $sz = $gr.MeasureString($lbl, $fXS)
        $gr.DrawString($lbl, $fXS, $black, [single]($px - $sz.Width / 2), [single]($py - 2.6))
    }
    $jx = ($j3 | Measure-Object -Property x -Average).Average; $jy = $j3[0].y
    $gr.DrawRectangle($red, [single]($ox2 + $BW - $jx - 5.25), [single]($oy2 + $jy - 4.25), [single]10.5, [single]8.5)
    $d1 = $g.pads | Where-Object { $_.ref -eq "D1" -and $_.num -eq "1" }
    $gr.DrawString("K(帯)", $fXS, $black, [single]($ox2 + $BW - $d1.x - 1.5), [single]($oy2 + $d1.y - 2.6))

    # ---- J1 ステレオジャック PJ-324M(本体14.2×11.5mm、ネジ部φ6×3.5mmが基板の外に出る)
    $j1 = $g.fps | Where-Object { $_.ref -eq "J1" }
    $jl = @{ "1" = "1:GND"; "2" = "2:R"; "3" = "3:Rsw"; "4" = "4:L"; "5" = "5:Lsw" }
    foreach ($p in $g.pads | Where-Object { $_.ref -eq "J1" }) {
        $px = $ox2 + $BW - $p.x; $py = $oy2 + $p.y
        $gr.FillEllipse($black, [single]($px - 0.8), [single]($py - 0.8), [single]1.6, [single]1.6)
        $gr.DrawString($jl[$p.num], $fXS, $black, [single]($px + 1.0), [single]($py - 0.6))
    }
    # 基板座標(表から見た図): 本体 x=原点-6.81〜+7.39, y=原点-5.65〜+5.85 / ネジ部 x=+7.39〜+10.9, y=-2.65〜+3.35
    $bx = $ox2 + $BW - ($j1.x + 7.39); $by = $oy2 + $j1.y - 5.65
    $gr.DrawRectangle($red, [single]$bx, [single]$by, [single]14.2, [single]11.5)
    $gr.DrawRectangle($red, [single]($bx - 3.51), [single]($oy2 + $j1.y - 2.65), [single]3.51, [single]6.0)
    $gr.DrawString("J1", $fXS, $black, [single]($bx + 6.0), [single]($by + 9.8))    # 注記(裏面図の下)
    $ny = $oy2 + $BH + 8
    $gr.DrawString("■ 電源部品の向き(この裏面図の上に部品を置いて決める)", $fS, $black, $ox2, $ny)
    $gr.DrawString("U7 DC-DC(7805互換): 黒丸=足。IN(12V)・G・OUT(5V)の並びを部品の刻印と合わせる。", $fS, $black, $ox2, $ny + 2.6)
    $gr.DrawString("　太枠=本体の置き場所(内側=ESP32側)。穴側はネジ頭に当たる。", $fS, $black, $ox2, $ny + 5.0)
    $gr.DrawString("J3 PDモジュール: 黒丸4つ=12V,12V,GND,GND。太枠=10.5×8.5mm。", $fS, $black, $ox2, $ny + 7.4)
    $gr.DrawString("　USB-C口が基板の下辺(外側)を向き、12V/GNDの並びが合う表裏を選ぶ。", $fS, $black, $ox2, $ny + 9.8)
    $gr.DrawString("D1 1N5819: 帯(K)側を「K(帯)」と書いた穴へ(この図では左)。", $fS, $black, $ox2, $ny + 12.2)
    $gr.DrawString("J1 PJ-324M: 太枠=本体とネジ部(左辺から3.5mm外へ出る)。1=GND 4=L 2=R(推定)", $fS, $black, $ox2, $ny + 14.6)
    $gr.DrawString("ESP32は部品面を上にして置き、ピン列を黒丸に合わせる", $fS, $black, $ox2, $oy2 + $BH + 2)
    $gr.DrawString("(DevKit V1 30ピン、破線=本体の想定外形、列間25.4mm)", $fS, $black, $ox2, $oy2 + $BH + 4.5)

    # ---- スケール(横150mm / 縦100mm)
    function Ruler-H($x0, $y0, $len) {
        $gr.DrawLine($mid, [single]$x0, [single]$y0, [single]($x0 + $len), [single]$y0)
        for ($i = 0; $i -le $len; $i++) {
            $t = if ($i % 10 -eq 0) { 4 } elseif ($i % 5 -eq 0) { 2.5 } else { 1.5 }
            $gr.DrawLine($thin, [single]($x0 + $i), [single]$y0, [single]($x0 + $i), [single]($y0 + $t))
            if ($i % 10 -eq 0) { $gr.DrawString("$i", $fXS, $black, [single]($x0 + $i - 0.7), [single]($y0 + 4.3)) }
        }
    }
    function Ruler-V($x0, $y0, $len) {
        $gr.DrawLine($mid, [single]$x0, [single]$y0, [single]$x0, [single]($y0 + $len))
        for ($i = 0; $i -le $len; $i++) {
            $t = if ($i % 10 -eq 0) { 4 } elseif ($i % 5 -eq 0) { 2.5 } else { 1.5 }
            $gr.DrawLine($thin, [single]$x0, [single]($y0 + $i), [single]($x0 + $t), [single]($y0 + $i))
            if ($i % 10 -eq 0) { $gr.DrawString("$i", $fXS, $black, [single]($x0 + 4.4), [single]($y0 + $i - 0.6)) }
        }
    }
    $gr.DrawString("横スケール 150mm(0と150の線の間を定規で測る)", $fS, $black, 30, 137)
    Ruler-H 30 141 150
    $gr.DrawString("縦スケール 100mm", $fS, $black, 30, 157)
    Ruler-V 30 162 100
    # 100mm 四角(縦横どちらの縮みも見る)
    $gr.DrawRectangle($mid, [single]80, [single]162, [single]100, [single]100)
    $gr.DrawLine($thin, [single]130, [single]162, [single]130, [single]262)
    $gr.DrawLine($thin, [single]80, [single]212, [single]180, [single]212)
    $gr.DrawString("100mm × 100mm の正方形", $fS, $black, 105, 205)
    $gr.DrawString("J4ピッチ 2.0mm / 列間 2.5mm、ESP32ピッチ 2.54mm", $fS, $black, 95, 218)

    $gr.DrawString("基板 74.09 × 66.5mm / 外形・コネクタ位置は OpenSFC TCMK-77XR のデータから推定", $fS, $black, 15, 272)
    $gr.DrawString("紙は湿気や印刷で0.3%程度伸縮します。100mmが99.7〜100.3mmなら十分です。", $fS, $black, 15, 276)
    $e.HasMorePages = $false
})
$doc.Print()
Write-Output "送信しました: $($doc.PrinterSettings.PrinterName) $PdfOut"
