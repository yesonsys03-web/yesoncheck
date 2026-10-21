# CLAUDE.md

이 파일은 Claude Code (claude.ai/code)가 이 저장소의 코드 작업 시 참고할 수 있는 가이드를 제공합니다.

## 프로젝트 개요

YesonCheck는 PyQt5로 구축된 전문 비디오 비교 및 OCR 분석 도구입니다. A/B 비디오 비교, OCR 기반 텍스트 세그먼트 감지, 자동 씬 컷 감지(애니매틱 모드), 애니메이션 제작 워크플로우에 최적화된 클립 내보내기 기능을 제공합니다.

**주요 기술**: PyQt5, OpenCV, PaddleOCR, PySceneDetect, TransNetV2, FFmpeg

## 주요 명령어

### 개발 환경
```bash
# 빌드·개발 환경 만들기 (최초 1회): ~/coding/p310_tf에 Python 3.10 + 아키텍처별 lock의 고정 버전
# (PyQt5, opencv 4.6.0.66, paddle, paddleocr 2.7.3, scenedetect 0.6.7.1, TensorFlow 2.15.1 등 — BUILD.md)
./setup_build_env.sh

# 가상 환경 활성화 (TF 이전의 ~/coding/p310은 빌드에 쓰지 않음)
source ~/coding/p310_tf/bin/activate

# TransNetV2(애니매틱2)는 pip로 설치하지 않음: 로더 코드 yesoncheck/transnetv2_model.py와
# 가중치 vendor/transnetv2-weights/가 저장소에 들어 있음 (upstream 85cef72, MIT)

# 시험
python -m pytest tests -q

# 애플리케이션 실행
python -m yesoncheck.app

# 비디오 파일과 함께 열기
python -m yesoncheck.app /path/to/video.mp4

# 빠른 구문 검사
python -m compileall yesoncheck
```

### macOS 애플리케이션 빌드
```bash
# 빌드 + 번들 검사(최소 macOS·모듈) + dmg (BUILD.md)
./build_app.sh

# 출력 위치
# dist/YesonCheck_Autocut_Intel.app 또는 dist/YesonCheck_Autocut_AppleSilicon.app (+ .dmg)
```

### 외부 의존성
```bash
# FFmpeg (비디오 병합 및 내보내기에 필수)
brew install ffmpeg

# FFmpeg 설치 확인
which ffmpeg ffprobe
# 출력 결과: /usr/local/bin/ffmpeg 및 /usr/local/bin/ffprobe
```

## 주요 기능

### 비디오 비교 및 분석
- **A/B 비교**: 두 비디오를 나란히 비교하거나 와이프 효과로 오버레이
- **ROI 선택**: 마우스로 드래그하여 관심 영역 선택 (OCR 분석용)
- **프레임 정확도 탐색**: 개별 프레임 단위로 비디오 탐색
- **북마크 시스템**: 중요한 프레임 마킹 및 빠른 탐색

### OCR 및 씬 감지
- **다중 OCR 모드**: King (빨간색 텍스트), Titmouse, Bento (표준 OCR)
- **자동 씬 컷 감지**: PySceneDetect (하드 컷) 및 TransNetV2 (점진적 전환)
- **세그먼트 편집**: 병합, 삭제, 이름 변경, 분할 기능
- **자동 씬 이름 지정**: OCR 텍스트 기반 자동 이름 생성

### 내보내기 및 공유
- **다중 품질 프리셋**: Fast (하드웨어 가속), Quality, Balanced
- **배치 내보내기**: 여러 세그먼트를 한 번에 내보내기
- **웹 보고서**: HTML 형식으로 OCR 분석 결과 내보내기 (썸네일 포함)
- **프레임 정확도**: FFmpeg 기반 정확한 프레임 단위 비디오 자르기

### 실시간 동기화
- OCR 리뷰 대화상자와 메인 윈도우 간 양방향 동기화
- 재생 위치, 세그먼트 선택, 프레임 탐색 실시간 업데이트
- 자세한 내용은 `SYNC_GUIDE.md` 및 `REALTIME_SYNC_GUIDE.md` 참조

## 아키텍처

### 모듈형 믹스인 디자인

애플리케이션은 `VideoPlayer`가 여러 전문화된 믹스인으로 구성되는 믹스인 기반 아키텍처를 사용합니다:

```python
class VideoPlayer(PlayerUpdateMixin, PlayerAnnotationsMixin, PlayerSidebarMixin, PlayerPlaybackMixin, VideoPlayerBase):
    pass
```

**주요 파일**:
- `yesoncheck/app.py` (355줄): 애플리케이션 부트스트랩 및 CLI 진입점 — 빌드 앱은 `setup_app_logging`이 stdout·stderr를
  창(프로세스)마다 기록 파일 `yesoncheck_<날짜>_<pid>.log`로(Mac `~/Library/Logs/YesonCheck`, Windows
  `%LOCALAPPDATA%\YesonCheck\logs` — update.log와 같은 폴더, 30일 지난 것은 켤 때 지움) 보내고 예외 창(`sys.excepthook`)을
  설치. 업데이트 중(다른 창이 넘긴 업데이트 — 도우미가 `--update-result`로 켠 앱은 빼고)에 켜면 창을 만들지 않고
  "업데이트 중입니다 — 끝난 뒤 다시 열어 주세요" 창만(8초 뒤 저절로 닫힘) 보이고 끝남
