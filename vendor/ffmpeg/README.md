# 번들용 정적 ffmpeg / ffprobe

YesonCheck_Autocut.spec이 빌드하는 Mac의 아키텍처 폴더(`x86_64`, `arm64`)에서 가져와 앱에 넣습니다.
Homebrew ffmpeg는 빌드한 macOS 버전 이상에서만 실행되고 /usr/local·/opt/homebrew의 dylib를 참조하므로 쓰지 않습니다.

- 버전: FFmpeg 9.0.2 (정적 빌드, 시스템 라이브러리만 참조, 최소 macOS 12.0)
- 출처: https://ffmpeg.martin-riedl.de/ (release 9.0.2, 2026-10-06 다운로드, 배포처 sha256으로 zip 검증)
  - x86_64: https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/{ffmpeg,ffprobe}.zip
  - arm64:  https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/{ffmpeg,ffprobe}.zip

| 파일 | sha256 |
|---|---|
| x86_64/ffmpeg | b25689cf2211c0582d317e849912769a1f1c93904fe102c485b5364a425633d1 |
| x86_64/ffprobe | b5df9964b0c2048318fafedcd4e3bbafbc561033cee77de8da1840685d8a9d0d |
| arm64/ffmpeg | 2e11c6f90993cdb79fff84d3f90044d28316b310e75b3e030cfc9a54f2c9d384 |
| arm64/ffprobe | 2738aa46a7f9acbc8ab09a6715554c90f7de603171ac403726765685df6a0059 |

바이너리는 크기(합계 약 320MB) 때문에 git에 넣지 않습니다. clone한 뒤 프로젝트 폴더에서 `./fetch_ffmpeg.sh`를 실행하면 위 주소에서 받아 sha256을 대조해 넣습니다.

교체할 때는 `check_min_macos.py`로 아키텍처·최소 macOS·외부 dylib 참조를 확인하고, `fetch_ffmpeg.sh`의 주소·sha256과 위 표도 같이 고치세요.

## Windows (`windows/ffmpeg.exe`, `windows/ffprobe.exe`)

- 버전: FFmpeg 9.0.2 essentials (gyan.dev, GPL, libx264 포함, 정적 빌드)
- 출처: https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip
  (zip sha256 60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba)
- 받기: PowerShell에서 `./fetch_ffmpeg_windows.ps1` (zip과 exe의 sha256 대조)

| 파일 | sha256 |
|---|---|
| windows/ffmpeg.exe | 3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec |
| windows/ffprobe.exe | f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52 |
