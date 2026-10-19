; YesonCheck Windows 설치 파일 (Inno Setup 6)
;
; CI(windows-build.yml)가 PyInstaller onedir 빌드(dist\YesonCheck_Autocut)를 만든 뒤
; 이 스크립트로 Setup.exe 하나로 묶는다. 버전 정보는 CI가 커맨드라인에서 넘긴다:
;   ISCC /DAppVersion=1.2.3 /DAppSha=abcdef1 installer\yesoncheck.iss
; 로컬에서 그냥 열어 컴파일할 수 있도록 기본값도 정의해 둔다.

#define MyAppName "Yeson Checker"
#define MyAppPublisher "Yeson"
#define MyAppExeName "YesonCheck_Autocut.exe"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppSha
  #define AppSha "dev"
#endif

; Inno Setup이 Korean.isl을 들고 있는지 컴파일 타임에 확인 (없으면 영어만 제공)
#define InnoLangDir GetEnv('ProgramFiles(x86)') + "\Inno Setup 6\Languages"

[Setup]
; 이 GUID는 절대 바꾸지 않는다 — 바뀌면 설치 프로그램이 "업데이트"가 아니라
; 새 프로그램으로 보여 이전 설치를 못 찾고 나란히 깔릴 수 있다.
AppId={{E9263926-FCEA-4F45-9FA2-F7AED9F27FF4}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}

; C:\YesonCheck — ASCII, 공백 없음. PaddleOCR 등 일부 구성 요소가 한글·공백이 든 경로에서
; 실패하기 때문에 사용자 프로필(한글 이름일 수 있음) 밑이 아니라 드라이브 루트를 기본으로 쓴다.
DefaultDirName={sd}\YesonCheck
; 표준 사용자는 보통 시스템 드라이브 루트에 새 폴더를 만들 수 있어 관리자 권한 없이 설치된다
; (PrivilegesRequired=lowest). 그 PC의 정책상 그게 안 되면, 아래 설정 덕분에 설치 폴더
; 선택 화면이 나와 사용자가 직접 쓸 수 있는 다른 폴더(예: 사용자 폴더 밑)를 고를 수 있다.
DisableDirPage=no
UsePreviousAppDir=yes
; [Icons]에서 {group}을 쓰지 않으므로("시작 메뉴 폴더" 없이 바로 가기 하나만 둠) 폴더 선택 화면도 생략
DisableProgramGroupPage=yes

; 관리자 권한도 UAC 창도 필요 없게 — 스튜디오 PC에서 바로 설치할 수 있도록
PrivilegesRequired=lowest

; 업데이트 설치 때 실행 중인 YesonCheck_Autocut.exe를 닫아 주되(그래야 _internal 교체가 됨),
; 설치가 끝난 뒤 자동으로 다시 켜지는 않는다 (CloseApplications/RestartApplications)
CloseApplications=yes
RestartApplications=no

Compression=lzma2
SolidCompression=yes
; 압축이 너무 느리면 여기를 lzma2/fast로 바꾸는 것을 가장 먼저 고려할 것
; (CI 전체 제한 150분 안에서 다른 단계들과 같이 돌아가야 함)

; 이 스크립트는 installer\ 안에 있으므로, 상대 Source 경로는 저장소 루트를 기준으로
; 삼도록 SourceDir을 한 단계 위로 돌린다 (dist\YesonCheck_Autocut\... 그대로 쓰기 위함)
SourceDir=..
; OutputDir도 상대 경로면 SourceDir(저장소 루트) 기준이다 (Inno Setup 문서; CI에서 OutputDir=. 은
; 저장소 루트에 만들어졌음) → 결과물이 installer\YesonCheck_Setup_<sha>.exe 로 만들어지도록 installer로 지정
OutputDir=installer
OutputBaseFilename=YesonCheck_Setup_{#AppSha}

UninstallDisplayIcon={app}\{#MyAppExeName}
#ifexist "..\icon.ico"
SetupIconFile=icon.ico
#endif

[Languages]
#ifexist InnoLangDir + "\Korean.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기 (Create a desktop shortcut)"; Flags: checkedonce

[Files]
Source: "dist\YesonCheck_Autocut\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 라이선스(GPL-3.0)와 제3자 구성 요소 고지를 실행 파일 옆에도 둔다 (_internal 안에는 spec이 넣음)
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; 업데이트 설치 때마다 예전 _internal을 통째로 지우고 새로 복사한다 —
; 예전 빌드의 파일이 새 빌드와 섞여 남지 않도록 (CloseApplications가 먼저 실행 중인 앱을 닫아 둠)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\Yeson Checker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\Yeson Checker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; 설치 끝 화면의 선택적 체크박스. /VERYSILENT 같은 무음 설치에서는 skipifsilent 덕분에 실행되지 않는다
; (CI가 설치 직후 바로 앱을 실행 시험하므로, 설치 프로그램이 따로 앱을 띄우면 안 됨)
Filename: "{app}\{#MyAppExeName}"; Description: "Yeson Checker 실행"; Flags: nowait postinstall skipifsilent

; 제거 프로그램은 {app}(설치 폴더) 안의 파일만 지운다.
; %APPDATA%\YesonCheck\settings.json (PC별 설정)과 %LOCALAPPDATA%\YesonCheck\logs(로그)는
; 이 스크립트의 어떤 섹션도 건드리지 않으므로 제거 뒤에도 그대로 남는다 — 의도된 동작이다.