- `yesoncheck/main_window.py` (~10줄): 믹스인 구성
- `yesoncheck/player_base.py` (5,422줄): 핵심 UI 및 윈도우 관리
- `yesoncheck/player_playback.py` (2,575줄): 비디오 재생, 프레임 탐색 및 FFmpeg 작업
- `yesoncheck/player_sidebar.py` (1,831줄): 사이드바 UI, 썸네일 및 북마크
- `yesoncheck/player_review.py` (7,106줄): 3패널 레이아웃 및 세그먼트 편집 기능이 있는 OCR 리뷰 대화상자
- `yesoncheck/player_timeline.py` (840줄): 접을 수 있는 컨트롤이 있는 OCR 타임라인 위젯
- `yesoncheck/player_update.py` (1,408줄): 자동 업데이트 믹스인(`PlayerUpdateMixin`) — 확인 일정(켤 때 + 3시간마다
  + Help → 업데이트 확인…), 알림 띠 처리, '업데이트'를 누른 뒤 받기·다른 창 닫기·도우미에 넘기기, 다시 켜진 앱의 성공/실패
  판정 (여러 창일 때의 순서는 아래 '여러 창과 업데이트')
- `yesoncheck/video_widget.py` (~584줄): 줌, 팬, ROI 선택 기능이 있는 커스텀 비디오 뷰포트
- `yesoncheck/video_list.py` (~420줄): 사이드바 영상 목록 규칙 (job·폴더 읽기, 정렬, 다시 읽기 계획, 없어진 영상 판정 `check_gone`) — Qt 없음
- `yesoncheck/mac_mounts.py`: (Mac) 이 Mac에서 공유가 붙은 곳 — 자동 연결(autofs) 설정(`/etc/auto_master`와 간접 맵)과
  `/etc/fstab`을 읽어, 공유 설정의 앞부분(`/USA_DB`, path_map.json의 "mac", 제자리가 아닌 공유의 `/<이름>`)이 이 Mac에
  없으면 이름이 같은 공유를 열고, 제자리가 아닌 공유 아래 경로는 그 앞부분으로 되돌려 저장 (`paths.to_native`·`to_storage`
  등, 정하지 못하면 저장하지 않고 창). 시작할 때 `app.load_mount_map`이 공유 설정 폴더만, 공유 설정을 읽은 뒤 나머지를 정함
  — 로그 `[공유] /usadata2 → … (auto_nfs)` — Qt 없음
- `yesoncheck/workers.py` (3,465줄): OCR, 내보내기, 썸네일 및 씬 감지를 위한 백그라운드 스레드
- `yesoncheck/auto_trim.py` (637줄): 자동 씬 컷을 위한 PySceneDetect 통합
- `yesoncheck/transnetv2_detector.py` (698줄): 점진적 전환 감지를 위한 TransNetV2 통합
- `yesoncheck/web_info.py` (~330줄): OCR 분석 결과를 웹 페이지로 내보내기
- `yesoncheck/user_files.py` (208줄): 사용자 파일(JSON)을 여러 창이 함께 써도 안전하게 — `write_json_atomic`(같은 폴더의
  임시 파일 + `os.replace`, Windows는 다른 프로세스가 연 동안 다시 시도), `read_json`(깨진 파일은 `UserFileError` — 빈 값으로
  치고 덮어쓰지 않음), `FileLock`(같은 PC의 프로세스 사이 잠금 — NAS 위 파일에는 쓰지 않음), `update_json`(`<파일>.lock`을
  잡고 다시 읽기 → 고치기 → 원자적 쓰기) — Qt 없음
- `yesoncheck/bookmarks.py` (47줄): 북마크 `~/.yeson_bookmarks.json` — 더하기·지우기마다 파일을 다시 읽어 고침
  (`user_files.update_json`, 잠금 파일 `~/.yeson_bookmarks.json.lock`), 읽지 못하면 `UserFileError`(빈 목록으로 덮지 않음) — Qt 없음
- `yesoncheck/instances.py` (383줄): 창 기록 — 창(프로세스)마다 사용자별 기록 폴더(Mac `~/Library/Caches/YesonCheck/instances`,
  Windows `%LOCALAPPDATA%\YesonCheck\instances`)에 `<pid>.json`(pid·앱 자리·프로세스 시작 시각·연결 서버 이름). 창을 보인
  뒤 남기고 닫기 시작할 때·프로세스가 끝날 때 지움, `others()`가 같은 앱 자리의 다른 창을 세며 죽은 창(pid 없음·시작 시각
  다름)의 기록을 지움(지금 열 수 없는 기록은 그 번에 건너뜀). `other_user_processes`: 같은 앱 자리의 다른 사용자 프로세스
  (Mac `ps`, Windows `tasklist`) — Qt 없음
- `yesoncheck/instance_link.py` (199줄): 창 사이 연결 — 창마다 `QLocalServer`(`yesoncheck-<사용자>-<pid>`, 이 사용자만),
  한 줄 JSON 규약 `{"op":"status"}`(창 제목·영상·작업·저장 안 한 검토 결과) / `{"op":"close"}`(닫기 버튼과 같은 정상 종료
  — 열린 모달 대화 상자는 취소). 클라이언트 `query_status`·`request_close`는 시간 안에 답이 없으면 `InstanceLinkError`
- `yesoncheck/launch_args.py` (44줄): 켤 때 받은 인자 — `--update-result TOKEN`(도우미가 다시 켠 앱만 지난 업데이트를 판정),
  `--smoke-test DIR`, 나머지는 열 파일(경로 하나가 인자 하나 그대로) — Qt 없음
