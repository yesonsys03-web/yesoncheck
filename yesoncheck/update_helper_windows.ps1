# YesonCheck Windows 업데이트 도우미 — 앱이 끝난 뒤 설치 폴더를 백업 이름으로 바꾸고 새 버전을 조용히 설치하며,
# 새 앱이 잘 켜지지 않으면 되돌린다.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File update_helper_windows.ps1
#       -AppPid PID -InstallDir DIR -Installer EXE -Target VER -OkFile OK -Log LOG [-TimeoutSeconds S] [-ExeName NAME]
#
# 앱(update_install.launch_helper_windows)이 이 파일을 업데이트 상태 폴더로 복사해 콘솔 없이 띄운 뒤 끝난다.
# 순서:
#   1. PID가 끝나기를 기다림(300초 — 넘으면 아무것도 바꾸지 않음). pid는 끝난 뒤 다른 프로세스에 다시 쓰일 수 있으므로
#      그 pid의 실행 파일이 DIR\ExeName일 때만 기다린다.
#   2. 지난번에 남은 DIR.update-backup을 지움(못 지우면 설치하지 않음).
#   3. DIR을 DIR.update-backup으로 이름만 바꿈(약 1 GB를 복사하지 않음). 안의 파일이 잡혀 있어 못 바꾸면 — 다른
#      YesonCheck 창이 켜져 있거나 백신 등이 파일을 잡고 있음 — 설치하지 않고 옛 앱을 다시 켬.
#   4. 설치 파일을 /VERYSILENT로 DIR에 설치(설치 파일 자체 기록은 LOG.inno.txt). 종료 코드 ≠ 0이면 되돌림.
#   5. OK를 지우고 DIR\ExeName을 켬(환경 변수는 이 도우미의 것 그대로, 작업 폴더는 DIR — 바로 가기와 같음).
#   6. 새 앱이 창을 보인 뒤 쓰는 OK({"version": "VER"})를 -TimeoutSeconds초까지 기다림 → 되면 백업과 OK를 지움.
# 중간에 실패하거나, 새 앱이 표시 없이 끝나거나, 시간이 지나면 되돌림: 새 앱 프로세스(실행 파일이 DIR 아래인 것 —
# 이름으로는 찾지 않음)를 끝내고, 반쯤 깔린 DIR을 옆 이름으로 치운 뒤 백업을 DIR로 되돌리고, 치운 것을 지운 다음 옛
# 앱을 켠다. DIR에 앱이 없는 채로 끝내지 않는다 — 되돌리기마저 실패하면 두 오류를 모두 기록하고 종료 코드 2.
#
# 종료 코드: 0 업데이트 성공, 1 바꾸지 않았거나 되돌림(옛 앱을 켬), 2 되돌리기 실패 또는 잘못된 인자.
#
# 모든 단계와 실패를 LOG에 "YYYY-MM-DDTHH:MM:SS 도우미: 내용" 한 줄씩 UTF-8로 덧붙인다 — update_install.log()와 같은
# 형식이라 다시 켜진 앱이 log_tail_since로 이 줄들을 "업데이트 실패" 창에 보여 준다(시각 없이 이어지는 줄은 앞줄을 따름).
# Windows PowerShell 5.1에서 돈다 — 이 파일은 UTF-8 BOM으로 저장한다(BOM이 없으면 5.1이 한글을 ANSI로 읽음).
# $ErrorActionPreference = 'Stop'이고, 단계마다 try/catch로 직접 처리해 되돌리기가 반드시 돈다.
#
# 환경 변수 (주로 시험용):
#   YC_UPDATE_OK_TIMEOUT_S   -TimeoutSeconds의 기본값 (없으면 180초)
#   YC_UPDATE_PID_TIMEOUT_S  앱이 끝나기를 기다리는 시간 (없으면 300초)

param(
    [string]$AppPid = '',
    [string]$InstallDir = '',
    [string]$Installer = '',
    [string]$Target = '',
    [string]$OkFile = '',
    [string]$Log = '',
    [string]$TimeoutSeconds = '',
    [string]$ExeName = 'YesonCheck_Autocut.exe'
)

