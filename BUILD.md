# YesonCheck macOS 앱 빌드 (Intel / Apple Silicon)

- 지원 대상: **macOS 12.3(몬터레이) 이상**, Intel Mac과 Apple Silicon Mac
  (12.3인 이유: Intel용 paddle 3.0.0이 12.3을 요구. 몬터레이 최종 업데이트는 12.7.x)
- PyInstaller는 다른 아키텍처용으로 빌드할 수 없으므로, **아키텍처마다 해당 Mac에서 한 번씩** 빌드합니다.
  GitHub Actions가 두 아키텍처의 Mac 러너에서 각각 빌드·검사·실행 시험도 합니다 (5절). 아래 1·2절의 로컬 빌드는 그대로 쓸 수 있습니다.

| 빌드한 Mac | 결과물 | 배포 대상 |
|---|---|---|
| Intel Mac | `dist/YesonCheck_Autocut_Intel.app` | Intel Mac |
| Apple Silicon Mac | `dist/YesonCheck_Autocut_AppleSilicon.app` | Apple Silicon Mac |

Intel 앱도 Apple Silicon에서 Rosetta로 실행되지만, macOS 26.4부터 실행 시 경고가 뜨고 macOS 28부터는 실행되지 않습니다.

애니매틱2(TransNetV2 딥러닝 씬 감지)는 Mac·Windows 빌드 모두에 들어갑니다 (2026-10-14부터):
- 빌드 환경에 TensorFlow 2.15.1이 설치됩니다 (lock에 고정). TransNetV2 코드는 `yesoncheck/transnetv2_model.py`,
  가중치는 `vendor/transnetv2-weights/`(git에 들어 있음, 출처·sha256은 그 폴더의 `README.md`)에 있습니다.
- spec이 가중치 세 파일의 sha256을 확인하고 앱의 `transnetv2-weights/`에 넣습니다. 없거나 다르면 빌드가 멈춥니다.
- TensorFlow 때문에 앱 크기가 이전의 약 두 배가 됩니다. 앱 시작 때는 TensorFlow를 불러오지 않고,
  애니매틱2 분석을 시작할 때 불러옵니다 (로그에 `[애니매틱2 …] TensorFlow 불러오는 중…` / `불러옴 (n초)`).
- x86(Intel Mac, Windows)에서는 **CPU가 AVX를 지원해야** 애니매틱2가 보입니다. TensorFlow 2.15 x86 빌드는 AVX가 없는
  CPU에서 import하는 순간 오류 메시지 없이 죽기 때문에, 앱이 TensorFlow를 부르기 전에 numpy의 CPU 기능 표로 확인해
  AVX가 없으면 항목을 숨기고 시작 로그에 이유를 남깁니다 (`[시작 …] 애니매틱2(TransNetV2) 항목 숨김 — …`).
  해당: 오래된 펜티엄·셀러론, CPU 기능을 가린 가상 머신, macOS 12~14에서 Rosetta 2로 돌린 Intel 앱
  (Apple Silicon Mac에는 Apple Silicon 앱을 쓰세요). arm64 TensorFlow는 AVX와 무관합니다.

## 1. 빌드 환경 만들기 (Mac마다 최초 1회)

1. 소스 받기: `git clone https://github.com/yesonsys03-web/yesoncheck.git` (퍼블릭 저장소 — GitHub 로그인 없이 받을 수 있음)
2. 정적 ffmpeg 받기: 프로젝트 폴더에서 `./fetch_ffmpeg.sh`
   - git에 없는 `vendor/ffmpeg/{x86_64,arm64}`를 배포처에서 받아 sha256을 대조합니다 (`vendor/ffmpeg/README.md`). 이미 맞는 파일이 있으면 건너뜁니다.
   - 저장소 대신 폴더를 직접 복사했다면 `vendor/ffmpeg/`가 이미 들어 있으니 이 단계는 건너뛰어도 됩니다.