- `yesoncheck/review_sync.py` (97줄): OCR 검토 창 ↔ 웹 보고서 실시간 동기화 서버(`ReviewSyncServer`) — 창마다 127.0.0.1의 빈 포트와
  무작위 토큰(`ws://127.0.0.1:포트/?token=…`), 토큰이 맞지 않는 연결은 닫고 기록. 보고서는 그 주소(`generate_web_report`의
  `ws_url`)로만 접속하고, 주소가 없으면(듣기 실패) 접속하지 않고 "실시간 동기화 꺼짐"
- `yesoncheck/frame_utils.py` (~21줄): 영화 산업 표준 프레임 계산 (feet.frames 형식)
- `yesoncheck/styles.py` (~22줄): 커스텀 UI 스타일
- `yesoncheck/build_info.py` (89줄): 빌드가 앱에 넣은 `build_info.json`(버전·커밋·빌드 시각·플랫폼)을 읽어 창
  제목·Help → 정보에 보임 — 소스 실행이면 버전 "개발(소스)" — Qt 없음
- `yesoncheck/updates.py` (305줄): 업데이트 확인 핵심 — NAS·GitHub의 `latest.json`을 읽고 더 새 버전을 고름
  (예상된 실패와 오류를 구분, REST API는 쓰지 않음) — Qt 없음
- `yesoncheck/update_banner.py` (127줄): 창 맨 위 전체 너비 알림 띠(`UpdateBanner`) — 새 버전 알림·받는 중
  진행 막대·잠깐 메시지 세 가지 모양
- `yesoncheck/update_install.py` (839줄): 업데이트 설치 준비 — 받기(다운로드 + sha256 검사)·Mac dmg 준비
  (`hdiutil`+`ditto`)·업데이트 기록(`pending_update.json` — 무작위 토큰·건 창의 pid·도우미 pid)·도우미(아래) 띄우기·
  '업데이트 중' 판정(`update_in_progress`)·다시 켜진 앱의 결과 판정(`startup_result` — 토큰이 맞는 앱만) — Qt 없음
- `yesoncheck/update_helper_mac.sh` (666줄) / `yesoncheck/update_helper_windows.ps1` (1,118줄): 앱이 끝난 뒤
  별도 프로세스로 떠서, 같은 앱의 모든 프로세스(모든 사용자)가 끝나기를 기다렸다 새 버전으로 바꾸고 토큰과 함께 다시 켜며,
  잘 켜지지 않으면 자기가 켠 프로세스만 끝내고 옛 버전으로 되돌리는 도우미 스크립트

**외부 의존성**:
- `apted/`: OCR 텍스트 비교를 위한 트리 편집 거리 라이브러리

### 여러 창과 업데이트

한 프로세스에 창 하나 — 창을 더 열면 프로세스(앱)가 하나 더 뜬다. 여러 창이 함께 쓰는 것:
- 주석 파일(영상 옆 `.yesoncheck/<이름>_annotations.json`, NAS — Mac·Windows 모두): 저장할 때 디스크를 다시 읽어 항목 `id`로
  합치고(`frame_annotations.merge_annotations`) 원자적으로 씀. 지운 항목은 `deleted_ids`(묘비)에 남겨 다른 창의 옛 사본이
  되살리지 못하게. 옛 버전(1.1.x)은 `deleted_ids`를 모르고 파일을 통째로 다시 쓰므로 다른 창·PC의 주석을 지울 수 있음 —
  모든 PC가 새 버전이어야 안전.
- 북마크·오버레이 설정·주석 내보내기 폴더: 원자적 쓰기(`user_files`), 북마크는 잠금 안에서 다시 읽어 고침(`bookmarks`).
  읽지 못한 파일은 빈 값으로 치지 않고 창으로.
- 웹 보고서 동기화: 창마다 빈 포트 + 무작위 토큰(`review_sync`).
- 기록: 창마다 `yesoncheck_<날짜>_<pid>.log`, 업데이트 기록 `update.log`의 앱 줄에는 `[pid N]`.

업데이트 순서 (`player_update`, 도우미 — 설계 3-4):
1. [업데이트] → 뒤 스레드에서 다른 창 확인(띠에 "다른 창 확인 중…"): 같은 앱 자리에서 다른 사용자의 YesonCheck가 돌면
   "다른 사용자({user})가 YesonCheck를 쓰고 있어 업데이트할 수 없습니다"로 멈춤. 이 사용자의 다른 창(창 기록)에는 상태를 물음.
2. 다른 창이 있으면 확인 창 하나: "다른 YesonCheck 창 {n}개도 닫힙니다." + 작업 중인 창(이 창 포함)과 그 작업·"작업 중인
   창의 작업은 멈춥니다." + 저장 안 한 OCR·애니매틱 검토 결과가 있는 창·"닫으면 저장 안 한 결과는 사라집니다." + 응답 없는 창,
   [모두 닫고 업데이트] [취소]. 다른 창이 없으면 예전처럼 이 창의 작업만 물음.
3. 받기(진행·취소) → 넘기기 직전에 다시 셈: 다른 사용자가 켰으면 멈춤, 새로 작업·저장 안 한 결과가 생긴 창이 있으면 다시
   물음, 새로 켜진 빈 창은 묻지 않고 함께 닫음.
4. 다른 창마다 정상 종료 요청(`instance_link.request_close` — 닫기 버튼과 같음, 작업을 멈추고 열린 모달 대화 상자는 취소)
   → 창 기록이 아니라 프로세스가 끝나기를 기다림: 요청의 답을 받은 뒤 최대 `CLOSE_OTHERS_TIMEOUT_S`(약 90초 — 닫히는 창이
   작업 멈추기 `JOB_CLOSE_WAIT_MS`×작업 수 + 공유 설정 `SHARED_CONFIG_CLOSE_WAIT_MS` + 붙잡아 둔 작업 `EXIT_WAIT_S`를 기다리는
   합 + 여유). 그사이 새로 켜진 창도 닫음. 끝나지 않은 창이 있으면 받은 것을 지우고 "업데이트를 멈췄습니다 — 이 창이
   닫히지 않았습니다: …" — 앱은 그대로.
