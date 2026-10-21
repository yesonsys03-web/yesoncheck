# YesonCheck Windows 업데이트 도우미 — 앱이 끝난 뒤 설치 폴더를 백업 이름으로 바꾸고 새 버전을 조용히 설치하며,
# 새 앱이 잘 켜지지 않으면 되돌린다.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File update_helper_windows.ps1
#       -AppPid PID -InstallDir DIR -Installer EXE -Target VER -OkFile OK -Log LOG [-TimeoutSeconds S] [-ExeName NAME]
#       [-Token TOKEN]
#   (TOKEN: 앱의 업데이트 기록(pending_update.json)의 토큰 — 다시 켜는 앱만 결과를 판정하게 넘길 값. 지금은 받아 두기만 함)
#   powershell ... -File update_helper_windows.ps1 -Recover      (다음 로그인에서 — RunOnce가 부름, 아래 '되살림')
#
# 앱(update_install.launch_helper_windows)이 이 파일을 업데이트 상태 폴더로 복사해 창 없는 콘솔로 띄운 뒤 끝난다.
# 순서:
#   1. PID가 끝나기를 기다림(300초 — 넘으면 아무것도 바꾸지 않음). pid는 끝난 뒤 다른 프로세스에 다시 쓰일 수 있으므로
#      그 pid의 실행 파일이 DIR\ExeName일 때만 기다린다.
#   2. 지난번에 치워 둔 DIR.update-failed-*를 지워 봄(못 지워도 계속), 남은 DIR.update-backup을 지움(못 지우면 설치하지
#      않음).
#   3. 지난 OK를 지우고(못 지우면 바꾸지 않고 옛 앱을 다시 켬 — 남은 OK가 이번 업데이트의 것으로 보이면 다음 로그인의
#      되살림이 반쯤 깔린 DIR을 남길 수 있음) 다음 로그인의 되살림을 등록(아래)한 뒤 DIR을 DIR.update-backup으로 이름만
#      바꿈(약 1 GB를 복사하지 않음). 안의 파일이 잡혀 있어 못 바꾸면 — 다른 YesonCheck 창이 켜져 있거나 백신 등이 파일을
#      잡고 있음 — 설치하지 않고 옛 앱을 다시 켬.
#   4. 설치 파일을 /VERYSILENT로 DIR에 설치(설치 파일 자체 기록은 LOG.inno.txt). 종료 코드 ≠ 0이면 되돌림. 30분 안에
#      끝나지 않으면 설치 파일과 그 자손 프로세스(Inno의 is-*.tmp\Setup.tmp 등)를 끝내고 되돌림.
#   5. OK를 지우고 DIR\ExeName을 켬(환경 변수는 이 도우미의 것 그대로, 작업 폴더는 DIR — 바로 가기와 같음).
#   6. 새 앱이 창을 보인 뒤 쓰는 OK({"version": "VER"})를 -TimeoutSeconds초까지 기다림 → 되면 백업·되살림 등록·OK를 지움.
# 중간에 실패하거나, 새 앱이 표시 없이 끝나거나, 시간이 지나면 되돌림: 새 앱과 그 자손 프로세스, 실행 파일이 DIR
# 아래인 프로세스를 끝내고(이름으로는 찾지 않음), 반쯤 깔린 DIR을 옆 이름으로 치운 뒤 백업을 DIR로 되돌리고, 치운 것을
# 지운 다음 옛 앱을 켠다. DIR에 앱이 없는 채로 끝내지 않는다 — 되돌리기마저 실패하면 두 오류를 모두 기록하고, 알림 창을
# 띄우고(앱이 없으니 다음 실행에서 알릴 수 없음) 종료 코드 2.
#
# 종료 코드: 0 업데이트 성공, 1 바꾸지 않았거나 되돌림(옛 앱을 켬), 2 되돌리기 실패·설치 폴더에 앱이 없음·잘못된 인자.
#
# 되살림 (컴퓨터가 꺼지거나 로그아웃되어 이 도우미와 설치 파일이 중간에 끝난 경우): DIR의 이름을 바꾸기 바로 전에
# HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce에 값 YesonCheckUpdateRecover(= 이 스크립트 -Recover)를 등록하고,
# 되살림에 쓸 값(DIR·VER·OK·LOG·NAME)을 이 스크립트 옆 update_recover.txt에 적는다(RunOnce 명령 줄은 260자 안으로 — 경로를
# 다 넣으면 넘음; 스크립트 경로가 길어 넘으면 짧은(8.3) 경로, 그다음 짧은 옵션 이름으로 줄여 보고, 그래도 넘으면 등록하지 않고
# 크게 기록한 뒤 업데이트는 계속 — 그때는 설치 중에 꺼지면 손으로 되돌려야 함). 끝날 때(성공·되돌림·바꾸지 않음) 둘 다
# 지운다 — 되돌리기마저 실패한 종료 코드 2만 남겨 둬, 다음 로그인에서 다시 되살려 본다. Windows는 다음 로그인에서 그 값을
# 지우고 한 번 실행한다. -Recover:
#   - DIR.update-backup이 없으면 할 일 없음 (종료 코드 0).
#   - OK가 VER이고 DIR에 앱이 있으면 업데이트는 성공했던 것 → 백업만 지움 (0). (등록 전에 지난 OK를 지우고, 되돌릴 때는
#     새 앱을 끝낸 뒤에 지우므로 OK는 이 업데이트의 새 앱이 잘 켜진 뒤에만 있음)
#   - 그 밖이면 끝나지 않은 업데이트 → DIR(반쯤 깔린 것)을 옆 이름으로 치우고 백업을 DIR로 되돌림 (1). 앱은 켜지 않는다 —
#     로그인 때 저절로 창이 뜨지 않게; 다음에 켠 옛 앱이 업데이트 기록을 보고 '업데이트 실패' 창으로 알림.
#   - 되살리지 못하면 기록하고 알림 창 (2).
#
# 모든 단계와 실패를 LOG에 "YYYY-MM-DDTHH:MM:SS 도우미: 내용" 한 줄씩 UTF-8로 덧붙인다 — update_install.log()와 같은
# 시각 형식이고(앱의 줄은 시각 뒤에 "[pid N]") 다시 켜진 앱이 log_tail_since로 업데이트를 건 창의 줄과 이 줄들을 "업데이트
# 실패" 창에 보여 준다(시각 없이 이어지는 줄은 앞줄을 따름).
# Windows PowerShell 5.1에서 돈다 — 이 파일은 UTF-8 BOM으로 저장한다(BOM이 없으면 5.1이 한글을 ANSI로 읽음).
# $ErrorActionPreference = 'Stop'이고, 단계마다 try/catch로 직접 처리해 되돌리기가 반드시 돈다.
#
# 환경 변수 (주로 시험용):
#   YC_UPDATE_OK_TIMEOUT_S       -TimeoutSeconds의 기본값 (없으면 180초)
#   YC_UPDATE_PID_TIMEOUT_S      앱이 끝나기를 기다리는 시간 (없으면 300초)
#   YC_UPDATE_INSTALL_TIMEOUT_S  설치 파일이 끝나기를 기다리는 시간 (없으면 1800초)
#   YC_UPDATE_NO_MESSAGEBOX      1이면 종료 코드 2의 알림 창을 띄우지 않음 (시험이 멈추지 않게)
#   YC_UPDATE_RUNONCE_KEY        되살림을 등록할 HKCU 아래 키 (없으면 Software\Microsoft\Windows\CurrentVersion\RunOnce —
#                                시험은 진짜 RunOnce를 건드리지 않게 다른 키로)
#   YC_UPDATE_RUNONCE_MAX_CHARS  RunOnce 명령 줄의 한도 (없으면 260 — 시험이 줄이기·등록하지 않기를 일부러 거치게)