3. uv 설치: `brew install uv`
4. 프로젝트 폴더에서 실행:
   ```bash
   ./setup_build_env.sh
   ```
   - `~/coding/p310_tf`에 uv가 관리하는 Python 3.10 가상환경을 만들고, 아키텍처별 lock 파일
     (`requirements-build-x86_64.lock` / `requirements-build-arm64.lock`)의 고정 버전을 설치합니다 (TensorFlow 포함).
     마지막에 cv2·paddle·protobuf·tensorflow를 불러 확인합니다.
     설치할 버전을 바꾸려면 `requirements-build.txt`를 고친 뒤 파일 맨 위 명령으로 lock을 다시 만드세요.
   - 이미 `~/coding/p310_tf`가 있으면 멈춥니다. 다른 경로를 쓰려면 `VENV=경로 ./setup_build_env.sh`, 빌드할 때는 `PY=경로/bin/python ./build_app.sh`.
   - TensorFlow 이전의 환경 `~/coding/p310`은 지우지 않아도 됩니다 (되돌릴 때용). 스크립트의 기본 경로는 이제 `~/coding/p310_tf`입니다.
     `~/coding/p310`으로는 빌드할 수 없습니다 (TensorFlow가 없어 `check_frozen_imports.py`가 실패).
   - 소스 시험(pytest)도 이 환경에서: `uv pip install --python ~/coding/p310_tf/bin/python -r requirements-test.txt` 후
     `~/coding/p310_tf/bin/python -m pytest tests -q` (애니매틱2 시험은 TensorFlow가 없으면 실패합니다 — 건너뛰지 않음).

### Apple Silicon Mac

같은 순서입니다 (`./fetch_ffmpeg.sh` → `./setup_build_env.sh` → `./build_app.sh`). 스크립트가 venv Python의 아키텍처를 보고
`requirements-build-arm64.lock`을 고릅니다: paddle 3.0.0, TensorFlow 2.15.1(`macosx_12_0_arm64` 휠, 최소 macOS 12.0),
tensorflow-io-gcs-filesystem 0.34.0(앱에는 넣지 않음). Rosetta 터미널에서 만든 x86_64 Python이 아닌지 확인하세요
(`~/coding/p310_tf/bin/python -c 'import platform; print(platform.machine())'` → `arm64`).
TensorFlow를 넣은 Apple Silicon 빌드는 GitHub Actions의 `mac (AppleSilicon)` job(5절)이 만들고, 두 검사
(`check_min_macos.py`·`check_frozen_imports.py`)와 2절의 실행 시험(`애니매틱2 (TransNetV2)`가 `[0, 30, 60]`)까지 통과합니다.
Apple Silicon Mac에서 직접 빌드해도 같은 결과(두 검사 `통과`, 실행 시험 `"ok": true`)가 나와야 합니다.

- paddle 3.0.0 본체(최소 macOS 11.4)는 BLAS를 시스템 Accelerate로 씁니다. 휠에 함께 든 LAPACK 보조 라이브러리
  (libblas·liblapack — macOS 14.0 이상 + 휠을 만든 Mac의 Homebrew를 가리킴, 그 Fortran 런타임 libgfortran·libgcc_s·libquadmath)는
  spec이 앱에 넣지 않습니다 (본체가 링크하지 않고 LAPACK 연산 때만 불러옴 — OCR은 쓰지 않음).
- paddle 2.6.2는 쓰지 않습니다: 안에 정적으로 든 OpenBLAS(0.3.18 이전)의 `sgemm_itcopy`가 macOS가 예약한 x18 레지스터를
  반복 횟수로 써서, Apple Silicon에서는 OCR 추론 중에 프로세스가 죽습니다 (GitHub Actions 실행 시험에서 첫 OCR에서 끝남).

## 2. 빌드

```bash
./build_app.sh
```