5. 업데이트 기록(`pending_update.json`, 무작위 토큰) → 도우미를 띄움(토큰을 넘김) → 기록에 도우미 pid → 도우미가 시작
   기록을 남기면 이 창이 끝남. 그때부터 새 버전이 '잘 켜짐'을 쓸 때까지 켜는 앱은 "업데이트 중입니다 — 끝난 뒤 다시 열어
   주세요" 창만 보이고 끝남(8초 뒤 저절로 닫힘 — 도우미의 기다림을 막지 않게).
6. 도우미: 건 창이 끝나기를 기다림 → 같은 앱 자리의 모든 사용자의 프로세스가 끝나기를 기다림(`YC_OTHERS_TIMEOUT`, 기본
   60초 — 넘거나 확인하지 못하면 바꾸지 않고 옛 앱을 다시 켬) → 바꿈 → `--update-result TOKEN`으로 다시 켬 → 그 앱만 결과를
   판정(띠에 "…로 업데이트했습니다" 또는 "업데이트 실패" 창). 되돌릴 때는 자기가 켠 프로세스만 끝냄(켜기 전부터 돌던 창 —
   업데이트 중에 사용자가 켠 창 — 은 건드리지 않음).
- 첫 적용: 업데이트는 켜져 있는 옛 앱의 도우미가 하므로 1.1.x → 이 버전 업데이트 전에는 다른 창을 모두 닫아야 함(배포 노트).
- 알고 둔 한계: OCR을 저장한 뒤 검토 창에서 더 고친 내용은 '저장 안 한 결과'로 표시되지 않음.

### 컴포넌트 역할

**VideoPlayerBase** (`player_base.py`):
- 메인 윈도우 초기화 및 UI 레이아웃
- 4K 최적화를 위한 프레임 캐싱 시스템
- 북마크 관리 및 작업 경로 설정
- 오버레이 텍스트 렌더링 및 표시
- 메뉴바 생성
- OCR 모드 선택 (King, Titmouse, Animatic, Animatic2)
- 핵심 재생 컨트롤 및 상태 표시

**PlayerPlaybackMixin** (`player_playback.py`):
- 비디오 파일 로딩 및 OpenCV 캡처 관리
- 프레임 단위 재생 및 탐색
- FFmpeg 비디오 병합 기능
- ffprobe를 통한 비디오 코덱 감지
- 재생 속도 및 오디오 제어
- 프레임 탐색 (다음/이전 프레임, 프레임으로 이동)

**PlayerSidebarMixin** (`player_sidebar.py`):
- 파일 브라우저 및 재생목록이 있는 사이드바 UI
- 썸네일 생성 및 캐싱
- 북마크 생성 및 탐색
- 파일 드래그 앤 드롭 처리
- 컨텍스트 메뉴 작업
- 작품 → 시즌 → job 순서 (시즌이 없는 The_Johnsons·TJS_Animatic은 작품 → job): 시즌을 고르기 전에는 job 목록이 'job선택'만,
  job을 고르기 전에는 영상 목록을 읽지 않음. 고른 것은 콤보의 `currentIndex() > 0`으로 판단 (`_picked`·`_job_picked` — 0번은
  안내 항목, -1은 비우는 중: clear가 빈 글자로 currentIndexChanged를 보냄)
- 목록 다시 읽기: 다른 앱에서 돌아올 때·같은 job을 다시 고를 때·새로고침 버튼(F5)·없는 영상을 열 때. 항목마다 들어온 곳
  (`SIDEBAR_SOURCE_ROLE`: job·폴더)을 기억하고 그 규칙(`video_list`)으로 뒤에서(`SidebarScan`) 다시 읽어 없어진 영상은 빼고
  새 영상은 넣음. 지워졌다는 근거가 있을 때만 뺌 (공유가 떨어진 것은 남기고 창으로 알림)
- 새로고침 버튼·F5(`_refresh_sidebar_by_user`): 썸네일 모드면 다시 읽은 결과를 넣은 뒤 모든 영상의 썸네일도 썸네일 버튼처럼
  확인 (`_check_thumbnails_after_refresh` → `_apply_disk_thumbnails`·`_make_thumbnails` — 같은 이름으로 다시 렌더링해
  썸네일보다 새 영상·없거나 읽을 수 없는 썸네일만 진행바와 함께 다시 만듦, 로그 `새로고침: 썸네일 확인 n개, 다시 만듦 m개`
  — m은 띄운 워커 수). 이번 읽기에서 확인하지 못한 영상(읽지 못한 목록 폴더·하위 폴더, 확인하지 못한 따로 넣은 파일)과
  화면에만 보이는(썸네일 폴더가 없는) 아이콘이 있는 영상은 건너뜀. 요청(`_sidebar_thumbnail_check_requested`)은 다음에 시작하는
  읽기에 실려(`SidebarScan.check_thumbnails`) 그 결과를 넣을 때 한 번: 읽는 중에 누르면 뒤이은 읽기에서, 결과를 버리고 다시
  읽으면(목록을 쓰는 중·폴더를 덧붙임) 요청으로 되돌림, 목록을 비우거나(job·폴더) 읽기가 예상 못 한 오류로 끝나면 버림.
  저절로 다시 읽을 때는 새 영상의 썸네일만