$ErrorActionPreference = 'Stop'
$ExtraArgs = @($args)  # 모르는 인자 — 함수 안에서 $args를 쓰면 그 함수의 인자이므로 여기서 받아 둠
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$RetryCount = 5  # 이름 바꾸기·지우기: 잠깐 잡힌 파일(백신 검사 등) 때문이면 1초 간격으로 다시 해 봄

$script:FailReason = ''
$script:OkReadError = ''   # 마지막으로 OK를 읽지 못한 이유 (실패 기록용)
$script:AppGone = $false   # 앱(PID)이 끝났음 — 그 전에는 옛 앱을 다시 켜지 않음(아직 켜져 있을 수 있음)
$script:Renamed = $false   # DIR을 백업 이름으로 바꿨음 — 그 뒤로 실패하면 백업을 되돌려야 함
$script:Launched = $false  # 새 앱을 켜려고 했음 — 되돌릴 때 DIR 아래 프로세스를 끝내야 함
$script:NewProc = $null    # 켠 새 앱 프로세스

# ---- 기록 ----

function Write-Log([string]$Message) {
    # update_install.timestamp()와 같은 형식 (지역 설정과 상관없이 - 와 : 를 그대로)
    $stamp = [DateTime]::Now.ToString("yyyy-MM-dd'T'HH':'mm':'ss", [System.Globalization.CultureInfo]::InvariantCulture)
    $line = $stamp + ' 도우미: ' + $Message
    [Console]::Out.WriteLine($line)
    if (-not $Log) { return }
    # UTF-8(BOM 없이)로 직접 덧붙임 — 5.1의 Add-Content·Out-File은 ANSI·UTF-16이 기본. 앱의 log()(파이썬)와 같은 파일을
    # 함께 쓰므로 FileShare.ReadWrite로 열고, 그래도 잠깐 막히면 몇 번 다시 해 봄. 끝내 못 쓰면 stderr에 남기고 계속한다
    # (기록을 못 했다고 되돌리기를 멈추면 안 됨)
    $bytes = $Utf8NoBom.GetBytes($line + "`r`n")
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            $fs = New-Object System.IO.FileStream($Log, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
            try { $fs.Write($bytes, 0, $bytes.Length) } finally { $fs.Dispose() }
            return
        } catch {
            if ($attempt -ge $RetryCount) {
                [Console]::Error.WriteLine('로그에 쓰지 못함 (' + $Log + '): ' + $_.Exception.Message + ' — ' + $line)
                return
            }
            Start-Sleep -Milliseconds 200
        }
    }
}

function Format-Err($Record) {
    # catch의 $_ → "예외 종류: 메시지". .NET 메서드 호출의 예외는 PowerShell이 감싸므로 안쪽 것을 적음
    $ex = $Record.Exception
    while (($ex -is [System.Management.Automation.MethodInvocationException]) -and ($null -ne $ex.InnerException)) {
        $ex = $ex.InnerException
    }
    return $ex.GetType().FullName + ': ' + $ex.Message
}

function Exit-Usage([string]$Why) {
    Write-Log ('잘못된 인자: ' + $Why)
    [Console]::Error.WriteLine('사용법: powershell -File update_helper_windows.ps1 -AppPid PID -InstallDir DIR -Installer EXE -Target VER -OkFile OK -Log LOG [-TimeoutSeconds S] [-ExeName NAME]')
    exit 2
}

# ---- 파일 ----

function Test-Exists([string]$Path) {
    return ([System.IO.Directory]::Exists($Path) -or [System.IO.File]::Exists($Path))
}

function Move-Dir([string]$From, [string]$To) {
    # 폴더 이름 바꾸기 (같은 드라이브 — 복사하지 않음). 안의 파일이 잡혀 있으면 실패하므로 몇 번 다시 해 보고,
    # 끝내 안 되면 마지막 오류를 그대로 올림
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            [System.IO.Directory]::Move($From, $To)
            return
        } catch {
            if ($attempt -ge $RetryCount) { throw }
            Start-Sleep -Seconds 1
        }
    }
}