PyInstaller 앞에 `tools/write_build_info.py`가 `build/build_info.json`(버전·커밋·빌드 시각·플랫폼)을 만들고, spec이 앱의
`Contents/Resources/`에 넣습니다 (창 제목·Help → 정보에 보이는 버전, 앱 `Info.plist`의 `CFBundleShortVersionString`).
버전은 git 태그로 정합니다: HEAD에 `vX.Y.Z` 태그가 있고 작업 폴더가 깨끗하면 `X.Y.Z`(배포판), 아니면
`<가장 큰 vX.Y.Z>+<커밋 7자리>`(태그가 없으면 `0.0.0+…`, 커밋 안 된 변경이 있으면 끝에 `.dirty`) — 정보 창에 "(시험 빌드)".
git 저장소가 아닌 폴더에서는 버전을 정할 수 없어 빌드가 멈춥니다.

빌드가 끝나면 두 가지 검사를 하고, 하나라도 실패하면 빌드 스크립트가 실패로 끝납니다.

1. `check_min_macos.py` — 앱 안의 모든 바이너리
   - 목표 아키텍처 슬라이스가 있는지
   - 요구 최소 macOS가 12.3 이하인지 (앱 Info.plist의 `LSMinimumSystemVersion` 기준)
   - `/usr/local`, `/opt/homebrew` 같은 빌드 Mac에만 있는 경로의 dylib를 참조하지 않는지
   - `@rpath` 등 상대 참조가 앱 안의 실제 파일을 가리키는지, 심볼릭 링크가 앱 밖을 가리키지 않는지
2. `check_frozen_imports.py` — 앱 안의 파이썬 모듈
   - 빌드 환경에서 OCR 인식과 씬 감지(애니매틱, 애니매틱2 TransNetV2)를 실제로 실행해 쓰인 모듈을 모으고, 그 모듈이 앱 안에 모두 있는지 대조합니다.
   - 애니매틱2는 합성 3샷 영상(30프레임씩)에서 씬 시작 `[0, 30, 60]`을 찾아야 하고, TensorFlow나 가중치가 없으면 검사가 실패합니다.
   - PyInstaller가 놓친 모듈 때문에 앱이 실행 중 `No module named ...`로 죽는 문제를 빌드 단계에서 잡습니다.
   - OCR 모델이 없으면 `~/.paddleocr`에 내려받으므로 인터넷 연결이 필요합니다.

두 검사 모두 `통과`가 나와야 배포할 수 있습니다. 이어서 앱의 `Contents/Resources/`에 `LICENSE`(GPL-3.0)와
`THIRD_PARTY_NOTICES.md`가 저장소의 것과 같게 들어 있는지도 확인합니다 (없으면 빌드 실패).

배포 전에 빌드된 앱으로 실행 시험도 해 보세요 (화면 없이 공유 설정·작품 목록·OCR·애니매틱2·내보내기·병합을 실제 앱 코드로 실행):

```bash
VERSION="$(~/coding/p310_tf/bin/python -c 'import json; print(json.load(open("build/build_info.json"))["version"])')"
~/coding/p310_tf/bin/python ci/make_test_data.py --share-root /tmp/yc --mac-root /tmp/yc --workdir /tmp/yc_smoke --expect-version "$VERSION"
QT_QPA_PLATFORM=offscreen YESONCHECK_CONFIG_DIR=/tmp/yc/.yesoncheck \
  dist/YesonCheck_Autocut_<Intel|AppleSilicon>.app/Contents/MacOS/YesonCheck_Autocut --smoke-test /tmp/yc_smoke
```

`--expect-version`: 앱이 읽은 버전(앱 안의 `build_info.json`)이 이번 빌드의 `build/build_info.json`과 같고 창 제목에 보이는지
`앱 버전` 항목으로 확인합니다.

종료 코드 0, `/tmp/yc_smoke/smoke_result.json`의 `"ok": true`, `애니매틱2 (TransNetV2)` 항목의 `"cuts": [0, 30, 60]`이면 정상입니다
(`/tmp/yc`·`/tmp/yc_smoke`가 이미 있으면 지우고 다시 만드세요).