- 썸네일 반복(썸네일 버튼·새로고침·파일 넣기·`generate_thumbnail`의 기다림)은 목록이 바뀌거나 목록 모드로 바꾸거나 창을
  닫으면 멈춤 (`_thumbnail_pass_stopped`). 끝난 썸네일 워커는 그 finished를 받을 때만 목록에서 뺌 (먼저 놓으면 partial로 이은 failed 신호가 사라져 실패 창이 안 뜸)

**PlayerReviewMixin** (`player_review.py`):
- 3패널 레이아웃(씬 목록, 상세정보, 미리보기)이 있는 OCR 리뷰 대화상자
- 세그먼트 편집: 병합, 삭제, 이름 변경, 분할
- 자동 씬 이름 지정 및 이름 변경
- 프레임 정확도의 타임라인 시각화
- 품질 프리셋이 있는 내보내기 컨트롤
- 재생 중 실시간 미리보기 업데이트

**PlayerTimelineMixin** (`player_timeline.py`):
- 썸네일 미리보기가 있는 OCR 타임라인 위젯
- 더 나은 UX를 위한 접을 수 있는 컨트롤 패널
- 프레임 정확도의 세그먼트 탐색
- 세그먼트 경계에 대한 시각적 피드백
- ROI 종횡비 보존

**CustomVideoWidget** (`video_widget.py`):
- QGraphicsView를 사용한 비디오 프레임 렌더링
- 줌, 팬 및 윈도우에 맞추기 컨트롤
- A/B 비교를 위한 와이프 효과 (X/Y축)
- OCR을 위한 ROI(관심 영역) 선택
- 마우스 및 휠 이벤트 처리

**Workers** (`workers.py`):
- `OCRWorker`: PaddleOCR을 사용한 백그라운드 OCR 분석
- `OCRExportWorker`: FFmpeg 기반 세그먼트 내보내기
- `SceneDetectWorker`: 애니매틱 모드를 위한 PySceneDetect 래퍼
- `TransNetV2Worker`: 점진적 전환 감지가 있는 향상된 애니매틱 모드를 위한 TransNetV2 래퍼
- `ThumbnailWorker`: 캐싱이 있는 비동기 썸네일 생성
- `ThumbnailLoaderWorker`: 파일 브라우저를 위한 비동기 썸네일 로딩
- `FFmpegWorker`: 백그라운드 FFmpeg 비디오 병합 작업
- `SingleExportWorker`: 단일 세그먼트 내보내기
- `BatchExportWorker`: 다중 세그먼트 배치 내보내기

**씬 감지 모듈**:
- `auto_trim.py`: PySceneDetect 통합이 있는 OpenCV 기반 씬 감지
- `transnetv2_detector.py`: 하드 컷과 점진적 전환(디졸브, 페이드) 모두 감지하는 딥러닝 기반 씬 감지

**유틸리티 모듈**:
- `web_info.py`: OCR 분석 결과를 HTML 형식으로 내보내기 (썸네일, 세그먼트 정보, 통계 포함)

### OCR 분석 모드

**King 모드**: 빨간색 텍스트 최적화, 5배 업스케일, Scene-Panel 패턴 보정
**Titmouse 모드**: 표준 OCR, 2배 업스케일
**Bento 모드**: 표준 OCR (Titmouse와 유사)
**Animatic (Auto Cut) 모드**: 배경 변화 감지가 있는 PySceneDetect 기반 씬 컷 감지
**Animatic2 (TransNetV2) 모드**: 하드 컷과 점진적 전환(디졸브, 페이드) 모두 감지하도록 특별히 설계된 딥러닝 기반 씬 컷 감지

### 씬 감지 접근 방식

**PySceneDetect (Animatic 모드)**:
- OpenCV 기반 히스토그램 차이 감지
- 50% 히스토그램 가중치를 사용한 배경 변화 감지
- 오탐지를 피하기 위한 팬/줌 감지
- 설정 가능한 임계값 (기본값 0.15) 및 최소 씬 길이 (15프레임)
- ROI 선택 불필요

**TransNetV2 (Animatic2 모드)**:
- 딥러닝 기반 씬 경계 감지
- 하드 컷 감지 (급격한 씬 변화)
- 점진적 전환 감지 (디졸브, 페이드, 와이프)
- TensorFlow 2.15.1 사용 (빌드에 포함). 코드·가중치는 저장소에 있음 (`yesoncheck/transnetv2_model.py`, `vendor/transnetv2-weights/`)
- TensorFlow는 앱 시작 때 불러오지 않고 첫 애니매틱2 분석에서 불러옴 (불러온 모델은 프로세스 안에서 다시 씀)
- x86에서는 CPU가 AVX를 지원해야 함 (없으면 항목을 숨기고 시작 로그에 이유)
- 효율성을 위해 48x27 픽셀로 프레임 처리
- 설정 가능한 임계값 (기본값 0.5) 및 최소 씬 길이 (15프레임)
- ROI 선택 불필요
- 전문적인 편집과 전환이 있는 콘텐츠에 더 적합

### 비디오 내보내기 모드

**Fast 모드**: VideoToolbox 하드웨어 가속, 사용자 선택 가능한 비트레이트 (1000k-8000k)
**Quality 모드**: libx264 slower 프리셋, CRF 18
**Balanced 모드** (기본값): libx264 faster 프리셋, CRF 20

## PyInstaller 빌드 설정

`.spec` 파일에는 중요한 런타임 훅과 의존성 수집이 포함되어 있습니다:

**런타임 훅**:
- `pyi_rth_paddle_fixed.py`: PyInstaller용 PaddlePaddle의 `set_paddle_lib_path` 패치
- `pyi_rth_paddleocr_fixed.py`: PaddleOCR 패키지 검색을 위한 sys.path 수정

**의존성 수집**:
- PaddleOCR: 모든 Python 파일 및 도구 디렉토리 (`collect_all`을 통해 수집)
- PaddlePaddle: 모든 서브모듈 및 바이너리
- SciPy: 모든 서브모듈 (~1058 모듈)
- Cython: 유틸리티 디렉토리 파일
- scikit-image: morphology 모듈
- apted: 트리 편집 거리 라이브러리 (프로젝트 디렉토리에 번들)

- TensorFlow 2.15.1: pyinstaller-hooks-contrib의 hook-tensorflow가 수집, hiddenimports에 `yesoncheck.transnetv2_model`·`tensorflow`
- TransNetV2 가중치: spec이 `vendor/transnetv2-weights/`의 sha256을 확인하고 앱의 `transnetv2-weights/`에 넣음 (LICENSE·README.md 포함)

**제외된 의존성** (번들 크기를 줄이기 위해, spec의 excludes):
- torch, transformers, sklearn, matplotlib, sympy, nltk, librosa, pygame 등
- tensorboard, tensorflow_io_gcs_filesystem (TensorFlow가 끌어오지만 앱은 쓰지 않음. keras·h5py는 TF import에 필요해 둠)

## 프레임 계산 시스템

애플리케이션은 영화 산업 표준 프레임 계산을 사용합니다:
- 16 프레임 = 1 피트
- 형식: `feet.frames` (예: "5.08" = 5 피트, 8 프레임)
- 표시 형식: `5F 08f`

모든 프레임 계산은 `FrameCalculator.calculate_sheet_length(frames)`를 사용합니다.

## 성능 최적화

### OCR 리뷰 대화상자
OCR 리뷰 윈도우가 열려있을 때:
- 슬라이더 드래그 업데이트 간격 3배 증가
- 모든 프레임 대신 2프레임마다 재생 업데이트
- 오버레이 및 B-프레임 렌더링 건너뛰기
- 이미지 스케일링은 `FastTransformation` 사용
- 디바운스 처리: 미리보기 업데이트를 위한 50ms 지연
- 이미지 캐시: 최대 10개의 스케일된 이미지

### 비디오 재생
- LRU 프레임 캐시 (기본값 50 프레임)
- 4K 자동 감지 (비디오 너비 ≥1920px)
- 차이 임계값 기반 스마트 프레임 건너뛰기
- 하드웨어 가속 지원 (CUDA/OpenCL)

### OCR 분석
- 픽셀 차이 임계값 기반 프레임 건너뛰기
- 30프레임마다 또는 씬 번호 변경 시 강제 OCR
- 더 나은 텍스트 인식을 위한 히스토그램 평활화
- 빨간색 텍스트 최적화 (King 모드)

### 씬 감지
- PySceneDetect: 팬/줌 최적화가 있는 임계값 기반 배경 변화 감지
- TransNetV2: 딥러닝 모델이 효율성을 위해 다운샘플된 프레임(48x27) 처리
- 두 방법 모두 마이크로 컷을 피하기 위한 최소 씬 길이 필터링 지원

## 일반적인 개발 패턴

### 스레드 안전성
모든 QThread 워커는 시그널을 내보내기 전에 `_is_running`을 확인합니다:
```python
if not self._is_running:
    return
```

### Signal/Slot 연결
UI signal/slot 연결은 위젯 선언 근처에 중앙 집중화되어 있습니다. 스레드 연결 슬롯에는 `@pyqtSlot`을 사용하세요.

### 오류 처리
FFmpeg 오류는 디버깅을 위해 stdout/stderr를 캡처합니다:
```python
except subprocess.CalledProcessError as e:
    error_msg = f"FFmpeg error:\nCommand: {e.cmd}\nReturn code: {e.returncode}\nOutput: {e.stdout}\nError: {e.stderr}"
```

### 파일 경로 처리
FFmpeg 및 ffprobe 경로는 런타임 환경에 따라 감지됩니다:
```python
if hasattr(sys, '_MEIPASS'):  # PyInstaller 번들
    ffmpeg_path = os.path.join(sys._MEIPASS, 'ffmpeg')
else:  # 개발 환경
    ffmpeg_path = "ffmpeg"
```

### 애니매틱2(TransNetV2) 사용 가능 여부
`transnetv2_detector.transnetv2_missing()`이 TensorFlow를 불러오지 않고 확인합니다 (tensorflow find_spec, 가중치 세 파일,
x86이면 CPU AVX). `TRANSNETV2_AVAILABLE`이 False면 분석 방식 목록에서 애니매틱2를 숨기고 시작 로그에 이유를 남깁니다.
ImportError를 잡아 조용히 '없음'으로 처리하지 않습니다 (모듈 자체 오류는 그대로 드러나야 함).

## 테스트 전략

**자동화된 테스트는 존재하지 않습니다.** 수동 테스트는 다음을 포함해야 합니다:
1. 비디오 로딩 (작은 파일 및 4K)
2. A/B 비디오 비교 및 오버레이 컨트롤
3. OCR 분석 (King, Titmouse, Bento 모드)
4. 씬 감지 (PySceneDetect를 사용한 Animatic, TransNetV2를 사용한 Animatic2)
5. 세그먼트 편집 (병합, 삭제, 이름 변경, 분할, 자동 씬 이름 변경)
6. 비디오 내보내기 (Fast, Quality, Balanced 모드)
7. 단일 및 배치 세그먼트 내보내기
8. 웹 보고서 생성 및 내보내기
9. 썸네일 생성 및 캐싱
10. 북마크 생성 및 탐색
11. 프레임 탐색 및 재생
12. OCR 리뷰 대화상자와 메인 윈도우 간 실시간 동기화