function Remove-Dir([string]$Path) {
    # 폴더(또는 파일)를 통째로 지움. 지운 뒤 남아 있으면 실패 — 몇 번 다시 해 보고, 끝내 안 되면 마지막 오류를 올림
    $attempt = 0
    while ($true) {
        $attempt++
        if (-not (Test-Exists $Path)) { return }
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            if (-not (Test-Exists $Path)) { return }
            throw ('지운 뒤에도 남아 있음: ' + $Path)
        } catch {
            if ($attempt -ge $RetryCount) { throw }
            Start-Sleep -Seconds 1
        }
    }
}

function Get-UnusedName([string]$Base) {
    $name = $Base
    $n = 0
    while (Test-Exists $name) {
        $n++
        $name = $Base + '-' + $n
    }
    return $name
}

# ---- 프로세스 ----

function Wait-AppExit {
    # $true: 앱이 끝남(또는 그 pid가 이 앱이 아님), $false: PidTimeoutS초 안에 끝나지 않음
    try {
        $proc = [System.Diagnostics.Process]::GetProcessById($AppPidNum)
    } catch {
        Write-Log ("앱(pid $AppPidNum)은 이미 끝나 있음 (" + (Format-Err $_) + ')')
        return $true
    }
    # 핸들을 먼저 잡아 두면 기다리는 동안 pid가 다른 프로세스로 바뀌지 않음
    try {
        $null = $proc.Handle
        $path = $proc.MainModule.FileName
    } catch {
        Write-Log ("pid $AppPidNum 의 실행 파일을 알 수 없어(끝나는 중이거나 다른 사용자의 프로세스) 앱은 끝난 것으로 봄: " + (Format-Err $_))
        return $true
    }
    if ([System.IO.Path]::GetFullPath($path) -ine $ExePath) {
        Write-Log "pid $AppPidNum 는 이 앱이 아님 ($path) — 앱은 이미 끝난 것으로 봄"
        return $true
    }
    Write-Log "앱이 끝나기를 기다림 (pid $AppPidNum, 최대 $($PidTimeoutS)초)"
    return $proc.WaitForExit($PidTimeoutS * 1000)
}

function Start-App([string]$What) {
    # DIR\ExeName을 켬 — 환경 변수는 이 도우미의 것 그대로, 작업 폴더는 DIR(바로 가기와 같음). 돌려줌: 프로세스
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.WorkingDirectory = $InstallDir
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    Write-Log "$($What)을 켬 (pid $($p.Id)): $ExePath"
    return $p
}