param(
    [string]$AppPid = '',
    [string]$InstallDir = '',
    [string]$Installer = '',
    [string]$Target = '',
    [string]$OkFile = '',
    [string]$Log = '',
    [string]$TimeoutSeconds = '',
    [string]$ExeName = 'YesonCheck_Autocut.exe',
    [string]$Token = '',
    [switch]$Recover
)

$ErrorActionPreference = 'Stop'
$ExtraArgs = @($args)  # 모르는 인자 — 함수 안에서 $args를 쓰면 그 함수의 인자이므로 여기서 받아 둠
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$RetryCount = 5          # 이름 바꾸기·지우기: 잠깐 잡힌 파일(백신 검사 등) 때문이면 1초 간격으로 다시 해 봄
$RestoreRetryCount = 30  # 되돌리기의 이름 바꾸기는 더 오래(30번 + 남은 프로세스를 다시 끝낸 뒤 30번 — 약 1분)
$WmiTimeoutS = 30        # 자손 프로세스를 찾는 WMI 질의의 한도 (기본은 끝없이 기다림 — winmgmt가 멈추면 되돌리기도 멈춤)

$script:FailReason = ''
$script:OkReadError = ''   # 마지막으로 OK를 읽지 못한 이유 (실패 기록용)
$script:AppGone = $false   # 앱(PID)이 끝났음 — 그 전에는 옛 앱을 다시 켜지 않음(아직 켜져 있을 수 있음)
$script:Renamed = $false   # DIR을 백업 이름으로 바꿨음 — 그 뒤로 실패하면 백업을 되돌려야 함
$script:Launched = $false  # 새 앱을 켜려고 했음 — 되돌릴 때 새 앱과 그 자손, DIR 아래 프로세스를 끝내야 함
$script:NewProc = $null    # 켠 새 앱 프로세스
$script:NewProcStart = [DateTime]::MinValue  # 새 앱을 켜기 바로 전 시각 (자손 프로세스를 가릴 때 씀)
$script:InstallerProc = $null  # 실행한 설치 파일 프로세스 — 되돌리기의 두 번째 이름 바꾸기 전에 그 자손을 다시 끝냄
$script:InstallerStart = [DateTime]::MinValue
$script:RecoverSet = $false  # 다음 로그인의 되살림을 등록했음 — 끝날 때 지워야 함

$RecoverValueName = 'YesonCheckUpdateRecover'  # RunOnce 값 이름
$RunOnceKey = $env:YC_UPDATE_RUNONCE_KEY
if (-not $RunOnceKey) { $RunOnceKey = 'Software\Microsoft\Windows\CurrentVersion\RunOnce' }
$RecoverFile = [System.IO.Path]::Combine($PSScriptRoot, 'update_recover.txt')  # 되살림에 쓸 값 (이 스크립트 옆)

# ---- 기록 ----