씬 감지 테스트 시:
- 하드 컷이 포함된 콘텐츠로 Animatic 모드 테스트 (전통적인 편집)
- 디졸브, 페이드 또는 점진적 전환이 포함된 콘텐츠로 Animatic2 모드 테스트
- 최소 씬 길이 필터링이 올바르게 작동하는지 확인
- 다양한 콘텐츠 유형에 최적의 설정을 찾기 위해 다양한 임계값으로 테스트

내보내기 테스트 시:
- 다양한 품질 설정으로 단일 세그먼트 내보내기
- 다중 세그먼트 배치 내보내기 (진행 상황 추적 확인)
- 내보낸 비디오의 프레임 정확도 검증
- 웹 보고서 HTML 파일 생성 및 브라우저에서 열기

커밋 메시지나 PR 설명에 테스트 입력(파일 경로, OS, GPU, 씬 감지 매개변수)을 문서화하세요.

## 알려진 문제 및 제한사항

### 빌드 경고
- PaddleOCR ppstructure 모듈 경고는 무시 가능 (선택적 기능)
- macOS SDK 버전은 코드 서명 중 주의 필요
- .app 번들 호환성을 위해 `onedir` 모드 사용 필수 (`onefile` 아님)

### 성능
- 4K 비디오 처리는 메모리 사용량 증가
- 전체 비디오 OCR 분석은 시간이 많이 소요됨 (최적화하려면 프레임 단계 사용)
- VideoToolbox 하드웨어 가속은 macOS 전용
- TransNetV2는 모든 프레임을 미리 처리해야 하므로 단순한 하드 컷의 경우 PySceneDetect보다 느릴 수 있음

### 기능
- OCR은 현재 영어만 지원
- ROI 추적은 빠른 움직임이나 씬 변경 시 실패할 수 있음
- FFmpeg는 별도로 설치해야 함 (번들되지 않음)
- 애니매틱2(TransNetV2)는 TensorFlow·가중치가 없거나 x86 CPU에 AVX가 없으면 목록에서 숨김 (시작 로그에 이유)
- TransNetV2는 긴 비디오 처리를 위해 상당한 메모리 필요

## 파일 구성

### 설정 파일
- 북마크: `~/.yeson_bookmarks.json` (+ 잠금 파일 `~/.yeson_bookmarks.json.lock` — 지우지 않고 둠, `user_files.FileLock`)
- 오버레이 위치·크기: `~/.yeson_overlay_settings.json`, 주석 내보내기 폴더: `~/.yeson_annotation_export.json` (원자적 쓰기)
- 주석: 영상 옆 `.yesoncheck/<이름>_annotations.json` — 지운 항목의 id는 `deleted_ids`에 (위 '여러 창과 업데이트')
- 창 기록: Mac `~/Library/Caches/YesonCheck/instances/<pid>.json`, Windows `%LOCALAPPDATA%\YesonCheck\instances\<pid>.json`
  (`YESONCHECK_INSTANCES_DIR`로 바꿀 수 있음 — 시험용)
- 앱 기록(빌드 앱): Mac `~/Library/Logs/YesonCheck/yesoncheck_<날짜>_<pid>.log`, Windows
  `%LOCALAPPDATA%\YesonCheck\logs\yesoncheck_<날짜>_<pid>.log` — 같은 폴더에 업데이트 기록 `update.log`
- 업데이트 상태(받은 파일·`pending_update.json`·'잘 켜짐' 표시·도우미 복사본): Mac `~/Library/Caches/YesonCheck/updates`,
  Windows `%LOCALAPPDATA%\YesonCheck\updates`
- 작업 경로: `/USA_DB/test_jn/.yesoncheck/work_paths.json` (공유를 다른 곳에 붙인 Mac — 예: mac_b의
  `/System/Volumes/Data/mnt/USA_DB` — 은 `mac_mounts`로 찾은 곳. 못 찾으면 공유 설정 오류에 찾아본 내용이 붙음)
- 썸네일: job 폴더의 `.yesoncheck_thumb/<md5>.jpg` — 모든 Mac·Windows PC가 함께 씀 (`yesoncheck/thumbnails.py`).
  이름은 Mac 경로의 md5 (Windows도 변환표로 Mac 경로를 구해 같은 이름 → 서로 만든 썸네일을 씀, `paths.thumbnail_key`).
  영상이 썸네일보다 새것이면 다시 만듦. 저장은 임시 파일 + `os.replace`. Mac은 만든 폴더를 0o777로(다른 NAS 계정의
  Windows도 쓰게). 저장·폴더 문제와 만들기 실패(OpenCV가 열지 못함·예상 못 한 오류 — `ThumbnailWorker.failed`, 스택 트레이스째
  로그)는 썸네일을 쓸 때 (폴더, 제목)마다 한 번 창으로.

### 빌드 파일
- `YesonCheck_Autocut.spec`: PyInstaller 설정 (TransNetV2 및 PySceneDetect 포함)
- `Info.plist`: macOS 앱 번들 메타데이터
- `icon.icns`: 애플리케이션 아이콘
- `pyi_rth_paddle_fixed.py`, `pyi_rth_paddleocr_fixed.py`: PaddleOCR 런타임 훅
- `tools/write_build_info.py` (96줄): PyInstaller 앞에서 `build/build_info.json`(버전·커밋·빌드 시각·플랫폼)을
  만듦 — 버전은 git 태그 `vX.Y.Z` 기준 (BUILD.md 6절)