function Stop-NewApp {
    # 켠 새 앱과, 실행 파일이 DIR 아래인 프로세스(새 앱이 띄운 ffmpeg 등)를 모두 끝냄. 이름으로는 찾지 않는다 —
    # 다른 곳에 깔린 같은 이름의 앱은 건드리지 않음
    $prefix = $InstallDir + '\'
    $targets = New-Object System.Collections.ArrayList
    if (($null -ne $script:NewProc) -and (-not $script:NewProc.HasExited)) { $null = $targets.Add($script:NewProc) }
    foreach ($p in [System.Diagnostics.Process]::GetProcesses()) {
        if (($null -ne $script:NewProc) -and ($p.Id -eq $script:NewProc.Id)) { continue }
        $path = $null
        try { $path = $p.MainModule.FileName } catch { $path = $null }  # 시스템·다른 사용자 프로세스는 경로를 읽을 수 없음 — 우리 앱이 아님
        if ($path -and $path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { $null = $targets.Add($p) }
    }
    if ($targets.Count -eq 0) {
        Write-Log '새 앱 프로세스는 이미 끝나 있음'
        return
    }
    Write-Log ('새 앱 프로세스를 끝냄: pid ' + (($targets | ForEach-Object { $_.Id }) -join ' '))
    foreach ($p in $targets) {
        try { $p.Kill() } catch { Write-Log ("프로세스(pid $($p.Id))를 끝내지 못함: " + (Format-Err $_)) }
    }
    foreach ($p in $targets) {
        try {
            if (-not $p.WaitForExit(10000)) { Write-Log "프로세스(pid $($p.Id))가 10초 안에 끝나지 않음" }
        } catch {
            Write-Log ("프로세스(pid $($p.Id))가 끝나기를 기다리지 못함: " + (Format-Err $_))
        }
    }
}

function Invoke-Installer {
    # 설치 파일을 조용히 실행하고 끝나기를 기다림 → 종료 코드 (windows-build.yml의 설치 시험과 같은 인자)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Installer
    $psi.Arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $InstallDir + '" /LOG="' + $InnoLog + '"'
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.WaitForExit()
    return $proc.ExitCode
}

function Write-InnoLogTail {
    # 설치 파일 자체 기록의 끝 20줄을 로그에 붙임 ("업데이트 실패" 창에서 바로 보이게 — 시각 없는 줄은 앞줄을 따름)
    if (-not [System.IO.File]::Exists($InnoLog)) {
        Write-Log ('설치 파일 기록이 없음: ' + $InnoLog)
        return
    }
    try {
        $lines = [System.IO.File]::ReadAllLines($InnoLog)
    } catch {
        Write-Log ('설치 파일 기록을 읽지 못함: ' + $InnoLog + ' (' + (Format-Err $_) + ')')
        return
    }
    $tail = @($lines | Select-Object -Last 20)
    $body = ($tail | ForEach-Object { '    ' + $_ }) -join "`r`n"
    Write-Log ('설치 파일 기록의 끝 ' + $tail.Count + '줄 (' + $InnoLog + "):`r`n" + $body)
}

# ---- '잘 켜짐' 표시 ----

function Read-OkVersion {
    # OK의 "version" 값. 없거나 못 읽으면 $null (못 읽은 이유는 $script:OkReadError).
    # 새 앱은 임시 파일 + 이름 바꾸기로 한 번만 쓰므로 파일이 보이면 다 쓴 것 — 있을 때만 연다
    # (늘 열어 보면 그 순간 앱의 이름 바꾸기가 막힐 수 있음)
    if (-not [System.IO.File]::Exists($OkFile)) { return $null }
    try {
        $text = [System.IO.File]::ReadAllText($OkFile, $Utf8NoBom)
    } catch {
        $script:OkReadError = Format-Err $_
        return $null
    }
    $m = [regex]::Match($text, '"version"\s*:\s*"([^"]*)"')
    if ($m.Success) { return $m.Groups[1].Value }
    $script:OkReadError = '형식이 다름: ' + $text
    return $null
}

function Get-OkSummary($Version) {
    if ($Version) { return ('버전 ' + $Version) }
    if ($script:OkReadError) { return ('읽지 못함 — ' + $script:OkReadError) }
    return '없음'
}

function Wait-OkMarker {
    # $true: 잘 켜짐, $false: 실패 (이유는 $script:FailReason)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Log "새 앱의 '잘 켜짐' 표시를 기다림 (최대 $($TimeoutS)초): $OkFile"
    while ($true) {
        $version = Read-OkVersion
        if ($version -eq $Target) { return $true }
        if ($script:NewProc.HasExited) {
            $version = Read-OkVersion  # 표시를 쓰고 바로 끝났을 수 있음
            if ($version -eq $Target) { return $true }
            $script:FailReason = "새 앱이 '잘 켜짐' 표시 없이 끝남 (종료 코드 $($script:NewProc.ExitCode), 표시: " + (Get-OkSummary $version) + ')'
            return $false
        }
        if ($sw.Elapsed.TotalSeconds -ge $TimeoutS) {
            $script:FailReason = "$($TimeoutS)초 안에 '잘 켜짐' 표시가 없음 (표시: " + (Get-OkSummary $version) + ')'
            return $false
        }
        Start-Sleep -Milliseconds 500
    }
}

# ---- 되돌리기 ----

function Restore-Backup {
    # 반쯤 깔린 DIR을 옆 이름으로 치우고(이름 바꾸기 — 지우다 일부만 지워져도 막히지 않게) 백업을 DIR로 되돌린 뒤 치운
    # 것을 지움. $true: 되돌림, $false: 되돌리지 못함 (이유는 기록)
    $failed = $null
    if (Test-Exists $InstallDir) {
        # 치울 이름은 이번 실행만의 것 (지난번에 못 지운 것이 남아 있어도 막히지 않게)
        $failed = Get-UnusedName ($InstallDir + '.update-failed-' + $PID)
        try {
            Move-Dir $InstallDir $failed
        } catch {
            Write-Log ('되돌리기 실패 — 반쯤 깔린 설치 폴더를 치우지 못함 (' + $InstallDir + ' → ' + $failed + '): ' + (Format-Err $_))
            return $false
        }
        Write-Log "반쯤 깔린 설치 폴더를 치움: $InstallDir → $failed"
    }
    try {
        Move-Dir $Backup $InstallDir
    } catch {
        Write-Log ('되돌리기 실패 — 백업을 제자리로 옮기지 못함 (' + $Backup + ' → ' + $InstallDir + '): ' + (Format-Err $_))
        if ($failed) { Write-Log "치운 새 버전: $failed" }
        return $false
    }
    Write-Log "백업을 제자리로 되돌림: $Backup → $InstallDir"
    if ($failed) {
        try {
            Remove-Dir $failed
            Write-Log "치운 새 버전을 지움: $failed"
        } catch {
            Write-Log ('치운 새 버전을 지우지 못함: ' + $failed + ' (' + (Format-Err $_) + ')')
        }
    }
    return $true
}

function Exit-Rollback {
    # $script:FailReason을 기록하고, 바꾼 것을 되돌린 뒤 옛 앱을 켜고 끝냄(1). 되돌리기가 실패하면 2
    Write-Log ('업데이트 실패: ' + $script:FailReason)
    if (-not $script:AppGone) {
        Write-Log '앱이 끝나기 전이라 아무것도 바꾸지 않음'
        exit 1
    }
    Write-Log '되돌림 시작'
    if ($script:Launched) {
        try { Stop-NewApp } catch { Write-Log ('새 앱 프로세스를 끝내다 오류: ' + (Format-Err $_)) }
    }
    $restored = $false
    try {
        if ($script:Renamed) {
            $restored = Restore-Backup
        } else {
            Write-Log "설치 폴더는 바뀌지 않았음: $InstallDir"
            $restored = $true
        }
        if ($restored -and (-not [System.IO.File]::Exists($ExePath))) {
            Write-Log "되돌리기 실패 — 설치 폴더에 옛 앱이 없음: $ExePath"
            $restored = $false
        }
    } catch {
        Write-Log ('되돌리기 실패 — 예상 못 한 오류: ' + (Format-Err $_) + "`r`n" + $_.ScriptStackTrace)
        $restored = $false
    }
    if (-not $restored) {
        Write-Log ('되돌리기 실패 — 처음 실패: ' + $script:FailReason)
        Write-Log "되돌리기 실패 — 옛 앱 백업: $Backup, 설치 폴더: $InstallDir (백업 폴더 이름을 설치 폴더 이름으로 손으로 바꿔 주세요)"
        exit 2
    }
    Write-Log '되돌림: 옛 앱을 다시 켬'
    try { $null = Start-App '옛 앱' } catch { Write-Log ('옛 앱을 켜지 못함: ' + (Format-Err $_)) }
    exit 1
}

# ---- 인자 확인 ----

if ($ExtraArgs.Count -gt 0) { Exit-Usage ('알 수 없는 인자: ' + ($ExtraArgs -join ' ')) }
$required = [ordered]@{
    '-AppPid' = $AppPid; '-InstallDir' = $InstallDir; '-Installer' = $Installer; '-Target' = $Target
    '-OkFile' = $OkFile; '-Log' = $Log; '-ExeName' = $ExeName
}
foreach ($name in $required.Keys) {
    if (-not $required[$name]) { Exit-Usage ($name + ' 값이 없음') }
}
if (-not $TimeoutSeconds) { $TimeoutSeconds = $env:YC_UPDATE_OK_TIMEOUT_S }
if (-not $TimeoutSeconds) { $TimeoutSeconds = '180' }
$PidTimeoutText = $env:YC_UPDATE_PID_TIMEOUT_S
if (-not $PidTimeoutText) { $PidTimeoutText = '300' }
$numbers = [ordered]@{ '-AppPid' = $AppPid; '-TimeoutSeconds(YC_UPDATE_OK_TIMEOUT_S)' = $TimeoutSeconds; 'YC_UPDATE_PID_TIMEOUT_S' = $PidTimeoutText }
foreach ($name in $numbers.Keys) {
    if ($numbers[$name] -notmatch '^[0-9]{1,9}$') { Exit-Usage ($name + ' 값은 숫자여야 함: ' + $numbers[$name]) }
}
$AppPidNum = [int]$AppPid
$TimeoutS = [int]$TimeoutSeconds
$PidTimeoutS = [int]$PidTimeoutText
if ($PidTimeoutS -gt 86400) { Exit-Usage ('YC_UPDATE_PID_TIMEOUT_S 값이 너무 큼: ' + $PidTimeoutS) }
$paths = [ordered]@{ '-InstallDir' = $InstallDir; '-Installer' = $Installer; '-OkFile' = $OkFile; '-Log' = $Log }
foreach ($name in $paths.Keys) {
    if ($paths[$name] -notmatch '^(?:[A-Za-z]:\\|\\\\)') { Exit-Usage ($name + ' 값은 전체 경로여야 함: ' + $paths[$name]) }
}
if ($ExeName -match '[\\/:]') { Exit-Usage ('-ExeName 값은 파일 이름이어야 함: ' + $ExeName) }
try {
    $InstallDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
} catch {
    Exit-Usage ('-InstallDir 값을 경로로 읽지 못함: ' + $InstallDir + ' (' + (Format-Err $_) + ')')
}
if (-not [System.IO.Path]::GetDirectoryName($InstallDir)) { Exit-Usage ('-InstallDir 값이 드라이브 맨 위임: ' + $InstallDir) }

$ExePath = [System.IO.Path]::Combine($InstallDir, $ExeName)
$Backup = $InstallDir + '.update-backup'
$InnoLog = $Log + '.inno.txt'

try {
    $null = [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($Log))
} catch {
    [Console]::Error.WriteLine('로그 폴더를 만들지 못함: ' + $Log + ' (' + (Format-Err $_) + ')')
}
# 이 도우미의 작업 폴더가 DIR(또는 그 아래)이면 그 폴더 핸들 때문에 DIR의 이름을 바꿀 수 없음 — 이 스크립트 폴더로 옮김
try {
    [System.IO.Directory]::SetCurrentDirectory($PSScriptRoot)
} catch {
    Write-Log ('작업 폴더를 이 스크립트 폴더로 바꾸지 못함: ' + $PSScriptRoot + ' (' + (Format-Err $_) + ')')
}

# ---- 업데이트 ----

Write-Log "시작: 대상 버전 $Target, 설치 폴더 $InstallDir, 설치 파일 $Installer"
try {
    # 1. 앱이 끝나기를 기다림
    $exited = $false
    try {
        $exited = Wait-AppExit
    } catch {
        Write-Log ("업데이트 실패 — 앱(pid $AppPidNum)이 끝나기를 기다리지 못해 아무것도 바꾸지 않음: " + (Format-Err $_))
        exit 1
    }
    if (-not $exited) {
        Write-Log "앱(pid $AppPidNum)이 $($PidTimeoutS)초가 지나도 끝나지 않아 아무것도 바꾸지 않음"
        exit 1
    }
    $script:AppGone = $true
    Write-Log "앱이 끝남 (pid $AppPidNum)"

    # 2. 지금 앱과 설치 파일
    if (-not [System.IO.File]::Exists($ExePath)) {
        Write-Log "업데이트 실패 — 설치 폴더에 지금 앱이 없음: $ExePath"
        exit 2
    }
    if (-not [System.IO.File]::Exists($Installer)) {
        $script:FailReason = "설치 파일이 없음: $Installer"
        Exit-Rollback
    }

    # 3. 지난 업데이트의 백업 (남아 있으면 이름 바꾸기가 실패함)
    if (Test-Exists $Backup) {
        Write-Log "지난 업데이트의 백업이 남아 있어 먼저 지움: $Backup"
        try {
            Remove-Dir $Backup
        } catch {
            $script:FailReason = '지난 업데이트의 백업을 지우지 못함: ' + $Backup + ' (' + (Format-Err $_) + ')'
            Exit-Rollback
        }
    }

    # 4. 설치 폴더를 백업 이름으로
    try {
        Move-Dir $InstallDir $Backup
    } catch {
        $script:FailReason = '설치 폴더의 이름을 바꾸지 못함 — 다른 YesonCheck 창이 켜져 있거나 파일이 잡혀 있음 (' + $InstallDir + ' → ' + $Backup + '): ' + (Format-Err $_)
        Exit-Rollback
    }
    $script:Renamed = $true
    Write-Log "설치 폴더를 백업 이름으로 바꿈: $InstallDir → $Backup"

    # 5. 조용히 설치
    Write-Log "설치 파일을 조용히 실행: $Installer (설치 파일 기록: $InnoLog)"
    $code = $null
    try {
        $code = Invoke-Installer
    } catch {
        $script:FailReason = '설치 파일을 실행하지 못함: ' + $Installer + ' (' + (Format-Err $_) + ')'
        Exit-Rollback
    }
    if ($code -ne 0) {
        $script:FailReason = "설치 파일이 실패함 (종료 코드 $code, 설치 파일 기록: $InnoLog)"
        Write-InnoLogTail
        Exit-Rollback
    }
    Write-Log '설치 파일이 끝남 (종료 코드 0)'

    # 6. 지난 표시를 지우고 새 앱을 켬
    try {
        if ([System.IO.File]::Exists($OkFile)) { [System.IO.File]::Delete($OkFile) }
    } catch {
        $script:FailReason = "지난 '잘 켜짐' 표시를 지우지 못함: " + $OkFile + ' (' + (Format-Err $_) + ')'
        Exit-Rollback
    }
    $script:Launched = $true
    try {
        $script:NewProc = Start-App '새 앱'
    } catch {
        $script:FailReason = '새 앱을 켜지 못함: ' + $ExePath + ' (' + (Format-Err $_) + ')'
        Exit-Rollback
    }

    # 7. 새 앱의 '잘 켜짐' 표시
    if (-not (Wait-OkMarker)) { Exit-Rollback }
    Write-Log "새 앱이 잘 켜짐 (버전 $Target)"

    # 8. 정리 (실패해도 업데이트는 성공 — 남은 백업은 다음 업데이트가 먼저 지움)
    try {
        Remove-Dir $Backup
        Write-Log "백업을 지움: $Backup"
    } catch {
        Write-Log ('백업을 지우지 못함: ' + $Backup + ' (' + (Format-Err $_) + ')')
    }
    try {
        if ([System.IO.File]::Exists($OkFile)) { [System.IO.File]::Delete($OkFile) }
    } catch {
        Write-Log ("'잘 켜짐' 표시를 지우지 못함: " + $OkFile + ' (' + (Format-Err $_) + ')')
    }
    Write-Log "업데이트 끝: $Target"
    exit 0
} catch {
    # 위에서 직접 처리하지 못한 오류(이 스크립트의 잘못 등) — 그래도 되돌림
    $script:FailReason = '예상 못 한 오류: ' + (Format-Err $_) + "`r`n" + $_.ScriptStackTrace
    Exit-Rollback
}