빌드가 끝나면 `dist/YesonCheck_Autocut_<Intel|AppleSilicon>.commit.txt`에 이 빌드의 출처가 남습니다:
`commit`(빌드를 시작할 때의 `git rev-parse HEAD`), `tree`(`clean` 또는 커밋 안 된 변경이 있었으면 `dirty`), 빌드 시각, dmg 이름.
`dirty` 빌드는 커밋과 내용이 다를 수 있으니 배포하지 말고, 커밋한 뒤 다시 빌드하세요.
git 저장소가 아닌 폴더(직접 복사한 폴더)에서는 버전을 정할 수 없어 빌드하지 않습니다.

## 3. 배포

- **다른 Mac에는 반드시 `dist/YesonCheck_Autocut_<Intel|AppleSilicon>.dmg` 파일을 옮기세요.**
  `.app`은 폴더이고 안에 심볼릭 링크가 수백 개 있어서, 폴더째 NAS·메신저 등으로 옮기면 링크가 깨지고
  실행 시 `Fatal Python error ... No module named 'encodings'`로 멈춥니다. `.dmg`는 파일 하나라 안전합니다.
- 받은 Mac에서 `.dmg`를 열고 앱을 `Applications` 폴더로 끌어다 놓으면 설치됩니다.
- 배포할 때 같은 이름의 `.commit.txt`도 함께 보관하세요 (어느 커밋으로 만든 앱인지 확인용, `tree: clean`이어야 함).
- 메신저·브라우저로 받은 앱은 격리 속성 때문에 처음 열 때 차단될 수 있습니다. Finder에서 우클릭 → **열기**로 한 번 열거나 `xattr -dr com.apple.quarantine YesonCheck_Autocut_*.app`을 실행하세요.
- 작품 경로 설정(`/USA_DB/test_jn/.yesoncheck/work_paths.json`)은 모든 Mac이 같이 씁니다.

## 4. Windows 빌드 (GitHub Actions)

- 빌드는 GitHub Actions의 `build (Windows·Mac)` 워크플로(파일 `.github/workflows/windows-build.yml`)의 `build` job이 합니다. Windows PC에서 직접 빌드할 필요는 없습니다.
- 실행: GitHub 저장소 → Actions → build (Windows·Mac) → **Run workflow** (또는 `gh workflow run windows-build.yml --ref main`). `v*` 태그를 푸시해도 실행됩니다.
  한 번 실행하면 Windows와 Mac 두 종류(5절)를 함께 빌드합니다.
- 하는 일: Windows lock 설치 → ffmpeg(gyan 9.0.2) 받기 → 시험용 SMB 공유를 만들어 경로 시험 → PyInstaller 빌드 → `_internal`에 msvcp140.dll·msvcp140_1.dll 확인 → 모듈 검사 → 빌드된 exe로 실행 시험(한글 UNC 경로의 작품 목록·ffprobe·OpenCV·OCR·애니매틱2·내보내기·병합) → 설치 파일 시험.
- Windows lock은 `--override requirements-build-windows.overrides.txt`(protobuf 3.20.3)와 함께 설치해야 합니다:
  paddle 2.6.2 Windows 휠은 protobuf <=3.20.2를, TensorFlow 2.15는 >=3.20.3을 요구해 덮어쓰지 않으면 uv가 설치를 거부합니다.
- TensorFlow는 import할 때 msvcp140.dll·msvcp140_1.dll을 찾습니다. spec이 두 DLL을 `_internal` 맨 위에 넣고(의존성 분석에 없으면 빌드 PC의 System32에서), 워크플로가 있는지 확인합니다.
- 버전: Mac과 같이 `tools/write_build_info.py`가 git 태그로 정합니다 (체크아웃은 `fetch-depth: 0` — 태그까지 받음). 설치 파일 이름 꼬리
  `<file_tag>`는 배포판(`vX.Y.Z` 태그)이면 `X.Y.Z`, 아니면 커밋 7자리. 두 실행 시험(빌드된 exe·설치된 exe)이 `--expect-version`으로 앱의 버전도 확인합니다.
