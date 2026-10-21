# 빌드된 exe로 실행 시험: --smoke-test 결과(JSON)와 앱 로그를 출력하고, 실패하면 오류로 끝낸다
param(
    [string]$Exe = "dist\YesonCheck_Autocut\YesonCheck_Autocut.exe",
    [string]$Workdir = "C:\yc_smoke",
    [int]$TimeoutSeconds = 1500
)
$ErrorActionPreference = "Stop"
$env:QT_QPA_PLATFORM = "offscreen"
# 워크플로 전체에 PYTHONUTF8=1이 있지만 사용자 PC에는 없음 → exe는 사용자 PC와 같은 조건으로 시험
if (Test-Path Env:PYTHONUTF8) { Remove-Item Env:PYTHONUTF8 }
$p = Start-Process -FilePath $Exe -ArgumentList @("--smoke-test", $Workdir) -PassThru
$timedOut = -not $p.WaitForExit($TimeoutSeconds * 1000)
if ($timedOut) {
    # 대화상자 등에 멈춰 시간 초과된 경우도 결과·로그를 봐야 원인을 알 수 있으므로,
    # 여기서 바로 throw하지 않고 종료시킨 뒤 아래에서 항상 출력하고 맨 끝에서 던진다.
    $p.Kill()
    $p.WaitForExit(10000) | Out-Null  # 로그가 flush될 시간을 잠깐 줌
}
$result = Join-Path $Workdir "smoke_result.json"
if (Test-Path $result) { Get-Content $result -Encoding utf8 | Write-Host } else { Write-Host "smoke_result.json 없음" }
# 앱 기록(yesoncheck_<날짜>_<pid>.log) 중 가장 새 것 — 같은 폴더의 update.log(업데이트 기록)는 아님
$logDir = Join-Path $env:LOCALAPPDATA "YesonCheck\logs"
if (Test-Path $logDir) {
    Get-ChildItem $logDir -Filter yesoncheck_*.log | Sort-Object LastWriteTime | Select-Object -Last 1 |
        ForEach-Object { Write-Host "===== 앱 로그: $($_.FullName)"; Get-Content $_.FullName -Encoding utf8 | Write-Host }
}
if ($timedOut) { throw "실행 시험이 $TimeoutSeconds초 안에 끝나지 않았습니다 (대화상자에서 멈췄을 수 있음)" }
if ($p.ExitCode -ne 0) { throw "실행 시험 실패 (종료 코드 $($p.ExitCode))" }
