# CI 시험용 SMB 공유: C:\yc_share를 \\localhost\yc_test로 공유하고 드라이브 문자로 연결한다
# 이후 단계가 쓰도록 YC_TEST_* 환경 변수를 GITHUB_ENV에 남긴다
param([string]$Drive = "Y:", [string]$Root = "C:\yc_share", [string]$ShareName = "yc_test")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Root | Out-Null
New-SmbShare -Name $ShareName -Path $Root -FullAccess "Everyone" | Out-Null
$Unc = "\\localhost\$ShareName"
net use $Drive $Unc /persistent:no
if ($LASTEXITCODE -ne 0) { throw "net use 실패: $Drive -> $Unc" }
Get-SmbMapping | Format-Table -AutoSize | Out-String | Write-Host
if ($env:GITHUB_ENV) {
    "YC_TEST_DRIVE=$Drive" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    "YC_TEST_UNC=$Unc" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    "YC_TEST_SHARE_ROOT=$Root" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
}