- 결과: 실행 기록 페이지 아래 **Artifacts**의 `YesonCheck_Setup_Windows_<file_tag>` 하나 (설치 파일 `YesonCheck_Setup_<file_tag>.exe`를 담은 zip). 14일 보관. **이 워크플로는 수동 실행이든 `v*` 태그 푸시든 빌드·시험만 합니다 — GitHub Release를 스스로 만들지 않습니다.** Release를 만들고 NAS에 올리는 일은 6·7절을 보세요.
  폴더째 받은 앱(`YesonCheck_Autocut_Windows_<커밋>`)은 2026-10-15부터 올리지 않습니다(사용자 요청 — 설치 파일만 씀).
- Windows PC에서 직접 빌드하려면: Python 3.10 + uv 설치 → `uv venv .venv --python 3.10 --managed-python` → `uv pip install --python .venv\Scripts\python.exe -r requirements-build-windows.lock --override requirements-build-windows.overrides.txt` → opencv contrib 재설치(워크플로 참고) → `./fetch_ffmpeg_windows.ps1` → `.venv\Scripts\python.exe tools\write_build_info.py --out build\build_info.json` → `.venv\Scripts\python.exe -m PyInstaller --clean -y YesonCheck_Autocut.spec`.
- 배포·첫 설정의 더 자세한 내용은 내부 문서를 참고하세요.

## 5. Mac 빌드 (GitHub Actions — Apple Silicon·Intel)

- 같은 워크플로 `build (Windows·Mac)`의 `mac` job이 Apple Silicon(`macos-15` 러너)과 Intel(`macos-15-intel` 러너)에서 각각 빌드합니다.
  실행 방법은 4절과 같고(수동 실행 또는 `v*` 태그), 한쪽이 실패해도 다른 쪽은 끝까지 돕니다.
- 하는 일은 1·2절의 스크립트 그대로입니다: `./fetch_ffmpeg.sh` → `VENV=<러너 임시 폴더>/p310_tf ./setup_build_env.sh`
  (+ `requirements-test.txt`) → 소스 시험(pytest) → `PY=… ./build_app.sh`(빌드 정보·PyInstaller·`check_min_macos.py`·
  `check_frozen_imports.py`·라이선스·dmg) → 2절의 실행 시험(`--expect-version` 포함, 시험 자료는 러너 임시 폴더) → dmg 올리기.
  - 빌드 전에 작업 폴더가 깨끗한지 확인합니다 (커밋 안 된 변경이 있으면 버전 끝에 `.dirty`가 붙어 멈춤).
  - 실행 시험은 25분 안에 끝나야 합니다 (Windows와 같음, macOS에는 `timeout` 명령이 없어 `perl`의 alarm으로 끊음).
    `smoke_result.json`은 성공해도 로그에 남습니다 — `애니매틱2 (TransNetV2)`의 `"cuts": [0, 30, 60]`을 여기서 확인할 수 있습니다.
  - 러너는 macOS 15지만 lock 설치가 `MACOSX_DEPLOYMENT_TARGET=12.0`으로 휠을 고르고 `check_min_macos.py`가 12.3 이하를
    확인하므로 몬터레이용 앱이 됩니다. 러너 디스크 여유는 시작과 끝에 `df -h /`로 기록합니다.
- 결과: Artifacts의 `YesonCheck_Autocut_AppleSilicon_<file_tag>`와 `YesonCheck_Autocut_Intel_<file_tag>`
  (각각 `YesonCheck_Autocut_<AppleSilicon|Intel>_<file_tag>.dmg`를 담은 zip, 14일 보관). `<file_tag>`는 4절과 같음
  (배포판 `vX.Y.Z` 태그면 `X.Y.Z`, 아니면 커밋 7자리). 받은 dmg는 3절처럼 씁니다.
- 로컬 `./build_app.sh`(1·2절)는 바뀌지 않았습니다. GitHub의 Intel Mac 러너는 언젠가 없어질 수 있습니다 —
  그때 Intel 앱은 다시 Intel Mac에서 `./build_app.sh`로 만듭니다.

