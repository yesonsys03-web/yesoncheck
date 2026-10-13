# 번들용 정적 ffmpeg/ffprobe 내려받기 (Windows, vendor\ffmpeg\windows)
# 바이너리는 크기 때문에 git에 넣지 않음 → clone한 뒤 빌드 전에 한 번 실행 (PowerShell)
# 출처: gyan.dev FFmpeg 9.0.2 essentials (GPL, libx264 포함), GitHub GyanD/codexffmpeg 릴리스 9.0.2
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # 진행 표시가 있으면 Invoke-WebRequest가 매우 느림
$Version = "9.0.2"
$Url = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/ffmpeg-$Version-essentials_build.zip"
$ZipSha256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
$Inner = "ffmpeg-$Version-essentials_build\bin"
$Tools = @{ "ffmpeg.exe" = "3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec"; "ffprobe.exe" = "f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52" }
$Dest = Join-Path $PSScriptRoot "vendor\ffmpeg\windows"

function Test-Tools {
    foreach ($name in $Tools.Keys) {
        $path = Join-Path $Dest $name
        if (-not (Test-Path $path)) { return $false }
        if ((Get-FileHash $path -Algorithm SHA256).Hash.ToLower() -ne $Tools[$name]) { return $false }
    }
    return $true
}

if (Test-Tools) { Write-Host "있음: $Dest"; exit 0 }
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("yc_ffmpeg_" + [guid]::NewGuid())
New-Item -ItemType Directory $Tmp | Out-Null
try {
    $Zip = Join-Path $Tmp "ffmpeg.zip"
    Write-Host "받는 중: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    $Got = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
    if ($Got -ne $ZipSha256) { throw "zip sha256 불일치: 기대 $ZipSha256, 실제 $Got" }
    Expand-Archive $Zip -DestinationPath $Tmp
    New-Item -ItemType Directory -Force $Dest | Out-Null
    foreach ($name in $Tools.Keys) { Copy-Item (Join-Path $Tmp "$Inner\$name") (Join-Path $Dest $name) -Force }
    if (-not (Test-Tools)) { throw "압축을 푼 exe의 sha256이 기록과 다릅니다" }
    Write-Host "완료: $Dest"
} finally {
    Remove-Item -Recurse -Force $Tmp
}
