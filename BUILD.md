# YesonCheck macOS 앱 빌드 (Intel / Apple Silicon)

- 지원 대상: **macOS 12.3(몬터레이) 이상**, Intel Mac과 Apple Silicon Mac
  (12.3인 이유: Intel용 paddle 3.0.0이 12.3을 요구. 몬터레이 최종 업데이트는 12.7.x)
- PyInstaller는 다른 아키텍처용으로 빌드할 수 없으므로, **아키텍처마다 해당 Mac에서 한 번씩** 빌드합니다.

| 빌드한 Mac | 결과물 | 배포 대상 |
|---|---|---|
| Intel Mac | `dist/YesonCheck_Autocut_Intel.app` | Intel Mac |
| Apple Silicon Mac | `dist/YesonCheck_Autocut_AppleSilicon.app` | Apple Silicon Mac |

Intel 앱도 Apple Silicon에서 Rosetta로 실행되지만, macOS 26.4부터 실행 시 경고가 뜨고 macOS 28부터는 실행되지 않습니다.

## 1. 빌드 환경 만들기 (Mac마다 최초 1회)

1. 소스 받기: `git clone https://github.com/yesonsys03-web/yesoncheck.git` (비공개 저장소라 GitHub 로그인 필요)
2. 정적 ffmpeg 받기: 프로젝트 폴더에서 `./fetch_ffmpeg.sh`
   - git에 없는 `vendor/ffmpeg/{x86_64,arm64}`를 배포처에서 받아 sha256을 대조합니다 (`vendor/ffmpeg/README.md`). 이미 맞는 파일이 있으면 건너뜁니다.
   - 저장소 대신 폴더를 직접 복사했다면 `vendor/ffmpeg/`가 이미 들어 있으니 이 단계는 건너뛰어도 됩니다.
3. uv 설치: `brew install uv`
4. 프로젝트 폴더에서 실행:
   ```bash
   ./setup_build_env.sh
   ```
   - `~/coding/p310`에 uv가 관리하는 Python 3.10 가상환경을 만들고, 아키텍처별 lock 파일
     (`requirements-build-x86_64.lock` / `requirements-build-arm64.lock`)의 고정 버전을 설치합니다.
     설치할 버전을 바꾸려면 `requirements-build.txt`를 고친 뒤 파일 맨 위 명령으로 lock을 다시 만드세요.
   - 이미 `~/coding/p310`이 있으면 멈춥니다. 다른 경로를 쓰려면 `VENV=경로 ./setup_build_env.sh`, 빌드할 때는 `PY=경로/bin/python ./build_app.sh`.

## 2. 빌드

```bash
./build_app.sh
```

빌드가 끝나면 두 가지 검사를 하고, 하나라도 실패하면 빌드 스크립트가 실패로 끝납니다.

1. `check_min_macos.py` — 앱 안의 모든 바이너리
   - 목표 아키텍처 슬라이스가 있는지
   - 요구 최소 macOS가 12.3 이하인지 (앱 Info.plist의 `LSMinimumSystemVersion` 기준)
   - `/usr/local`, `/opt/homebrew` 같은 빌드 Mac에만 있는 경로의 dylib를 참조하지 않는지
   - `@rpath` 등 상대 참조가 앱 안의 실제 파일을 가리키는지, 심볼릭 링크가 앱 밖을 가리키지 않는지
2. `check_frozen_imports.py` — 앱 안의 파이썬 모듈
   - 빌드 환경에서 OCR 인식과 씬 감지를 실제로 실행해 쓰인 모듈을 모으고, 그 모듈이 앱 안에 모두 있는지 대조합니다.
   - PyInstaller가 놓친 모듈 때문에 앱이 실행 중 `No module named ...`로 죽는 문제를 빌드 단계에서 잡습니다.
   - OCR 모델이 없으면 `~/.paddleocr`에 내려받으므로 인터넷 연결이 필요합니다.

두 검사 모두 `통과`가 나와야 배포할 수 있습니다.

## 3. 배포

- **다른 Mac에는 반드시 `dist/YesonCheck_Autocut_<Intel|AppleSilicon>.dmg` 파일을 옮기세요.**
  `.app`은 폴더이고 안에 심볼릭 링크가 수백 개 있어서, 폴더째 NAS·메신저 등으로 옮기면 링크가 깨지고
  실행 시 `Fatal Python error ... No module named 'encodings'`로 멈춥니다. `.dmg`는 파일 하나라 안전합니다.
- 받은 Mac에서 `.dmg`를 열고 앱을 `Applications` 폴더로 끌어다 놓으면 설치됩니다.
- 메신저·브라우저로 받은 앱은 격리 속성 때문에 처음 열 때 차단될 수 있습니다. Finder에서 우클릭 → **열기**로 한 번 열거나 `xattr -dr com.apple.quarantine YesonCheck_Autocut_*.app`을 실행하세요.
- 작품 경로 설정(`/USA_DB/test_jn/.yesoncheck/work_paths.json`)은 모든 Mac이 같이 씁니다.

## 4. Windows 빌드 (GitHub Actions)

- 빌드는 GitHub Actions의 `windows-build` 워크플로가 합니다. Windows PC에서 직접 빌드할 필요는 없습니다.
- 실행: GitHub 저장소 → Actions → windows-build → **Run workflow** (또는 `gh workflow run windows-build.yml --ref main`). `v*` 태그를 푸시해도 실행됩니다.
- 하는 일: Windows lock 설치 → ffmpeg(gyan 9.0.2) 받기 → 시험용 SMB 공유를 만들어 경로 시험 → PyInstaller 빌드 → 모듈 검사 → 빌드된 exe로 실행 시험(한글 UNC 경로의 작품 목록·ffprobe·OpenCV·OCR·내보내기·병합).
- 결과: 실행 기록 페이지 아래 **Artifacts**의 `YesonCheck_Autocut_Windows_<커밋 7자리>` (zip, 크기는 실행 기록 페이지에 표시). 14일 보관. **GitHub Release에는 올리지 않습니다.**
- Windows PC에서 직접 빌드하려면: Python 3.10 + uv 설치 → `uv venv .venv --python 3.10 --managed-python` → `uv pip install --python .venv\Scripts\python.exe -r requirements-build-windows.lock` → opencv contrib 재설치(워크플로 참고) → `./fetch_ffmpeg_windows.ps1` → `.venv\Scripts\python.exe -m PyInstaller --clean -y YesonCheck_Autocut.spec`.
- 배포·첫 설정은 `docs/windows-deploy.md`.