## 6. 버전

- 보이는 곳: 창 제목(`Yeson Checker 1.1.0`), Help → 정보(버전·커밋·빌드 날짜), 업데이트 알림 띠.
- 기준은 git 태그 `vX.Y.Z`(배포한 커밋에 붙임). 빌드가 버전을 앱 안에 넣습니다(2절의 `build/build_info.json` →
  Mac 번들 `Info.plist`의 `CFBundleShortVersionString`/Windows 파일 버전 정보/Inno Setup `AppVersion`에도 같은 값).
  - **배포판**: 태그가 붙은 커밋을 깨끗한 작업 폴더에서 빌드 — `X.Y.Z`.
  - **배포가 아닌 빌드**(수동으로 돌린 CI, 이 Mac의 `./build_app.sh`): `<마지막 배포 버전>+<커밋 7자리>`
    (태그가 없으면 `0.0.0+…`, 커밋 안 된 변경이 있으면 끝에 `.dirty`) — Help → 정보에 "(시험 빌드)"로 표시.
    버전을 비교할 때 `+` 뒤는 무시합니다(같은 번호의 배포판과 같은 것으로 보아 알리지 않고, 다음 배포가 나오면 알립니다).
  - **소스에서 실행**(`python -m yesoncheck.app`, `run_app.sh`): "개발(소스)" — 업데이트를 확인하지 않습니다
    (바꿀 앱이 없음).
- 배포 번호는 늘 커지기만 합니다: 자동 업데이트가 들어간 첫 배포가 `1.1.0`, 그 뒤로는 배포마다 끝자리 +1
  (`1.1.1`, `1.1.2` …), 큰 변경이면 가운데 +1·끝 0(`1.2.0`). 배포 절차는 7절.

## 7. 배포 (자동 업데이트)

1.1.0부터 앱이 스스로 새 버전을 알리고 설치합니다: 창 위 알림 띠로 "새 버전이 나왔습니다"를 보이고,
[업데이트]를 누르면 받아서 앱이 닫히고 설치된 뒤 다시 켜집니다. 빌드는 지금처럼 자주 돌지만(결과는 artifact만),
사용자가 Claude에게 **"배포해줘"**라고 할 때만 새 버전이 되어 알립니다.

### 7-1. "배포해줘" (유지보수자가 이 Mac에서)

배포 도구 `tools/release.py`가 합니다(`~/coding/p310_tf/bin/python tools/release.py <명령>`):

1. **`prepare`**: `main`에 있는 커밋인지·작업 폴더가 깨끗한지·NAS에 쓸 수 있는지·`gh` 로그인을 확인 → 다음 배포
   번호를 정함(가장 큰 `v*` 태그의 끝자리 +1, 큰 변경이면 `--minor`로 가운데 +1·끝 0) → 바뀐 점을 메시지로 담은
   주석 태그 `vX.Y.Z`를 푸시 → 이 태그로 CI(4·5절의 세 빌드: Windows, Mac Intel, Mac Apple Silicon)가 시작됩니다.
2. CI가 끝나기를 기다립니다 — 세 빌드 모두 성공해야 합니다(Windows 빌드가 가장 오래 걸려 약 1시간 안팎).
   Actions 화면에서 진행을 볼 수 있습니다.
3. **`publish`**: 세 job이 모두 성공했는지 확인 → 빌드 결과(artifact)를 받아 `latest.json`을 만듦 → GitHub
   Release를 초안으로 올리고 올라간 파일이 맞는지 확인한 뒤 공개(최신판으로 표시) → NAS `updates/` 폴더에 복사
   (설치 파일을 먼저, `latest.json`은 맨 마지막) → 오래된 설치 파일 정리(지금 버전과 바로 전 버전만 남김).
4. 버전·Release 주소·NAS 위치·걸린 시간을 보고합니다.