- `tools/release.py` (604줄): 배포 도구 — `prepare`(번호 정하기 → 주석 태그 푸시) · `publish`(CI 확인 → GitHub
  Release → NAS 복사) · `nas-sync` · `abort` (BUILD.md 7절)

### 문서
- `README.md`: 사용자 가이드 및 설정 지침
- `CLAUDE.md`: 개발자 문서 (이 파일)
- `AGENTS.md`: AI 에이전트 협업 가이드라인
- `TECH_SPEC.md`: 상세 기술 사양
- `SYNC_GUIDE.md`: OCR 리뷰 동기화 가이드
- `REALTIME_SYNC_GUIDE.md`: 실시간 동기화 구현 가이드

## 코드 스타일

- 4칸 들여쓰기로 PEP 8 준수
- 함수/변수: `snake_case`
- Qt 서브클래스: `CamelCase`
- 모듈 상수: `UPPERCASE`
- 지속된 설정에 매핑되지 않는 한 새로운 전역 상태 피하기
- 관련 믹스인 내에서 범위가 지정된 헬퍼 선호

## 개발 워크플로우

1. 관련 믹스인 또는 모듈에서 변경
2. `python -m yesoncheck.app`으로 테스트
3. 구문 검사 실행: `python -m compileall yesoncheck`
4. 다양한 비디오 형식 및 크기로 수동 테스트
5. UI 변경의 경우 OCR 리뷰 대화상자 성능 확인
6. 씬 감지 변경의 경우 하드 컷 및 점진적 전환 비디오 모두 테스트
7. 의존성 또는 빌드 설정 수정 시 번들 빌드 및 테스트

## 디버깅 팁

- 새 미디어 유형 추가 시 코덱 경고는 stdout 확인
- OCR 분석 로그는 팝업 대화상자에 표시 (상세 진행 상황)
- 씬 감지 로그는 프레임별 분석 표시 (TransNetV2는 컷 유형 분류 포함)
- FFmpeg stderr는 인코딩 진단 제공
- 프레임 캐시 통계 사용 가능: `cache_hits` 및 `cache_misses`
- ROI 좌표는 픽셀과 백분율로 모두 표시
- 애니매틱2를 숨기면 시작 로그에 `애니매틱2(TransNetV2) 항목 숨김 — 이 빌드/환경에 없는 것: [...]`
- 애니매틱2 분석 로그: `[애니매틱2 …] TensorFlow 불러오는 중…/불러옴 (n초)`, 모델 불러옴/다시 씀

## 새로운 씬 감지 방법 추가

새로운 씬 감지 방법을 추가하려면:

1. `yesoncheck/`에 새 모듈 생성 (예: `new_detector.py`)
2. 표준 형식으로 세그먼트를 반환하는 함수 구현:
   ```python
   def detect_scenes(video_path, ...) -> List[Dict]:
       return [{
           'start_frame': int,
           'end_frame': int,
           'start_time': float,
           'end_time': float,
           'duration': float,
           'text': str,
           'edited_text': str,
           'roi_preview': None,
           'detections': [],
       }, ...]
   ```
3. `workers.py`에 `QThread`를 상속하는 새 워커 클래스 추가
4. `player_base.py`에 새 모드 추가:
   - 새 모드를 포함하도록 `ocrModeComboBox` 업데이트
   - `start_ocr_analysis()`에 새 워커를 사용하는 조건부 로직 추가
5. 다양한 비디오 콘텐츠 유형으로 테스트

## 최근 변경 사항

### 2025-12-11
- **Spec 파일 업데이트**: `YesonCheck_Autocut.spec`으로 이름 변경 (자동 씬 컷 기능 강조)
- **Worker 확장**: `SingleExportWorker` 및 `BatchExportWorker` 추가로 내보내기 기능 개선
- **웹 내보내기**: `web_info.py` 모듈 추가로 OCR 분석 결과를 HTML 보고서로 내보내기
- **라인 수 업데이트**: 최신 코드베이스 반영 (총 ~21,898줄)

### 2025-11-21
- **관심사 분리**: `player_base.py`에서 OCR 리뷰 대화상자를 전용 모듈로 분리:
  - `player_review.py`: OCR 리뷰 대화상자 및 세그먼트 편집 로직
  - `player_timeline.py`: 타임라인 위젯 및 접을 수 있는 UI 컴포넌트
- **줄 수 감소**: `player_base.py`가 ~9,215줄에서 4,746줄로 감소 (48% 감소)
- **임포트 최적화**: 사용하지 않는 임포트 제거 및 의존성 정리
- **접을 수 있는 UI**: 타임라인 컨트롤이 더 나은 공간 관리를 위해 `CollapsibleBox` 위젯 사용
- **향상된 타임라인**: ROI 종횡비 보존으로 썸네일 미리보기 개선
- **Apted 통합**: 개선된 OCR 텍스트 비교를 위한 트리 편집 거리 라이브러리 추가

### 빌드 설정
- **Python 버전**: Python 3.10 (`~/coding/p310_tf` 가상 환경, `./setup_build_env.sh` — TensorFlow 2.15.1 포함)
- **Spec 파일**: TransNetV2 및 PySceneDetect 의존성을 포함한 `YesonCheck_Autocut.spec`
- **런타임 훅**: PaddleOCR 호환성을 위한 `_fixed` 변형 사용