function Write-Log([string]$Message) {
    # update_install.timestamp()와 같은 형식 (지역 설정과 상관없이 - 와 : 를 그대로)
    $stamp = [DateTime]::Now.ToString("yyyy-MM-dd'T'HH':'mm':'ss", [System.Globalization.CultureInfo]::InvariantCulture)
    $line = $stamp + ' 도우미: ' + $Message
    if (-not $Log) {
        # 기록 파일이 없을 때(잘못된 인자)만 stdout으로 — 있으면 기록에만: 앱은 stdout을 파일로 받아 기록에 없는 줄을 실패 창에
        # 보이는데, 5.1은 그 파일에 이 컴퓨터의 코드 페이지로 써서 한글이 깨진 같은 줄이 '기록에 없는 줄'이 됨
        [Console]::Out.WriteLine($line)
        return
    }
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

function Show-FatalMessage([string]$Text) {
    # 종료 코드 2일 때만: 앱을 다시 켜지 못했으니(또는 앱이 없으니) 다음 실행에서 알릴 수 없음 — 마지막으로 알림 창을
    # 띄운다. 맨 위에 보이게 DefaultDesktopOnly. 닫을 때까지 이 도우미는 기다림
    if ($env:YC_UPDATE_NO_MESSAGEBOX -eq '1') {
        Write-Log '알림 창은 띄우지 않음 (YC_UPDATE_NO_MESSAGEBOX=1)'
        return
    }
    try {
        $null = [System.Reflection.Assembly]::Load('System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089')
        $null = [System.Windows.Forms.MessageBox]::Show($Text, 'Yeson Checker 업데이트 실패',
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error,
            [System.Windows.Forms.MessageBoxDefaultButton]::Button1, [System.Windows.Forms.MessageBoxOptions]::DefaultDesktopOnly)
    } catch {
        Write-Log ('알림 창을 띄우지 못함: ' + (Format-Err $_))
    }
}

function Exit-Fatal([string]$Text) {
    # 알림 창을 띄우고 종료 코드 2 (기록은 부른 쪽이 먼저 남김)
    $where = '자세한 기록: ' + $Log
    if (-not $Log) { $where = '(기록 파일 없음)' }
    Show-FatalMessage ($Text + "`r`n`r`n" + $where)
    exit 2
}

function Exit-Usage([string]$Why) {
    Write-Log ('잘못된 인자: ' + $Why)
    [Console]::Error.WriteLine('사용법: powershell -File update_helper_windows.ps1 -AppPid PID -InstallDir DIR -Installer EXE -Target VER -OkFile OK -Log LOG [-TimeoutSeconds S] [-ExeName NAME]')
    Exit-Fatal ("업데이트 도우미를 시작하지 못했습니다 (잘못된 인자: " + $Why + ").`r`nYeson Checker를 다시 켜 주세요.")
}

# ---- 파일 ----

function Test-Exists([string]$Path) {
    return ([System.IO.Directory]::Exists($Path) -or [System.IO.File]::Exists($Path))
}

function Move-Dir([string]$From, [string]$To, [int]$Attempts = 5) {
    # 폴더 이름 바꾸기 (같은 드라이브 — 복사하지 않음). 안의 파일이 잡혀 있으면 실패하므로 1초 간격으로 Attempts번까지
    # 해 보고(처음 실패만 기록), 끝내 안 되면 마지막 오류를 그대로 올림
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            [System.IO.Directory]::Move($From, $To)
            return
        } catch {
            if ($attempt -ge $Attempts) { throw }
            if ($attempt -eq 1) {
                Write-Log ('이름을 바꾸지 못해 다시 해 봄 (최대 ' + $Attempts + '번, ' + $From + ' → ' + $To + '): ' + (Format-Err $_))
            }
            Start-Sleep -Seconds 1
        }
    }
}