**중요**: GitHub Release는 이 CI 워크플로가 스스로 만들지 않습니다(4절). Actions 화면에서 태그를 눌러 직접
실행해도 빌드만 됩니다 — Release를 만들고 NAS에 복사하는 일은 반드시 이 Mac에서 `tools/release.py publish`를
실행해야 일어납니다.

그 밖의 명령:
- **`nas-sync`**: GitHub에는 이미 공개됐는데 NAS 복사만 실패했을 때, Release 파일을 받아 NAS에 다시 복사합니다.
- **`abort`**: CI가 실패했을 때 태그와 초안 Release를 지웁니다(공개된 Release는 거부 — 번호는 다음 배포가
  다시 씁니다).
- **되돌리기**: "1.1.1로 되돌려줘"처럼 말하면, 그때의 커밋을 `--commit`으로 가리켜 새 번호(예: `1.1.3`)로 다시
  배포합니다. 버전 번호는 늘 커지기만 하므로 앱은 "지금보다 큰 번호가 있으면 알림" 한 가지 규칙만 씁니다.

### 7-2. 어디에 올라가나

- **GitHub Releases**(이 저장소의 Releases 탭): 설치 파일 3개(Windows·Mac Intel·Mac Apple Silicon)와
  `latest.json`.
- **NAS**: 공유 설정 폴더(작품 경로 설정 `work_paths.json`이 있는 그 공유 설정 폴더) 아래 `updates/` 폴더에
  같은 파일들. 인터넷이 안 되는 컴퓨터는 여기서 받습니다. 지금 버전과 바로 전 버전만 남습니다(그보다 오래된
  설치 파일은 지워지고, GitHub Release는 지우지 않습니다).

### 7-3. 사용자 컴퓨터에서

- 앱을 켤 때, 그리고 켜 둔 동안 3시간마다, Help → **업데이트 확인…**을 눌렀을 때 NAS와 GitHub를 확인합니다.
- 새 버전이 있으면 창 위 알림 띠: "⬆ 새 버전 1.1.1이 나왔습니다 · 지금 1.1.0" + [바뀐 점] [업데이트] [나중에].
  누르기 전에는 아무것도 바뀌지 않습니다.
- [업데이트]를 누르면: 받기(진행 표시, 취소 가능) → 앱이 닫힘 → 설치 → 다시 켜짐 → 띠에
  "1.1.1로 업데이트했습니다"가 잠깐 보입니다.
- 실패하면 지금 버전이 그대로 켜지고 "업데이트 실패" 창에 이유가 보입니다 — 다른 곳으로 저절로 바꿔 받지
  않습니다. 다시 [업데이트]를 누르면 처음부터 받습니다.
- 업데이트 기록(로그): Windows `%LOCALAPPDATA%\YesonCheck\logs\update.log`,
  Mac `~/Library/Logs/YesonCheck/update.log`.

### 7-4. 처음 한 번 (1.1.0 설치)

자동 업데이트가 들어간 1.1.0은 각 컴퓨터에 마지막으로 손으로 설치합니다. GitHub Release 페이지 또는 NAS
`updates/` 폴더에서 받으세요.

- **Windows**: `YesonCheck_Setup_1.1.0.exe`를 실행 — 지금 설치된 자리에 그대로 덮어 설치됩니다.
- **Mac**: `YesonCheck_Autocut_<Intel|AppleSilicon>_1.1.0.dmg`를 열고 앱을 **Applications** 폴더로 끌어다
  놓습니다(3절과 같음). 브라우저로 받은 dmg는 처음 열 때 Gatekeeper가 막을 수 있습니다 — Finder에서 앱을
  우클릭 → **열기**로 한 번 열어 주세요.

### 7-5. Apple Silicon·Intel 러너가 없어지면

GitHub의 Intel Mac 러너(`macos-15-intel`)는 언젠가 없어질 수 있습니다(5절) — 그때는 Intel 빌드를 이 Mac에서
`./build_app.sh`로 만든 뒤 배포 도구에 넘기는 방식으로 돌아갑니다.
