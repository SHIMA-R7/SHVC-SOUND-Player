# ロゴ画像(白地に黒)を、シルク用の白黒グリッド(1マス=Cell mm)に変換する
#   powershell -ExecutionPolicy Bypass -File make_logo_grid.ps1 -Image logo.png -WidthMm 54 -Cell 0.1 -Out logo_grid.txt
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [double]$WidthMm = 54,
    [double]$Cell = 0.1,
    [Parameter(Mandatory = $true)][string]$Out
)
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Bitmap]::FromFile((Resolve-Path $Image))

function Gray($bmp, $x, $y) { $c = $bmp.GetPixel($x, $y); ($c.R + $c.G + $c.B) / 3 }

# 1) 縮小版で黒い部分の外接矩形を求める
$k = 4
$small = New-Object System.Drawing.Bitmap ([int]($src.Width / $k)), ([int]($src.Height / $k))
$gs = [System.Drawing.Graphics]::FromImage($small)
$gs.InterpolationMode = 'HighQualityBilinear'
$gs.DrawImage($src, 0, 0, $small.Width, $small.Height)
$minx = $small.Width; $miny = $small.Height; $maxx = 0; $maxy = 0
for ($y = 0; $y -lt $small.Height; $y++) {
    for ($x = 0; $x -lt $small.Width; $x++) {
        if ((Gray $small $x $y) -lt 128) {
            if ($x -lt $minx) { $minx = $x }; if ($x -gt $maxx) { $maxx = $x }
            if ($y -lt $miny) { $miny = $y }; if ($y -gt $maxy) { $maxy = $y }
        }
    }
}
$crop = New-Object System.Drawing.Rectangle (($minx - 1) * $k), (($miny - 1) * $k), (($maxx - $minx + 3) * $k), (($maxy - $miny + 3) * $k)

# 2) 切り抜いた範囲をグリッドの大きさに縮小して二値化
$cols = [int][math]::Round($WidthMm / $Cell)
$rows = [int][math]::Round($cols * $crop.Height / $crop.Width)
$grid = New-Object System.Drawing.Bitmap $cols, $rows
$gg = [System.Drawing.Graphics]::FromImage($grid)
$gg.InterpolationMode = 'HighQualityBicubic'
$gg.PixelOffsetMode = 'HighQuality'
$gg.Clear([System.Drawing.Color]::White)
$gg.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $cols, $rows), $crop, [System.Drawing.GraphicsUnit]::Pixel)
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# cell_mm=$Cell cols=$cols rows=$rows width_mm=$WidthMm")
for ($y = 0; $y -lt $rows; $y++) {
    $sb = New-Object System.Text.StringBuilder $cols
    for ($x = 0; $x -lt $cols; $x++) { [void]$sb.Append($(if ((Gray $grid $x $y) -lt 128) { '1' } else { '0' })) }
    $lines.Add($sb.ToString())
}
[IO.File]::WriteAllLines($Out, $lines)
"グリッド $cols x $rows ($WidthMm x $([math]::Round($rows * $Cell, 1)) mm) -> $Out"