function Remove-Dir([string]$Path, [int]$Attempts = 5) {
    # 폴더(또는 파일)를 통째로 지움. 지운 뒤 남아 있으면 실패 — Attempts번까지 해 보고, 끝내 안 되면 마지막 오류를 올림
    $attempt = 0
    while ($true) {
        $attempt++
        if (-not (Test-Exists $Path)) { return }
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            if (-not (Test-Exists $Path)) { return }
            throw ('지운 뒤에도 남아 있음: ' + $Path)
        } catch {
            if ($attempt -ge $Attempts) { throw }
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

function Remove-FailedLeftovers {
    # 지난 업데이트가 되돌리며 치워 두고 지우지 못한 DIR.update-failed-*를 지워 봄 — 못 지워도 기록만 하고 계속
    $parent = [System.IO.Path]::GetDirectoryName($InstallDir)
    $prefix = [System.IO.Path]::GetFileName($InstallDir) + '.update-failed-'
    try {
        $found = @([System.IO.Directory]::GetDirectories($parent, $prefix + '*'))
    } catch {
        Write-Log ('지난 업데이트에서 치워 둔 폴더를 찾지 못함: ' + $parent + ' (' + (Format-Err $_) + ')')
        return
    }
    foreach ($dir in $found) {
        # 검색 무늬는 8.3 짧은 이름에도 맞을 수 있음 — 이름이 정말 그렇게 시작하는 것만
        if (-not [System.IO.Path]::GetFileName($dir).StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
        try {
            Remove-Dir $dir 1
            Write-Log "지난 업데이트에서 치워 둔 폴더를 지움: $dir"
        } catch {
            Write-Log ('지난 업데이트에서 치워 둔 폴더를 지우지 못함 (다음에 다시 해 봄): ' + $dir + ' (' + (Format-Err $_) + ')')
        }
    }
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

function Get-Descendants([int]$RootPid, [DateTime]$RootStart) {
    # RootPid의 자손 프로세스(자식·손자 …)들의 pid — Win32_Process의 ParentProcessId를 따라감. 부모보다 먼저 생긴
    # 프로세스는 넣지 않음(부모 pid가 끝난 뒤 다른 프로세스에 다시 쓰였을 수 있음). 시각 정밀도 차이로 1초 여유
    # 질의에 한도를 둠 — 넘으면 예외(부른 쪽이 기록하고, 루트와 DIR 아래 프로세스만 끝내고 계속)
    $searcher = [wmisearcher]'SELECT ProcessId, ParentProcessId, CreationDate FROM Win32_Process'
    $searcher.Options.Timeout = [TimeSpan]::FromSeconds($WmiTimeoutS)
    $all = @($searcher.Get())
    $created = @{}  # 자손으로 넣은 pid → 생긴 시각
    $created[$RootPid] = $RootStart
    $found = New-Object System.Collections.ArrayList
    $added = $true
    while ($added) {
        $added = $false
        foreach ($p in $all) {
            $id = [int]$p.ProcessId
            $parent = [int]$p.ParentProcessId
            if ($id -eq $PID) { continue }  # 이 도우미 자신은 넣지 않음
            if ($created.ContainsKey($id) -or (-not $created.ContainsKey($parent)) -or (-not $p.CreationDate)) { continue }
            $when = [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$p.CreationDate)
            if ($when.AddSeconds(1) -lt $created[$parent]) { continue }
            $created[$id] = $when
            $null = $found.Add($id)
            $added = $true
        }
    }
    return $found
}

function Add-Target($List, $Proc) {
    # 끝낼 프로세스 목록에 넣음 (pid가 같은 것은 한 번만)
    foreach ($t in $List) { if ($t.Id -eq $Proc.Id) { return } }
    $null = $List.Add($Proc)
}

function Add-ProcessTree($List, $Root, [DateTime]$RootStart) {
    # Root(아직 돌면)와 그 자손을 끝낼 목록에 넣음 — 자손을 찾지 못해도 기록하고 Root는 넣음
    if (-not $Root.HasExited) { Add-Target $List $Root }
    $ids = @()
    try {
        $ids = @(Get-Descendants $Root.Id $RootStart)
    } catch {
        Write-Log ('자손 프로세스를 찾지 못함 (pid ' + $Root.Id + '): ' + (Format-Err $_))
    }
    foreach ($id in $ids) {
        try {
            Add-Target $List ([System.Diagnostics.Process]::GetProcessById($id))
        } catch {
            Write-Log "자손 프로세스(pid $id)는 그 사이에 끝남"
        }
    }
}

function Stop-Targets($List, [string]$What) {
    if ($List.Count -eq 0) {
        Write-Log "$($What) 프로세스는 이미 끝나 있음"
        return
    }
    Write-Log ("$($What) 프로세스를 끝냄: pid " + (($List | ForEach-Object { $_.Id }) -join ' '))
    foreach ($p in $List) {
        try {
            if (-not $p.HasExited) { $p.Kill() }
        } catch {
            Write-Log ("프로세스(pid $($p.Id))를 끝내지 못함: " + (Format-Err $_))
        }
    }
    foreach ($p in $List) {
        try {
            if (-not $p.WaitForExit(10000)) { Write-Log "프로세스(pid $($p.Id))가 10초 안에 끝나지 않음" }
        } catch {
            Write-Log ("프로세스(pid $($p.Id))가 끝나기를 기다리지 못함: " + (Format-Err $_))
        }
    }
}

function Stop-NewApp {
    # 켠 새 앱과 그 자손(작업 폴더 DIR을 물려받은 cmd.exe·powershell.exe 등 — 실행 파일은 DIR 밖), 그리고 실행 파일이
    # DIR 아래인 프로세스(새 앱이 띄운 ffmpeg 등)를 모두 끝냄. 이름으로는 찾지 않는다 — 다른 곳에 깔린 같은 이름의 앱은
    # 건드리지 않음
    $targets = New-Object System.Collections.ArrayList
    if ($null -ne $script:NewProc) { Add-ProcessTree $targets $script:NewProc $script:NewProcStart }
    $prefix = $InstallDir + '\'
    foreach ($p in [System.Diagnostics.Process]::GetProcesses()) {
        $path = $null
        try { $path = $p.MainModule.FileName } catch { $path = $null }  # 시스템·다른 사용자 프로세스는 경로를 읽을 수 없음 — 우리 앱이 아님
        if ($path -and $path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { Add-Target $targets $p }
    }
    Stop-Targets $targets '새 앱'
}

function Invoke-Installer {
    # 설치 파일을 조용히 실행하고 끝나기를 기다림 (windows-build.yml의 설치 시험과 같은 인자) → 종료 코드.
    # InstallTimeoutS초 안에 끝나지 않으면 설치 파일과 그 자손을 끝내고 $null
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Installer
    $psi.Arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $InstallDir + '" /LOG="' + $InnoLog + '"'
    $psi.UseShellExecute = $false
    $script:InstallerStart = [DateTime]::Now
    $proc = [System.Diagnostics.Process]::Start($psi)
    $script:InstallerProc = $proc
    if ($proc.WaitForExit($InstallTimeoutS * 1000)) { return $proc.ExitCode }
    Write-Log ('설치 파일이 ' + $InstallTimeoutS + '초 안에 끝나지 않아 설치 파일과 그 자손 프로세스를 끝냄 (pid ' + $proc.Id + ')')
    Stop-InstallerTree
    return $null
}

function Stop-InstallerTree {
    # 실행한 설치 파일(아직 돌면)과 그 자손(Inno의 is-*.tmp\Setup.tmp 등)을 끝냄
    $targets = New-Object System.Collections.ArrayList
    Add-ProcessTree $targets $script:InstallerProc $script:InstallerStart
    Stop-Targets $targets '설치 파일'
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

# ---- 다음 로그인의 되살림 (RunOnce) ----

function Remove-RecoverFile {
    try {
        if ([System.IO.File]::Exists($RecoverFile)) { [System.IO.File]::Delete($RecoverFile) }
    } catch {
        Write-Log ('되살림 정보 파일을 지우지 못함: ' + $RecoverFile + ' (' + (Format-Err $_) + ')')
    }
}

function Get-ShortPath([string]$Path) {
    # 8.3 짧은 경로 (Scripting.FileSystemObject). 그 볼륨에 짧은 이름이 없으면 긴 이름 그대로 돌아옴. 구하지 못하면 기록하고
    # 원래 경로
    try {
        $fso = New-Object -ComObject Scripting.FileSystemObject
        $short = $fso.GetFile($Path).ShortPath
        if ($short) { return $short }
        Write-Log ('짧은(8.3) 경로가 비어 있음 — 긴 경로 그대로: ' + $Path)
    } catch {
        Write-Log ('짧은(8.3) 경로를 구하지 못함 — 긴 경로 그대로: ' + $Path + ' (' + (Format-Err $_) + ')')
    }
    return $Path
}

function Get-RecoverCommand {
    # RunOnce에 넣을 명령 줄 — $RunOnceMaxChars(260)자 안: 긴 경로 그대로 → 짧은(8.3) 경로 → 짧은 경로 + 짧은 옵션 이름
    # (-NoP·-EP·-W, powershell.exe가 아는 줄임) 순으로 해 봄. 셋 다 넘으면 $null — 마지막에 해 본 것은
    # $script:RecoverCommandTried (부른 쪽이 기록)
    $exe = [System.IO.Path]::Combine($PSHOME, 'powershell.exe')
    $long = '"' + $exe + '" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '" -Recover'
    $script:RecoverCommandTried = $long
    if ($long.Length -le $RunOnceMaxChars) { return $long }
    $shortExe = Get-ShortPath $exe
    $shortScript = Get-ShortPath $PSCommandPath
    $candidates = @(
        ('"' + $shortExe + '" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $shortScript + '" -Recover'),
        ('"' + $shortExe + '" -NoP -EP Bypass -W Hidden -File "' + $shortScript + '" -Recover')
    )
    foreach ($command in $candidates) {
        $script:RecoverCommandTried = $command
        if ($command.Length -le $RunOnceMaxChars) {
            Write-Log ('되살림 명령 줄이 ' + $long.Length + '자로 RunOnce 한도 ' + $RunOnceMaxChars + '자를 넘어 줄여 씀 (' +
                $command.Length + '자)')
            return $command
        }
    }
    return $null
}

function Register-Recover {
    # DIR의 이름을 바꾸기 바로 전: 되살림 정보 파일을 쓰고 RunOnce에 이 스크립트 -Recover를 등록. 등록하지 못해도(명령 줄이
    # 한도를 넘음 포함) 업데이트는 계속 (되돌리기는 그대로 돎 — 중간에 컴퓨터가 꺼질 때만 손으로 되돌려야 함), 크게 기록만
    $text = ('InstallDir=' + $InstallDir + "`r`n" + 'Target=' + $Target + "`r`n" + 'OkFile=' + $OkFile + "`r`n" +
        'Log=' + $Log + "`r`n" + 'ExeName=' + $ExeName + "`r`n")
    $command = $null
    try {
        $command = Get-RecoverCommand
    } catch {
        Write-Log ('다음 로그인의 되살림을 등록하지 않음 — 명령 줄을 만들지 못함: ' + (Format-Err $_) +
            ' — 업데이트는 계속하지만, 설치 중에 컴퓨터가 꺼지면 손으로 되돌려야 함')
        return
    }
    if ($null -eq $command) {
        Write-Log ('다음 로그인의 되살림을 등록하지 않음 — RunOnce 명령 줄이 짧은 경로·짧은 옵션으로도 ' +
            $script:RecoverCommandTried.Length + '자로 한도 ' + $RunOnceMaxChars + '자를 넘음 (스크립트 경로가 너무 김): ' +
            $script:RecoverCommandTried + ' — 업데이트는 계속하지만, 설치 중에 컴퓨터가 꺼지면 손으로 되돌려야 함')
        return
    }
    try {
        [System.IO.File]::WriteAllText($RecoverFile, $text, $Utf8NoBom)
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($RunOnceKey)
        if ($null -eq $key) { throw ('레지스트리 키를 만들지 못함: HKCU\' + $RunOnceKey) }
        try {
            $key.SetValue($RecoverValueName, $command, [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $key.Close()
        }
    } catch {
        Write-Log ('다음 로그인의 되살림을 등록하지 못함 — 업데이트는 계속 (설치 중에 컴퓨터가 꺼지면 손으로 되돌려야 함): ' + (Format-Err $_))
        Remove-RecoverFile
        return
    }
    $script:RecoverSet = $true
    Write-Log ('다음 로그인에서 되살리도록 등록함 (HKCU\' + $RunOnceKey + ' 의 ' + $RecoverValueName + ', ' + $command.Length + '자): ' + $command)
}

function Clear-Recover {
    # 등록한 되살림을 지움 (RunOnce 값, 그다음 되살림 정보 파일) → $true: 지웠거나 등록하지 않았음, $false: 값을 지우지 못함
    # (기록 — 정보 파일은 남겨 둠: 다음 로그인의 되살림이 읽을 수 있게)
    if (-not $script:RecoverSet) { return $true }
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($RunOnceKey, $true)
        if ($null -ne $key) {
            try {
                $key.DeleteValue($RecoverValueName, $false)
            } finally {
                $key.Close()
            }
        }
    } catch {
        Write-Log ('다음 로그인의 되살림 등록을 지우지 못함 (HKCU\' + $RunOnceKey + ' 의 ' + $RecoverValueName + '): ' + (Format-Err $_))
        return $false
    }
    $script:RecoverSet = $false
    Remove-RecoverFile
    Write-Log '다음 로그인의 되살림 등록을 지움'
    return $true
}

function Read-RecoverInfo {
    # 되살림 정보 파일 → 값 (InstallDir·Target·OkFile·Log·ExeName). 없거나 형식이 다르면 예외
    $info = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($RecoverFile, $Utf8NoBom)) {
        if (-not $line) { continue }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { throw ('형식이 다른 줄: ' + $line) }
        $info[$line.Substring(0, $i)] = $line.Substring($i + 1)
    }
    foreach ($name in @('InstallDir', 'Target', 'OkFile', 'Log', 'ExeName')) {
        if (-not $info[$name]) { throw ($name + ' 값이 없음') }
    }
    foreach ($name in @('InstallDir', 'OkFile', 'Log')) {
        if ($info[$name] -notmatch '^(?:[A-Za-z]:\\|\\\\)') { throw ($name + ' 값이 전체 경로가 아님: ' + $info[$name]) }
    }
    return $info
}

function Remove-OkMarker([string]$Why) {
    # '잘 켜짐' 표시(OK)가 있으면 지움 → $true: 없음·지움, $false: 지우지 못함 (기록). 다음 로그인의 되살림은 OK가 VER이면
    # 새 버전을 남기므로 OK는 이 업데이트의 새 앱이 잘 켜진 뒤에만 있어야 함 — 되살림 등록 전·되돌릴 때·되살림 끝에 지움
    try {
        if ([System.IO.File]::Exists($OkFile)) {
            [System.IO.File]::Delete($OkFile)
            Write-Log ("'잘 켜짐' 표시를 지움 (" + $Why + '): ' + $OkFile)
        }
        return $true
    } catch {
        Write-Log ("'잘 켜짐' 표시를 지우지 못함 (" + $Why + '): ' + $OkFile + ' (' + (Format-Err $_) + ')')
        return $false
    }
}

# ---- 되돌리기 ----

function Move-DirForRestore([string]$From, [string]$To) {
    # 되돌리기의 이름 바꾸기 — 끝낸 프로세스가 핸들을 늦게 놓거나 백신이 잡고 있을 수 있어 오래 해 보고, 그래도 안 되면
    # 남은 새 앱 프로세스를 다시 끝낸 뒤 한 번 더 오래 해 봄. 끝내 안 되면 마지막 오류를 올림
    try {
        Move-Dir $From $To $RestoreRetryCount
        return
    } catch {
        Write-Log ('되돌리기의 이름 바꾸기가 ' + $RestoreRetryCount + '번 실패함 (' + $From + ' → ' + $To + '): ' + (Format-Err $_))
    }
    if ($script:Launched) {
        try { Stop-NewApp } catch { Write-Log ('새 앱 프로세스를 다시 끝내다 오류: ' + (Format-Err $_)) }
    }
    if ($null -ne $script:InstallerProc) {
        try { Stop-InstallerTree } catch { Write-Log ('설치 파일 프로세스를 다시 끝내다 오류: ' + (Format-Err $_)) }
    }
    Move-Dir $From $To $RestoreRetryCount
}

function Restore-Backup {
    # 반쯤 깔린 DIR을 옆 이름으로 치우고(이름 바꾸기 — 지우다 일부만 지워져도 막히지 않게) 백업을 DIR로 되돌린 뒤 치운
    # 것을 지움. $true: 되돌림, $false: 되돌리지 못함 (이유는 기록)
    $failed = $null
    if (Test-Exists $InstallDir) {
        # 치울 이름은 이번 실행만의 것 (지난번에 못 지운 것이 남아 있어도 막히지 않게)
        $failed = Get-UnusedName ($InstallDir + '.update-failed-' + $PID)
        try {
            Move-DirForRestore $InstallDir $failed
        } catch {
            Write-Log ('되돌리기 실패 — 반쯤 깔린 설치 폴더를 치우지 못함 (' + $InstallDir + ' → ' + $failed + '): ' + (Format-Err $_))
            return $false
        }
        Write-Log "반쯤 깔린 설치 폴더를 치움: $InstallDir → $failed"
    }
    try {
        Move-DirForRestore $Backup $InstallDir
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
            Write-Log ('치운 새 버전을 지우지 못함 (다음 업데이트가 다시 지워 봄): ' + $failed + ' (' + (Format-Err $_) + ')')
        }
    }
    return $true
}

function Exit-Rollback {
    # $script:FailReason을 기록하고, 바꾼 것을 되돌린 뒤 옛 앱을 켜고 끝냄(1). 되돌리기가 실패하면 알림 창과 함께 2
    Write-Log ('업데이트 실패: ' + $script:FailReason)
    if (-not $script:AppGone) {
        Write-Log '앱이 끝나기 전이라 아무것도 바꾸지 않음'
        exit 1
    }
    Write-Log '되돌림 시작'
    if ($script:Launched) {
        try { Stop-NewApp } catch { Write-Log ('새 앱 프로세스를 끝내다 오류: ' + (Format-Err $_)) }
    }
    # 새 앱을 끝낸 뒤에 — 끝나기 전에 늦게 쓴 표시도 남지 않게 (되돌리는 중에 컴퓨터가 꺼져도 다음 로그인의 되살림이 이
    # 표시를 보고 반쯤 되돌린 새 버전을 남긴 채 백업을 지우지 않게). 지우지 못해도 되돌림은 계속
    if ($script:Renamed) { $null = Remove-OkMarker '되돌리기로 정함 — 새 앱을 끝낸 뒤' }
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
        if ($script:RecoverSet) { Write-Log '다음 로그인에서 다시 되살려 보도록 되살림 등록을 남겨 둠' }
        Exit-Fatal ("업데이트에 실패했고, 이전 버전으로 되돌리지도 못했습니다.`r`n`r`n" +
            '이전 버전(백업): ' + $Backup + "`r`n설치 폴더: " + $InstallDir + "`r`n`r`n" +
            '설치 폴더를 지우거나 다른 이름으로 바꾼 뒤, 백업 폴더의 이름을 설치 폴더 이름으로 바꾸면 이전 버전을 다시 쓸 수 있습니다.')
    }
    $null = Clear-Recover
    Write-Log '되돌림: 옛 앱을 다시 켬'
    try { $null = Start-App '옛 앱' } catch { Write-Log ('옛 앱을 켜지 못함: ' + (Format-Err $_)) }
    exit 1
}

# ---- 인자 확인 ----

if ($ExtraArgs.Count -gt 0) { Exit-Usage ('알 수 없는 인자: ' + ($ExtraArgs -join ' ')) }

# ---- 다음 로그인에서 되살림 (-Recover — RunOnce가 부름, 머리 설명의 '되살림') ----

if ($Recover) {
    foreach ($given in @($AppPid, $InstallDir, $Installer, $Target, $OkFile, $Log, $TimeoutSeconds)) {
        if ($given) { Exit-Usage '-Recover에는 다른 인자를 함께 쓰지 않음 (되살림 정보 파일에서 읽음)' }
    }
    try {
        $info = Read-RecoverInfo
    } catch {
        $why = Format-Err $_
        [Console]::Error.WriteLine('되살림 정보를 읽지 못함: ' + $RecoverFile + ' (' + $why + ')')
        Exit-Fatal ("지난 업데이트를 되살려야 하는지 확인하지 못했습니다 — 되살림 정보를 읽지 못함:`r`n" + $RecoverFile + "`r`n" + $why)
    }
    $InstallDir = $info['InstallDir'].TrimEnd('\')
    $Target = $info['Target']
    $OkFile = $info['OkFile']
    $Log = $info['Log']
    $ExeName = $info['ExeName']
    $ExePath = [System.IO.Path]::Combine($InstallDir, $ExeName)
    $Backup = $InstallDir + '.update-backup'
    try {
        $null = [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($Log))
    } catch {
        [Console]::Error.WriteLine('로그 폴더를 만들지 못함: ' + $Log + ' (' + (Format-Err $_) + ')')
    }
    try {
        [System.IO.Directory]::SetCurrentDirectory($PSScriptRoot)
    } catch {
        Write-Log ('작업 폴더를 이 스크립트 폴더로 바꾸지 못함: ' + $PSScriptRoot + ' (' + (Format-Err $_) + ')')
    }
    Write-Log ('되살림 확인 (다음 로그인, RunOnce): 대상 버전 ' + $Target + ', 설치 폴더 ' + $InstallDir)
    if (-not (Test-Exists $Backup)) {
        Write-Log ('되살림: 백업이 없음 — 할 일 없음 (' + $Backup + ')')
        Remove-RecoverFile
        exit 0
    }
    $okVersion = Read-OkVersion
    if (($okVersion -eq $Target) -and [System.IO.File]::Exists($ExePath)) {
        Write-Log ('되살림: 새 버전(' + $Target + ')이 잘 켜졌던 업데이트 — 새 버전을 그대로 두고 남은 백업만 지움: ' + $Backup)
        try {
            Remove-Dir $Backup
            Write-Log "백업을 지움: $Backup"
        } catch {
            Write-Log ('백업을 지우지 못함 (다음 업데이트가 다시 지워 봄): ' + $Backup + ' (' + (Format-Err $_) + ')')
        }
        $null = Remove-OkMarker '되살림 끝'
        Remove-RecoverFile
        exit 0
    }
    Write-Log ("되살림: 끝나지 않은 업데이트 (컴퓨터가 꺼짐·로그아웃 등, '잘 켜짐' 표시: " + (Get-OkSummary $okVersion) +
        ') — 이전 버전을 되살림')
    $script:Launched = $true  # 이름 바꾸기가 막히면 실행 파일이 설치 폴더 아래인 프로세스(반쯤 깔린 앱)를 끝내고 다시 해 봄
    $restored = $false
    try {
        $restored = Restore-Backup
        if ($restored -and (-not [System.IO.File]::Exists($ExePath))) {
            Write-Log ('되살림 실패 — 설치 폴더에 이전 버전 앱이 없음: ' + $ExePath)
            $restored = $false
        }
    } catch {
        Write-Log ('되살림 실패 — 예상 못 한 오류: ' + (Format-Err $_) + "`r`n" + $_.ScriptStackTrace)
        $restored = $false
    }
    Remove-RecoverFile
    if (-not $restored) {
        Write-Log ('되살림 실패 — 이전 버전(백업): ' + $Backup + ', 설치 폴더: ' + $InstallDir +
            ' (백업 폴더 이름을 설치 폴더 이름으로 손으로 바꿔 주세요)')
        Exit-Fatal ("지난 업데이트가 끝나지 않은 채(컴퓨터가 꺼짐·로그아웃 등) 남아 이전 버전으로 되살리려 했지만 하지 못했습니다.`r`n`r`n" +
            '이전 버전(백업): ' + $Backup + "`r`n설치 폴더: " + $InstallDir + "`r`n`r`n" +
            '설치 폴더를 지우거나 다른 이름으로 바꾼 뒤, 백업 폴더의 이름을 설치 폴더 이름으로 바꾸면 이전 버전을 다시 쓸 수 있습니다.')
    }
    $null = Remove-OkMarker '되살림 끝'
    Write-Log ('다음 로그인에서 되살림: 이전 버전을 설치 폴더로 되돌림 (' + $InstallDir +
        ') — 앱은 켜지 않음 (다음에 켤 때 업데이트 실패를 알림)')
    exit 1
}

# ---- 업데이트의 인자 ----

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
$InstallTimeoutText = $env:YC_UPDATE_INSTALL_TIMEOUT_S
if (-not $InstallTimeoutText) { $InstallTimeoutText = '1800' }
$RunOnceMaxText = $env:YC_UPDATE_RUNONCE_MAX_CHARS
if (-not $RunOnceMaxText) { $RunOnceMaxText = '260' }
$numbers = [ordered]@{
    '-AppPid' = $AppPid; '-TimeoutSeconds(YC_UPDATE_OK_TIMEOUT_S)' = $TimeoutSeconds
    'YC_UPDATE_PID_TIMEOUT_S' = $PidTimeoutText; 'YC_UPDATE_INSTALL_TIMEOUT_S' = $InstallTimeoutText
    'YC_UPDATE_RUNONCE_MAX_CHARS' = $RunOnceMaxText
}
foreach ($name in $numbers.Keys) {
    if ($numbers[$name] -notmatch '^[0-9]{1,9}$') { Exit-Usage ($name + ' 값은 숫자여야 함: ' + $numbers[$name]) }
}
$AppPidNum = [int]$AppPid
$TimeoutS = [int]$TimeoutSeconds
$PidTimeoutS = [int]$PidTimeoutText
$InstallTimeoutS = [int]$InstallTimeoutText
$RunOnceMaxChars = [int]$RunOnceMaxText  # RunOnce 명령 줄 한도 (Microsoft 문서: 260자)
# 밀리초로 바꿔 WaitForExit(int)에 넘기므로 하루까지만
if ($PidTimeoutS -gt 86400) { Exit-Usage ('YC_UPDATE_PID_TIMEOUT_S 값이 너무 큼: ' + $PidTimeoutS) }
if ($InstallTimeoutS -gt 86400) { Exit-Usage ('YC_UPDATE_INSTALL_TIMEOUT_S 값이 너무 큼: ' + $InstallTimeoutS) }
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
        Exit-Fatal ("업데이트를 시작하지 못했습니다 — 설치 폴더에 Yeson Checker가 없습니다:`r`n" + $ExePath)
    }
    if (-not [System.IO.File]::Exists($Installer)) {
        $script:FailReason = "설치 파일이 없음: $Installer"
        Exit-Rollback
    }

    # 3. 지난 업데이트가 남긴 것 (치워 둔 폴더는 지워 보기만, 백업이 남아 있으면 이름 바꾸기가 실패하므로 꼭 지움)
    Remove-FailedLeftovers
    if (Test-Exists $Backup) {
        Write-Log "지난 업데이트의 백업이 남아 있어 먼저 지움: $Backup"
        try {
            Remove-Dir $Backup
        } catch {
            $script:FailReason = '지난 업데이트의 백업을 지우지 못함: ' + $Backup + ' (' + (Format-Err $_) + ')'
            Exit-Rollback
        }
    }

    # 4. 설치 폴더를 백업 이름으로 (여기는 짧게 — 오래 잡혀 있으면 다른 창이 켜져 있는 것). 바로 전에 지난 '잘 켜짐' 표시를
    #    지우고(같은 버전을 다시 해 볼 때 지난번 것이 남아 있으면 다음 로그인의 되살림이 반쯤 깔린 설치 폴더를 새 버전으로
    #    봄 — 못 지우면 아무것도 바꾸지 않고 멈춤) 다음 로그인의 되살림을 등록: 여기부터 컴퓨터가 꺼지면 앱이 백업 이름에
    #    있거나 반쯤 깔린 채로 남음 (지난 백업을 지운 뒤라 남은 백업은 이번 것)
    if (-not (Remove-OkMarker '되살림 등록 전 — 지난 업데이트의 것')) {
        $script:FailReason = ("지난 '잘 켜짐' 표시를 지우지 못해 이름을 바꾸기 전에 멈춤 (남아 있으면 설치 중에 꺼졌을 때 다음 " +
            '로그인의 되살림이 반쯤 깔린 설치 폴더를 새 버전으로 볼 수 있음): ' + $OkFile)
        Exit-Rollback
    }
    Register-Recover
    try {
        Move-Dir $InstallDir $Backup $RetryCount
    } catch {
        $script:FailReason = '설치 폴더의 이름을 바꾸지 못함 — 다른 YesonCheck 창이 켜져 있거나 파일이 잡혀 있음 (' + $InstallDir + ' → ' + $Backup + '): ' + (Format-Err $_)
        Exit-Rollback
    }
    $script:Renamed = $true
    Write-Log "설치 폴더를 백업 이름으로 바꿈: $InstallDir → $Backup"

    # 5. 조용히 설치
    Write-Log "설치 파일을 조용히 실행: $Installer (설치 파일 기록: $InnoLog, 최대 $($InstallTimeoutS)초)"
    $code = $null
    try {
        $code = Invoke-Installer
    } catch {
        $script:FailReason = '설치 파일을 실행하지 못함: ' + $Installer + ' (' + (Format-Err $_) + ')'
        Exit-Rollback
    }
    if ($null -eq $code) {
        $script:FailReason = "설치 파일이 $($InstallTimeoutS)초 안에 끝나지 않음 (설치 파일 기록: $InnoLog)"
        Write-InnoLogTail
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
    $script:NewProcStart = [DateTime]::Now
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
    if (Clear-Recover) {
        try {
            if ([System.IO.File]::Exists($OkFile)) { [System.IO.File]::Delete($OkFile) }
        } catch {
            Write-Log ("'잘 켜짐' 표시를 지우지 못함: " + $OkFile + ' (' + (Format-Err $_) + ')')
        }
    } else {
        # 다음 로그인의 되살림이 (백업이 남았으면) 이 표시를 보고 새 버전을 그대로 두고 백업만 지우게
        Write-Log "되살림 등록을 지우지 못해 '잘 켜짐' 표시를 남겨 둠 — 다음 로그인의 되살림은 새 버전을 그대로 두고 백업만 지움"
    }
    Write-Log "업데이트 끝: $Target"
    exit 0
} catch {
    # 위에서 직접 처리하지 못한 오류(이 스크립트의 잘못 등) — 그래도 되돌림
    $script:FailReason = '예상 못 한 오류: ' + (Format-Err $_) + "`r`n" + $_.ScriptStackTrace
    Exit-Rollback
}
