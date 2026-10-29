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

큰 파일은 믹스인을 부모로 붙여 나눔 (코드는 옮기기만 했고 동작은 그대로):
- `PlayerSidebarMixin`(`player_sidebar.py`)은 `SidebarBookmarksMixin`·`SidebarPlaylistMixin`·`SidebarConfigPathsMixin`·
  `SidebarRefreshMixin`·`SidebarSequencesMixin`·`SidebarAllMixin`·`SidebarThumbnailsMixin` 7개를 상속
- `VideoPlayerBase`(`player_base.py`)는 `PlayerOcrMixin`·`PlayerOverlayMixin` 2개와 `QMainWindow`를 상속

그래서 `VideoPlayer.__mro__`는 `VideoPlayer > PlayerUpdateMixin > PlayerAnnotationsMixin > PlayerSidebarMixin > SidebarBookmarksMixin >
SidebarPlaylistMixin > SidebarConfigPathsMixin > SidebarRefreshMixin > SidebarSequencesMixin > SidebarAllMixin > SidebarThumbnailsMixin > PlayerPlaybackMixin > VideoPlayerBase >
PlayerOcrMixin > PlayerOverlayMixin > QMainWindow …`. 이 구조에서 지킬 것:
- 같은 이름의 메서드를 두 믹스인에 두지 않음 (MRO에서 먼저 나오는 쪽이 가림 — `PlayerSidebarMixin`의 `dragEnterEvent`·`dropEvent`는 `QMainWindow`의 가상 함수를 가림).
  부모 믹스인 모듈(`sidebar_*`·`player_ocr`·`player_overlay`)은 상속받는 쪽(`player_sidebar`·`player_base`)을 모듈 수준에서 import하지 않음 (순환).
  상태(`self.…`)는 `VideoPlayerBase.__init__`이 만들고 믹스인은 `self.`로 부름.
- 시험이 모듈 전역을 바꿔치기할 때는 **그 이름을 읽는 코드가 있는 모듈**에서 바꿈 — 다른 모듈에 다시 내보낸 이름을 바꾸면 말없이 닿지 않음.
  예: `sidebar_thumbnails.ThumbnailWorker`·`shared_config_load.gather_shared_config`·`sidebar_config_paths.PathMapSetupDialog`·`ocr_worker.paddleocr_base_dir`.
- 옛 import 경로는 다시 내보내기로 남아 있음: `yesoncheck.workers`(워커 전부), `player_base`(`EXIT_WAIT_S`·`release_worker`·`wait_for_released_workers`),
  `player_sidebar`(`SidebarScan`·`ThumbnailContext`·`gather_shared_config` 등).

**주요 파일**:
- `yesoncheck/app.py` (402줄): 애플리케이션 부트스트랩 및 CLI 진입점 — 빌드 앱은 `setup_app_logging`이 stdout·stderr를
  창(프로세스)마다 기록 파일 `yesoncheck_<날짜>_<pid>.log`로(Mac `~/Library/Logs/YesonCheck`, Windows
  `%LOCALAPPDATA%\YesonCheck\logs` — update.log와 같은 폴더, 30일 지난 것은 켤 때 지움) 보내고 예외 창(`sys.excepthook`)을
  설치. 업데이트 중(다른 창이 넘긴 업데이트 — 도우미가 `--update-result`로 켠 앱은 빼고)에 켜면 창을 만들지 않고
  "업데이트 중입니다 — 끝난 뒤 다시 열어 주세요" 창만(8초 뒤 저절로 닫힘) 보이고 끝남. 받은 파일·Dock 클릭은
  `mac_app_events`가 받아 첫 파일은 이 창의 A(`open_startup_file` — 있는지 보지 않고 `open_file`로, 열지 못하면 그 오류 창), 나머지와
  켜진 뒤의 것은 새 창(`new_window`)으로 보내고, 창을 보인 뒤 Mac 빌드 앱은 처음 한 번 동영상 기본 앱을 묻고(`default_app`) Windows 빌드
  앱은 이 계정에 연결 프로그램을 등록(`file_associations`) —
  시작 순서는 아래 '여러 창과 업데이트'의 '새 창·동영상 열기·기본 앱'. 스플래시 전에 `movie_pipe_source.movie_source_mode()`를 한 번 불러
  `YESONCHECK_MOVIE_SOURCE`의 나쁜 값을 시작 때 ValueError로 멈춤
- `yesoncheck/main_window.py` (12줄): 믹스인 구성 (`VideoPlayer`)
- `yesoncheck/player_base.py` (1,873줄): 핵심 UI 및 윈도우 관리 — `VideoPlayerBase`(UI 만들기·메뉴·테마 전환·창 닫기·작업 정지·창 사이 연결).
  OCR 묶음은 `player_ocr`, 오버레이 묶음은 `player_overlay`로 나눠 부모로 붙였고, 스타일시트 문자열은 `main_window_styles`, 붙잡아 둔 워커 정리는
  `worker_lifecycle`로 옮김 (`worker_lifecycle`의 이름은 여기서 다시 내보냄)
- `yesoncheck/player_ocr.py` (1,845줄): `PlayerOcrMixin` — ROI·분석 방식 UI 상태, 분석 시작(OCR·애니매틱·애니매틱2)과 진행·완료 콜백, 검토 창 수명,
  결과 저장·불러오기, 구간 내보내기 (`VideoPlayerBase`의 부모)
- `yesoncheck/player_overlay.py` (753줄): `PlayerOverlayMixin` — 영상 위 오버레이 컨트롤(V 키)의 위젯·위치·크기·설정 파일(`~/.yeson_overlay_settings.json`)
  (`VideoPlayerBase`의 부모)
- `yesoncheck/main_window_styles.py` (940줄): 어두운·밝은 테마 시트(`DARK_STYLESHEET`·`LIGHT_STYLESHEET`)와 큰 인라인 시트 상수 — 데이터만 있는 잎 모듈
  (한 글자도 바뀌지 않게 `tests/test_stylesheet_freeze.py`가 해시로 지킴)
- `yesoncheck/worker_lifecycle.py` (76줄): 놓아 준 `QThread` 워커를 끝날 때까지 붙잡아 두기 — `release_worker`·`wait_for_released_workers`·`EXIT_WAIT_S`(30초)
- `yesoncheck/player_playback.py` (2,651줄): 비디오 재생, 프레임 탐색 및 FFmpeg 작업 — `_open_movie_capture`는 `os.stat` 확인 뒤·`cv2.VideoCapture` 앞에 ffmpeg 파이프 게이트(`maybe_pipe_capture`)를 끼움(아래 `movie_pipe_source`; 음성이면 기존 cv2 줄이 그대로 돎). `update_frame`은 그린 직후 `refresh_frame_annotations_display(redraw=False)`를 불러 같은 프레임을 두 번 그리지 않음 (틱당 `updateFrame` 2→1, 픽셀 동일 — 이 브랜치에서 기존 표시 코드를 바꾼 유일한 곳, 사용자 승인 예외; 드래그 + OCR 검토 창 분기는 앞 그림이 B를 뺀 그림이라 와이프가 켜져 있을 때만 다시 그림; 같은 패턴인 `_overlay_slider_ui_update`는 무변경; tests/test_display_single_draw.py) — 화살표·휠 프레임 이동 모두 오버레이(V 모드) 슬라이더를 함께 갱신(`_update_ui_fast`도 `update_overlay_controls`를 부름 — tests/test_overlay_slider_sync.py) — 전역 단축키(`keyPressEvent`): V(컨트롤 전체 숨김·오버레이), N/ㅜ(가운데 컨트롤 열 숨김 — `toggle_middle_panel`, V·전체화면 복원 뒤에도 유지)
- `yesoncheck/player_annotations.py` (1,073줄): 수정 사항 주석(프레임별 텍스트·도형) UI와 재생 연동 (`PlayerAnnotationsMixin`) — 주석 모드 버튼은 켜짐을 빨강으로 표시(`ANNOTATION_MODE_BUTTON_STYLE`). `refresh_frame_annotations_display(redraw=True)`·`_redraw_frame_with_annotations(draw=True)`: `False`면 다시 그리기만 빼고 목록·상태 라벨·편집 대상 갱신은 그대로
- `yesoncheck/player_sidebar.py` (555줄): `PlayerSidebarMixin` — 드롭·파일 넣기·폴더 불러오기, 우클릭 메뉴·파일 복사, 작품 → 시즌 → job 콤보,
  선택한 영상을 A에 열기. 나머지는 아래 부모 믹스인 모듈에 있고 이 모듈은 옛 import 경로를 위해 일부 이름을 다시 내보냄
  - `yesoncheck/sidebar_bookmarks.py` (216줄): `SidebarBookmarksMixin` — 북마크 읽기·더하기·지우기, 북마크 관리 창, 북마크 폴더 열기
  - `yesoncheck/sidebar_playlist.py` (202줄): `SidebarPlaylistMixin` — 선택 재생(Play Selected) 재생목록 시작·차례대로 열기·없는 영상 건너뛰기 (`_playlist_selection`: Mov 탭은 Mov 목록 선택, All 탭은 mov만)
  - `yesoncheck/sidebar_config_paths.py` (883줄): `SidebarConfigPathsMixin` — 공유 설정 읽기 시작·창에 넣기·문제 알림, (Windows) 변환표 자동 설정,
    작품 경로 관리 창·`get_work_path`·관리 비밀번호
  - `yesoncheck/sidebar_refresh.py` (496줄): `SidebarRefreshMixin`·`SidebarScan` — 목록 항목 모델(출처·세대·다시 읽기 보류)과 목록 다시 읽기·목록 문제 알림
  - `yesoncheck/sidebar_all.py` (206줄): `SidebarAllMixin` — All 탭(`self.all_sidebar`): Mov·Seq 목록을 복제(clone)해 한 목록에 이름 자연 정렬로 섞음(시퀀스 글자는 테마별 하늘색 `ALL_SEQ_FG`,
    종류는 `ALL_KIND_ROLE`). 원본 모델(rowsInserted·rowsRemoved·modelReset·dataChanged)이 바뀌면 보이는 동안만 미뤄서 통째로 다시 만듦 — All은 늘 파생, 원본에서만 고침(선택 재생 강조도 이 길로 따라옴).
    누르면 종류대로 A에 열고, 우클릭은 'Mov만 모두 선택' + 선택을 원본 목록에 비춘 뒤 그 종류의 기존 메뉴(`_build_sidebar_menu`·`_build_seq_menu`). 선택 재생은 `sidebar_playlist._playlist_selection`이 All 탭에서 mov만 고름(시퀀스 연속 재생은 메모리 한계로 안 함)
  - `yesoncheck/sidebar_sequences.py` (874줄): `SidebarSequencesMixin`·`SequenceExportDialog` — Mov·Seq·All 탭 전환과 Seq 목록, 끌어다 놓은 프레임 파일 처리, Seq 우클릭 메뉴(A/B로 열기·MOV 만들기·썸네일·정보),
    일괄 내보내기 진행 창. 시퀀스 썸네일은 짝 `.mov`의 것을 재사용
  - `yesoncheck/sidebar_thumbnails.py` (933줄): `SidebarThumbnailsMixin` — 목록/썸네일 모드·사이드바 폭, 썸네일 반복·워커 정리, 영상 단위 확인·만들기,
    썸네일 폴더·문제 알림, 백그라운드 썸네일 읽기
  - `yesoncheck/sidebar_items.py` (38줄): 사이드바 항목 상수(창 제목·안내 문구·항목 데이터 역할)와 `ThumbnailContext` — 잎 모듈
  - `yesoncheck/shared_config_load.py` (308줄): 공유 설정 읽기 코드 — `gather_shared_config`·`SharedConfigState`·`SharedConfigLoad`(`QThread`)·
    `list_works_not_opening`. 창·위젯을 건드리지 않음 (창에 넣는 일은 `SidebarConfigPathsMixin`)
- `yesoncheck/player_review.py` (7,032줄): 3패널 레이아웃 및 세그먼트 편집 기능이 있는 OCR 리뷰 대화상자 (`OCRReviewDialog`)
- `yesoncheck/player_timeline.py` (840줄): 접을 수 있는 컨트롤이 있는 OCR 타임라인 위젯 (`OCRTimelineWidget`·`CollapsibleBox`)
- `yesoncheck/player_update.py` (1,408줄): 자동 업데이트 믹스인(`PlayerUpdateMixin`) — 확인 일정(켤 때 + 3시간마다
  + Help → 업데이트 확인…), 알림 띠 처리, '업데이트'를 누른 뒤 받기·다른 창 닫기·도우미에 넘기기, 다시 켜진 앱의 성공/실패
  판정 (여러 창일 때의 순서는 아래 '여러 창과 업데이트')
- `yesoncheck/video_widget.py` (982줄): 줌, 팬, ROI 선택 기능이 있는 커스텀 비디오 뷰포트 — 주석 모드 동안 오른쪽 위에 '주석 모드' 배지(마우스 투과), 텍스트 입력 요청은 '텍스트' 도구에서만(도형 도구의 드래그 없는 클릭은 무시).
  **GL 뷰포트(Mac 전용)**: cocoa에서만 `QOpenGLWidget` 뷰포트가 기본 — 풀스크린 재생이 레티나 CPU 확대 블릿 때문에 13.5fps로 떨어지던 것을 GPU 확대로 24.8fps로 되돌림(창 모드는 동일 — 2026-10-28 실측). Windows는 풀스크린 저하가 없고(사용자 실측) offscreen(시험·CI)은 QOpenGLWidget 미지원이라 raster 그대로 — CI의 실행 시험·`ci/screenshot_check.py`도 전부 offscreen/windows라 GL 경로는 CI를 타지 않음(cocoa 실기 확인 몫).
  `YESONCHECK_VIEWPORT=gl|raster`로 명시 전환(그 밖의 값은 ValueError — 조용한 폴백 금지, `viewport_mode`; 시험은 `tests/conftest.py`가 이 변수를 지우고 시작). cocoa 기본 GL은 먼저 `gl_context_available`로 컨텍스트 생성을 확인하고, 실패하면 기록에 바로 남기고 raster로 계속하며 사유를 `viewport_fallback_reason`에 남김 — 오류 창은 `app.launch`가 스플래시를 닫은 뒤 `show_viewport_fallback`으로(위젯 생성 중 모달은 `splash.finish`의 processEvents 안에서 열려 시작 순서를 멈추고 업데이트 '잘 켜짐' 표시까지 늦춤). 조용한 빈 화면 금지; 토글로 강제한 GL은 확인 없이 그대로(`viewport_forced`). GL일 때 지키는 것(전부 실측 근거): ① 블록 위치 — `setAcceptDrops(True)` 뒤·줌/배지 라벨 생성 앞(`setViewport`가 새 뷰포트를 쌓임 맨 위에 둬서, 라벨이 뒤에 만들어져야 가려지지 않음 — hole punch) ② `setViewport`가 끄는 뷰포트 마우스 추적 다시 켬 ③ `FullViewportUpdate` ④ MSAA 4(GL2 엔진의 AA는 MSAA뿐 — 없으면 와이프 선·ROI·주석 미리보기가 계단짐; FPS 영향 없음 실측) ⑤ `WA_OpaquePaintEvent`(없으면 창 스타일시트 폴리시 뒤 풀스크린이 다시 16fps — 스타일시트 배경을 매 프레임 CPU로 칠하게 됨) ⑥ 영상 주변 여백은 스타일시트 대신 `backgroundBrush`로 테마 색을 GPU가 칠함(`apply_theme_background` — 창 생성과 `set_dark_theme`/`set_light_theme`가 부름, 색 `VIDEO_BG`는 시트의 테마 배경과 짝). 알고 둔 한계: GL 선 AA는 MSAA라 raster의 해석적 AA보다 거칢(눈 확인 통과 기준), `GL_MAX_TEXTURE_SIZE`(보통 16384) 초과 프레임은 미확인, raster를 골랐을 때는 로그가 없음(기록에 `[뷰포트] GL` 줄이 있으면 GL 경로), 컨텍스트 확인은 통과했는데 위젯 초기화(컨텍스트 공유·MSAA FBO)가 실패하는 드문 경우는 qWarning만 남음, GL이 안 되는 Mac은 창(프로세스)마다 폴백 알림이 뜸(조용히 넘기지 않는 쪽을 택함). 시험 `tests/test_gl_viewport.py`
- 이미지 시퀀스 (`<베이스>-NNNN.<확장자>` 프레임들을 영상처럼 열어 재생·비교, Seq 탭, 시퀀스 → MOV 일괄 만들기 — 사용자 설명은 README '이미지 시퀀스 재생'):
  - `yesoncheck/sequence_scan.py` (137줄): 파일 이름에서 시퀀스를 묶는 규칙 `group_sequences`·`SeqInfo`·프레임 이름 해석 `parse_frame_name`·한 프레임의 시퀀스 찾기 `sequence_of_frame`·여러 프레임용 색인 `FolderFrames` — Qt·디스크 없음. **시퀀스의 정체성은 가상 경로
    `<폴더>/<베이스>.seq`(`SeqInfo.identity`, `is_sequence_path`로 판별)**: 진짜 파일이 아니며 목록·`filename_a`·주석 파일 이름(`<베이스>_seq_annotations.json`)·
    창 제목이 모두 이 문자열을 씀. 시퀀스 경로를 `os.path.exists`·`cv2.VideoCapture`에 그대로 넘기지 말 것 (`open_any_capture`가 가름, OCR 류는 `is_sequence_active`로 막음)
  - `yesoncheck/sequence_source.py` (600줄): `decode_frame`(TGA·PNG·JPG·TIF는 PIL, EXR은 cv2)·`ImageSequenceCapture`(`cv2.VideoCapture` 자리에 꽂는 캡처, 선읽기 버퍼)·`open_any_capture`(`.seq` → 시퀀스 캡처, 아니면 `maybe_pipe_capture`가 파이프 캡처를 주고 음성이면 `cv2.VideoCapture`)
    **프레임 한 장 = 그 시퀀스**: `resolve_frame_path`/`find_frame_sequence`(폴더를 한 번 읽음, 프레임 이름이 아닌 경로·`.seq`는 읽지 않음, 없는 폴더는 None, 그 밖의 읽기 오류는 그대로 올림)가
    프레임 경로를 시퀀스 가상 경로로 바꿈. `open_file`(`_frame_to_sequence_path`)이 **모든 열기 길**(Open Video A/B 대화상자 — 필터가 없어 프레임도 고를 수 있음 —·끌어다 놓기·Finder 열기·다음으로 열기)에서
    mov·`.seq` 분기 앞에서 부르므로 `filename_a/_b`에는 늘 `.seq`가 들어감. 한 장뿐인 프레임(시퀀스 아님)은 예전처럼 영상 경로. 같은 base의 시퀀스가 여럿(다른 확장자·자릿수)이면 캡처가 여는 첫 묶음의
    프레임만 바꿈. 끌어다 놓기는 `SidebarSequencesMixin._dropped_frames`·`_add_dropped_frames`(영상 영역 `CustomVideoWidget.dropEvent`와 Mov 목록 `eventFilter`와 메인 창 `PlayerSidebarMixin.dropEvent`가 부름 — 영상 영역·창은 영상 파일처럼 A(둘이면 A·B)로 열고 Seq 탭을 보여 줌,
    Mov 목록은 Seq 목록에만 덧붙임, 영상 파일이 함께 있으면 영상은 예전대로). 폴더 목록은 `FolderFrames`로 한 번만 묶음(프레임마다 `group_sequences`를 부르면 장수의 제곱으로 느려져 5,000장 드롭이 30초 넘게 GUI를 얼림).
    **드롭 대상 (창 본문 핸들러)**: Qt는 드롭을 놓은 자리에서 위로 올라가며 `acceptDrops()`인 첫 위젯에 건넴 — 영상 영역(`CustomVideoWidget`)과 Mov 목록(`self.sidebar`, `eventFilter`가 DragEnter·Drop을 받음)은 자기가 받고,
    드롭을 받지 않는 위젯(Seq 목록·창 가장자리·컨트롤 영역)은 최상위 창 `VideoPlayer`(`setAcceptDrops(True)`, `dragEnterEvent`가 URL이면 수락)에 가서 `PlayerSidebarMixin.dropEvent`가 돎. 드롭은 한 위젯에만 건네지므로 두 번 처리되지 않음.
    `dropEvent`는 `self`가 `open_file`을 가진 창이면 self를 대상으로 씀 (예전에는 `self.parent()`로만 찾아서 최상위 창에서는 대상이 없어 본문이 한 번도 돌지 않았음 — 영상 파일·폴더·프레임 모두 말없이 무시). 본문은 `CustomVideoWidget.dropEvent`와 같은 코드이므로 한쪽을 고치면 다른 쪽도 고칠 것.
    시험은 실제 `QDropEvent`를 `player.dropEvent`에 건네고(`tests/test_sequence_frame_open.py`의 `drop_files(…, "window", …)`), 위젯 위 전달(Seq 목록·영상 영역·Mov 목록)은 `QApplication.sendEvent`로 DragEnter → DragMove → Drop을 보내(`deliver_drag`) Qt의 대상 고르기까지 지킴
    EXR: Windows cv2 휠은 OpenEXR 코덱이 기본으로 꺼져 있고 `OPENCV_IO_ENABLE_OPENEXR=1`은 **cv2를 불러오기 전에** 정해 두는 것이 안전함 — `yesoncheck/__init__.py`·`tests/conftest.py`·`check_frozen_imports.py`가
    맨 위에서 정함 (cv2를 부르는 새 진입점이 생기면 그보다 앞에). 그래도 꺼진 cv2면 `exr_supported()`가 False, `decode_frame(…, "exr")`는 원인을 이은 ValueError로 크게 실패 (EXR 시험은 이때만 건너뜀)
  - `yesoncheck/sequence_export_worker.py` (335줄): `SequenceExportWorker`(`QThread`) — 시퀀스 여러 개를 `<출력 폴더>/<베이스>.mov`로, `validate_out_dir`가 원본 폴더를 거부.
    읽지 못한 프레임을 직전 프레임으로 채운 수는 `ImageSequenceCapture.read_failure_count`로 세어 항목마다(`item_done`)·끝날 때(`substitutions`) 진행 창 로그와 콘솔에 알림 — 오류 아님(길이 보존, `finished` 나감)
  - `check_frozen_imports.py`가 TGA·EXR 한 장씩 `decode_frame`을 실행함 — PIL 플러그인은 지연 import라 동결 앱에서 빠져도 시험이 못 잡음 (cv2에 EXR이 꺼져 있으면 EXR만 건너뛰고 결과 줄에 적음)
- `yesoncheck/movie_pipe_source.py` (973줄): **ffmpeg 파이프 프레임 소스** — ProRes류 CFR mov를 번들 ffmpeg(`-f rawvideo -pix_fmt bgr24`, 출력 대상 `pipe:1` — 바이트가 오는 길은 아래 '전송')로 디코드해
  `cv2.VideoCapture` 자리에 꽂는 덕타이핑 캡처 `FFmpegPipeCapture`(`isOpened`·`read`·`get`·`set`·`release`, `ImageSequenceCapture`와 같은 계약)와 그것을 고르는 게이트.
  **왜**: 4K ProRes 4444(3840×2160 24fps)가 cv2로는 디코드만으로 22fps라 실시간에 못 미침. 원인은 cv2 내장 FFmpeg의 단일 스레드 픽셀 변환(12bit 4:4:4 → BGR)으로 **보임**(간접 실측 2026-10-29:
  번들 ffmpeg도 단일 스레드로 돌리면 8.5fps, cv2에 `OPENCV_FFMPEG_CAPTURE_OPTIONS="threads;0"`은 효과 없음 23.0fps) — 번들 ffmpeg의 디코드+bgr24 변환은 8코어를 써서 50.7fps(이 Mac Intel 8코어 실측;
  코덱·기계 탓이 아님 — 다른 재생기는 같은 파일을 실시간으로 틀었음). 새 의존성 없음(ffmpeg·ffprobe는 이미 번들, `external_tools` 경로).
  **앱 안에서의 실측(같은 Mac, 4K 4444 334장 처음부터 끝까지 재생)**: 처음 구현(stdout 파이프 전송) 22.0초(15.2fps) → 소켓 전송 18.54초(18.0fps) → 링 복사 이동·중복 그리기 제거 뒤 최종 **16.57초(20.2fps)**.
  1080p ProRes는 실시간, **4K는 이전보다 빨라졌지만 완전한 실시간이 아님** — 남은 병목은 표시 경로(아래 '알고 둔 한계' ⑦).
  - **게이트 `pipe_eligible(probe)`** (`probe_movie`가 ffprobe 1회로 `MovieProbe`를 읽음; **양성 증거로만 켜지는 opt-in** — 한 조건이라도 확인 못 하면 거짓): ① 코덱 `prores`(`PIPE_CODECS`)
    ② `r_frame_rate` 유효(0 < r ≤ 240)이고 `avg_frame_rate == r`(Fraction 등식) ③ nb_frames ≥ 1·크기 ≥ 1 ④ **정확 등식** `Fraction(nb_frames,1)/r == duration_ts × time_base`(프레임 수·길이·속도 삼자 일치)
    ⑤ 회전 0이고 화소 비율(SAR) 없음/1:1 ⑥ 영상 트랙·컨테이너 시작 시각이 유한한 값(0이 아니어도 됨 — 탐색이 오프셋을 보정). 어긋난 첫 조건을 `ineligible_reason`이 조건 번호와 함께 한 줄로 알려 줌.
    ④⑤가 필요한 이유(전부 경계 클립으로 재현한 실측): 느슨한 비율(0.5%) 판정은 편집 목록으로 앞 2장이 잘린 파일(nb_frames 120인데 실제 118장 — cv2·ffmpeg 동일)과 한 프레임이 길게 머무는 파일(avg가 r과 0.33%만 다름)을
    통과시켜 EOF 불변식이 매번 거짓 경보를 내거나 정지 프레임 뒤부터 탐색이 한 칸 일찍 착지함. 회전 메타(90°) 파일은 ffprobe가 320×180인데 cv2는 180×320을 줘서 바이트 수가 같은 채 reshape만 조용히 깨짐. h264 등 나머지와 게이트 음성 ProRes는 기존 cv2 줄이 그대로 돎.
  - **진입점**: `maybe_pipe_capture(path)` 한 함수가 모드·판정·캡처 생성을 묶고(양성이면 캡처, 음성이면 `None`), `sequence_source.open_any_capture`(주석 내보내기)와 `VideoPlayer._open_movie_capture`(영상 열기) 둘이 같은 함수를 부름 —
    판정 중복 금지. `_open_movie_capture`의 `PipeCaptureError`는 트레이스째 오류 창 + `None`(`_open_sequence_capture`처럼 보던 영상은 그대로), `open_any_capture`는 받지 않고 그대로 올리며 `AnnotationExportWorker.run`의 기존 `except Exception`이 받아 error 신호로 알림.
    **기존 재생·탐색 코드는 수정하지 않음**(사용자 최우선 제약: 기존 파일 재생 무회귀) — 바뀐 열기 경로는 `_open_movie_capture`의 삽입 분기와 `open_any_capture`의 한 호출뿐이고, 기존 표시 코드를 바꾼 유일한 곳은 사용자가 승인한
    `update_frame`의 중복 그리기 제거(위 `player_playback.py` 항목). OCR·씬 감지·썸네일 워커, OCR 검토 창·타임라인의 미리보기 캡처, 미디어 정보 창은 `cv2.VideoCapture`를 직접 열어 cv2 그대로(4K ProRes에서는 여전히 느림 — 필요해지면 별도 작업).
  - **토글 `YESONCHECK_MOVIE_SOURCE=auto|pipe|cv2`** (진단·킬 스위치, `YESONCHECK_VIEWPORT` 선례): 없거나 비면 `auto`, 대소문자 무시, 그 밖의 값은 ValueError(조용한 폴백 금지) — `app.launch`가 시작 때 한 번 `movie_source_mode()`로 검증(스플래시 전).
    `cv2`는 킬 스위치(probe도 하지 않고 1.5.0 동작 그대로). `pipe`는 ① 코덱만 면제하고 정확도 조건 ②~⑥은 유지 — 불통과면 열 때 `PipeCaptureError`로 크게 실패(어긋날 파일을 강제로 틀어 주지 않음),
    ffprobe가 파일을 못 읽어도 cv2로 조용히 가지 않고 같은 예외. 시험은 `tests/conftest.py`가 이 변수를 지우고 시작.
  - **로그**(print): 파이프를 골랐으면 `[재생] ffmpeg 파이프: <이름> (prores 3840×2160 24fps, 프레임 334)` — **기록에 이 줄이 있으면 파이프 경로**. 게이트 음성이면 `[재생] cv2: <이름> (파이프 아님 — ② 프레임 속도가 일정하지 않음 …)`처럼
    사유 한 줄. `auto`에서 ffprobe가 파일을 못 읽으면(`RuntimeError` — 깨진 파일·확인 불가) 스택 트레이스·stderr 전문을 남기고 cv2로 엶(cv2도 못 열면 기존 오류 창). `ToolNotFoundError`(번들 ffprobe 없음)·probe 해석 오류(`KeyError` 등 코드 버그)·
    캡처 생성의 `PipeCaptureError`는 잡지 않고 그대로 올림.
  - **ffmpeg 명령**(`_pipe_command`): `ffmpeg -nostdin -v error [-ss <t>] -i <파일> -map 0:V:0 -fps_mode passthrough -f rawvideo -pix_fmt bgr24 <출력>` — **`-fps_mode passthrough` 필수**(없으면 rawvideo가 CFR에 맞추려
    프레임을 복제해 섞음: 영상 start 0.5s 클립에서 파이프 132장 vs cv2 120장), **`-map 0:V:0`** 대문자 V(attached_pic 제외 — `probe_movie`가 고른 트랙과 같음; 소문자 `v:0`은 attached_pic을 포함). 경로는 인자 리스트 그대로(비ASCII 안전),
    Windows는 `subprocess_kwargs()`(CREATE_NO_WINDOW). 출력 대상은 POSIX `pipe:1`, Windows `tcp://127.0.0.1:<포트>?send_buffer_size=32768`.
  - **전송 — 왜 stdout 파이프가 아니라 소켓인가(실측)**: 처음에는 ffmpeg stdout 파이프를 읽었는데, 4K 한 장(24.9MB)이 64KB 파이프에서 ~467번의 read로 들어오고 호출마다 읽기 스레드가 GIL을 다시 잡아야 해서
    GUI 스레드가 파이썬을 실행 중이면(재생 틱의 `process_frame`·`update_frame`) 매번 switch interval(5ms)을 기다림 → 읽기 스레드 기아(메인이 GIL을 쥔 결정 실험에서 공급 28fps → 0.4fps, 실제 재생 15fps).
    소켓에서 `recv_into(..., MSG_WAITALL)`은 커널이 한 장을 다 채울 때까지 GIL을 놓은 채 syscall 한 번이라 **프레임당 recv 1회**(`recv_calls`로 시험이 구조 단언) — 메인이 GIL을 쥐고 있어도 공급이 유지됨.
    **POSIX**는 `socketpair(AF_UNIX)`의 한 끝을 ffmpeg의 stdout으로 넘김(명령의 출력 대상은 `pipe:1` 그대로; `Popen` 직후 부모에서 자식 쪽 끝을 닫아야 EOF가 옴). 측정(4K 정상 상태 60장, 메인 idle/40ms GIL 쥠):
    ffmpeg가 직접 여는 `unix://` 리스너 12~22fps(macOS 로컬 소켓 기본 버퍼가 8KB이고 ffmpeg unix 프로토콜에 버퍼 옵션이 없음), TCP 루프백 21~33fps, socketpair 30~43fps — 가장 빠르고 리스너·임시 폴더·경로 길이·접속 상대 확인이 없음.
    **Windows**는 socketpair 끝을 자식 stdout으로 넘길 수 없어(소켓 핸들은 CRT fd가 아님) 127.0.0.1 임시 포트 TCP 리스너에 ffmpeg가 접속(`accept`는 하나만, 상대가 127.0.0.1인지 확인, 대기 한도
    `CONNECT_TIMEOUT_S` = `READ_TIMEOUT_S`). **소켓은 blocking, 타임아웃 없음**: `settimeout`은 CPython이 내부적으로 non-blocking으로 바꾸는데 Windows는 non-blocking 소켓의 `MSG_WAITALL`을 거절하고
    (BSD는 첫 바이트까지만 적용) — 멈춘 ffmpeg 보호는 `take(READ_TIMEOUT_S)` 실패 → `stop()`의 shutdown+close+kill이 막힌 recv를 깨우는 길로. 버퍼 `SOCKET_BUFFER_BYTES` = 64KiB — 근거는 처리량뿐
    (8KB 26~29fps → 32KB부터 꺾여 34~39fps, 64KB·128KB·4MB는 잡음 수준이라 더 키워도 안 빨라짐; **Windows TCP의 절반씩(32K+32K)은 재 보지 않은 값**). 시험 `tests/test_movie_pipe_transport.py`는 Windows 경로를
    `sys.platform` 바꿔치기로 이 플랫폼에서도 돌림(Windows 실기는 CI).
  - **세션과 선읽기**: `_PipeSession` = ffmpeg 프로세스 하나 + 전송 소켓·읽기 스레드·stderr 스레드(상시 비움)·유한 큐·정지 플래그 한 덩어리. 탐색 재시작·`release`가 세션을 통째로 버려 옛 프로세스의 프레임·실패가 새 큐에 섞이지 않음. 소켓은 읽기 스레드만 읽음.
    선읽기 `READAHEAD_FRAMES=6` — 디코드와 표시를 떼어 프레임당 시간이 합이 아니라 max가 되게 하고 NAS 순간 끊김을 누그러뜨림; 큐가 비면 채워질 때까지 기다림(자연 감속, 프레임을 건너뛰지 않음).
    **링 보관본의 복사는 GUI 스레드가 아니라 읽기 스레드가 함**: 큐 항목은 (내줄 배열, 링 보관본) 쌍이고 `read()`는 보관본을 링에 옮기기만 해서 4K 24.9MB 복사가 GUI에서 사라짐(복사는 GIL을 놓는 numpy 복사). 보관본 버퍼는
    `_BufferPool`이 재활용(링이 밀어낸·비운 것과 정지한 세션 큐의 것이 돌아옴, 최대 16장 = 링 8 + 큐 6 + 2; 호출자에게 주는 배열은 늘 새 배열). 대가: 읽기 스레드가 한 장에 GIL을 한 번 더 잡고,
    4K 메모리가 늘어 **캡처당 큐 6쌍(프레임+보관본) ≈299MB + 링 8장 ≈199MB + 재활용 풀 → 약 550MB**(링 복사를 옮기기 전 ~350MB; 십진 MB, 4K bgr24 24.9MB/장 기준 — A/B 와이프에 4K 둘이면 ≈1.1GB). 스레드는 데몬, GUI 스레드는 무한 join하지 않음(NFS hard mount에서 kill해도 안 죽는
    프로세스는 데몬 스레드가 거둠). `weakref.finalize`가 `release` 없이 버려진 캡처의 ffmpeg를 끝냄. A/B 와이프는 ffmpeg 2개.
  - **탐색**: `set(CAP_PROP_POS_FRAMES, n)`은 **지연(lazy)** — 목표만 기록하고(cv2처럼 0~count로 자르고 소수 버림, `get`은 곧바로 그 값) 실제 이동은 다음 `read()` 머리에서: 제자리 → 링 버퍼 안(`KEEP_BEHIND=8`장 보관 —
    뒤로 한 칸이 재시작 없이; 없으면 4K에서 449~634ms로 cv2의 329~372ms보다 느려지는 실측 회귀) → 앞쪽 `SEEK_FORWARD_MAX=24`장 안이면 꺼내 버림 → 그 밖은 `-ss` 재시작(`SEEK_BACK_K=0`).
    **재시작 `-ss`는 `t = n/r + (영상 트랙 start − 컨테이너 start)`로 트랙 오프셋 보정 필수** — `-ss`는 컨테이너 start 기준이라 빼면 영상 start 0.5s 파일에서 12프레임 앞에 착지(`external_tools`의 선례와 같은 보정).
    연속 set(슬라이더 드래그)은 이동 한 번으로 합쳐지고, 곧 release될 캡처의 set(`stop_video` → `seek_to_frame(1)`)은 공짜. **링(8장)을 넘어 뒤로 가면 ← 한 번마다 재시작(~0.5초)** — 재시작한 세션의 링은
    그 자리에서 새로 시작하므로(슬라이더로 옮겨 온 바로 그 프레임에서 ←를 눌러도 마찬가지) 즉시인 것은 링에 남은 최근 장수 안뿐이고, 앞으로 가는 방향은 큐·스트림에서 이어짐.
  - **프레임 정확도(데이터 계약)**: 주석 JSON의 프레임 번호는 NAS에서 cv2 기반 옛 버전 PC와 함께 쓰고 OCR·씬 워커도 cv2라 "파이프 번호 = cv2 번호"가 깨지면 다른 PC·기능의 주석·구간이 어긋남. 위치는 자체 카운터(순차 전달이라 구조상 정확),
    전체 수는 ffprobe `nb_frames`(cv2 `FRAME_COUNT`와 같은 출처 — 실파일 334 일치), `get(FPS)`는 `float(avg)`(cv2와 같은 출처), 탐색 시각은 정확한 분수 r(병합용 `pick_frame_rate`의 표준값 스냅을 쓰면 2분대부터 반 프레임 어긋남).
    EOF 불변식: 정상 끝은 스트림 위치 == nb_frames에서의 EOF뿐 — 모자라거나 넘치면 도중 실패. 단 끝까지 재생해야 걸리므로 중간 어긋남의 실질 방어는 게이트와 시험.
  - **실패 처리(B 방식 — 사용자 확정)**: `PipeCaptureError`(원인·파일·명령·stderr 전문)는 **열 때만** 올라옴 — 생성자, 그리고 `pipe` 모드에서 게이트 불통과·ffprobe 실패일 때 `maybe_pipe_capture`가 직접 올림. 받는 곳은 `_open_movie_capture`의
    새 분기(오류 창)이고 `open_any_capture` 쪽은 위 '진입점'대로. 생성 뒤의 `read`·`get`·`set`은 예외를 내지 않음 — 도중 실패(프로세스 사망·프레임 중간에서 끊김·
    종료 코드 ≠ 0·EOF 수 불일치·`READ_TIMEOUT_S`=30초 동안 프레임 없음·재시작할 ffmpeg를 띄우지 못함)는 큐에 남은 정상 프레임을 다 준 뒤 캡처가 스스로 '죽음' 상태가 되고(죽은 cv2 캡처와 같은 겉모습: `read` `(False, None)`·`isOpened` False·`get` 0.0·`set` False)
    기록(stderr)에 **즉시 1회**(원인·읽던 곳의 호출 스택·명령·stderr 전문) + **Qt 루프에서 오류 창 1회**(`error_window.show_window` — 큐드 연결이라 재생 타이머 슬롯 안에서 모달을 열지 않음; QApplication이 없으면 기록만). 재생은 영상 끝에 닿은 것처럼 멈추고
    다시 열면 정상. **왜 호출처가 아니라 캡처 안에서 끝내나**: 기존 호출처 10여 곳이 read 예외를 삼키거나 print만 하고(매일 쓰는 h264 재생도 지나는 길이라 손대면 회귀 위험), 재생 타이머 슬롯 `next_frame_playback`은 try가 없어
    예외가 올라오면 소스 실행의 PyQt5가 프로세스를 abort함(exit 134 실측). `read()`는 한 번에 한 스레드만 부름(같은 캡처를 두 스레드가 동시에 read하는 건 미지원), `get`·`set`·`release`는 다른 스레드에서 불러도 됨.
  - **픽셀 동일성(스파이크 실측 2026-10-29, CI 세 플랫폼)**: 프레임 정렬(수·순서)은 전 플랫폼·전 클립 완벽. 바이트는 **4:4:4(4444·알파)가 세 플랫폼에서 cv2와 완전 동일**(실파일은 여기), **4:2:2는 Apple Silicon에서만 cv2 대비 ±4 레벨 이내**
    (단색 ±2, 색 경계 ±4 — chroma 보간의 CPU별 swscale 경로 차, 눈으로 구분 불가). 사용자 결정(2026-10-29): 4:2:2도 파이프에 포함 — 시험 기준은 4:4:4 = 바이트 완전 동일, 4:2:2 = 프레임 정렬 완벽 + 최대 차이 ≤ 5
    (`tests/prores_clips.py`의 `BYTE_EXACT`·`TOLERANCE_422`). 앱 의미: Apple Silicon에서 ProRes 422의 표시 색(주석 굽기 내보내기도)이 이전과 최대 4 레벨 다를 수 있음, 프레임 번호는 불변. bitexact 플래그는 cv2와 달라질 수 있어 안 씀(cv2 동일성 우선).
  - **시험 클립 함정**: CI Mac 러너의 cv2 디코드가 밝기를 레벨 ±2 틀어 버려(프레임 번호를 밝기 한 값에 그대로 실은 처음 방식이 깨짐) 번호를 회색 블록 두 개의 두 자리 수(`RADIX` 14·`STEP` 18 — ±8 레벨까지 견고)로 실음 — `tests/prores_clips.py`의 `frame_number`.
    정답은 늘 프레임에 그려 넣은 번호이고 cv2 픽셀에 기대지 않음(플랫폼 픽셀 차와 탐색 버그를 가르려고).
  - **알고 둔 한계**: ① 모든 영상 열기에 ffprobe 1회(~45ms, GUI 스레드·timeout 없음 — NAS가 멈추면 기존 `os.stat`과 같은 성질) ② 소스 실행에서 PATH에 ffmpeg·ffprobe가 없으면 h264 열기도 `ToolNotFoundError`(빌드 앱은 번들이라 해당 없음; `YESONCHECK_MOVIE_SOURCE=cv2`면 probe를 안 하므로 피함)
    ③ 파이프가 죽은 뒤 Play를 누르면 `get(FPS)`가 0이라 영상 타이머는 안 켜지지만 단추는 Pause로 바뀌고 소리 재생기는 시작함(오류 창은 이미 떴음 — 다시 열면 정상) ④ 죽은 캡처는 `release` 전까지 링 버퍼(4K ≈199MB)를 쥐고 있음
    ⑤ 1GbE 링크 PC는 4K ProRes 첫 재생이 네트워크 대역 한계(131MB/s 필요 — 이 Mac은 10GbE 실측이라 해당 없음, 2회째부터는 캐시) ⑥ 같은 캡처를 두 스레드가 동시에 read하는 건 미지원(계약)
    ⑦ **4K는 이 Mac에서 약 20fps(334장 16.57초)로 완전 실시간이 아님, Windows 4K는 표시 경로가 병목**: 남은 병목은 디코드가 아니라 4K `QPixmap`의 GL paint 48ms/프레임(`QImage`를 직접 그리면 24ms이고 그중 ~20ms는 33MB 텍스처 업로드 하한).
    raster 뷰포트는 107ms라 Windows(raster)의 4K는 paint만으로 약 8fps 수준(이 Mac에서 raster로 잰 값으로 본 추정 — Windows 실기 미측정). 1080p ProRes는 실시간.
  - **다음 후보 — 4K 표시 경로**: 직접 GL 텍스처 스트리밍(PBO 등)·Windows GL 뷰포트. `QPixmap` → `QImage` 직접 그리기는 틱이 약 41ms로 예산(41.7ms)에 걸쳐 확실한 실시간이 안 돼 사용자 결정으로 하지 않음. 근거 스크립트
    (`yc_paint_fmt_exp.py`·`yc_sock_exp.py`·`yc_pipe_read_exp.py`·`yc_microbench.py`)와 하니스(`profile_4k_playback.py`)는 내부(비공개) 저장소의 `docs/superpowers/records/2026-10-29-prores-pipe-design/`.
  - 빌드 앱 `yesoncheck/smoke_test.py`의 'ProRes 파이프 열기' 단계(`prores_pipe_open` — 번들 ffmpeg로 소형 ProRes mov를 만들어 `open_any_capture`로 열고 읽기·탐색, `YESONCHECK_MOVIE_SOURCE`가 auto가 아니면 실패): 빌드 앱의
    `_MEIPASS` ffmpeg와 Windows CREATE_NO_WINDOW 파이프가 실제로 실행되는 유일한 자리. 4K 실물 재생·탐색·와이프·주석은 CI가 못 보므로 눈 확인 몫 — 내부(비공개) 저장소의
    `docs/superpowers/records/2026-10-29-prores-pipe-design/eye-check.md`. 시험은 아래 '테스트 전략'.
- `yesoncheck/video_list.py` (427줄): 사이드바 영상 목록 규칙 (job·폴더 읽기, 정렬, 다시 읽기 계획, 없어진 영상 판정 `check_gone`) — Qt 없음
- `yesoncheck/mac_mounts.py`: (Mac) 이 Mac에서 공유가 붙은 곳 — 자동 연결(autofs) 설정(`/etc/auto_master`와 간접 맵)과
  `/etc/fstab`을 읽어, 공유 설정의 앞부분(`/USA_DB`, path_map.json의 "mac", 제자리가 아닌 공유의 `/<이름>`)이 이 Mac에
  없으면 이름이 같은 공유를 열고, 제자리가 아닌 공유 아래 경로는 그 앞부분으로 되돌려 저장 (`paths.to_native`·`to_storage`
  등, 정하지 못하면 저장하지 않고 창). 시작할 때 `app.load_mount_map`이 공유 설정 폴더만, 공유 설정을 읽은 뒤 나머지를 정함
  — 로그 `[공유] /usadata2 → … (auto_nfs)` — Qt 없음
- `yesoncheck/workers.py` (18줄): 옛 import 경로(`from yesoncheck.workers import X`)를 위해 아래 워커 모듈을 불러와 다시 내보내기만 하는 모듈 —
  워커 코드는 여기에 없음 (자세한 것은 아래 'Workers')
  - `yesoncheck/ocr_worker.py` (2,243줄): `OCRWorker`와 PaddleOCR 도우미 (`paddleocr_base_dir`·`use_ascii_paddleocr_dir`·`guard_paddle_buffer_growth`)
  - `yesoncheck/ocr_export_worker.py` (293줄): `OCRExportWorker`
  - `yesoncheck/scene_workers.py` (390줄): `SceneDetectWorker`·`TransNetV2Worker`
  - `yesoncheck/thumbnail_workers.py` (234줄): `ThumbnailWorker`·`ThumbnailLoaderWorker`
  - `yesoncheck/ffmpeg_worker.py` (60줄): `FFmpegWorker`
- `yesoncheck/auto_trim.py` (637줄): 자동 씬 컷을 위한 PySceneDetect 통합
- `yesoncheck/transnetv2_detector.py` (809줄): 점진적 전환 감지를 위한 TransNetV2 통합
- `yesoncheck/web_info.py` (2,647줄): OCR 분석 결과를 웹 페이지로 내보내기
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
- `yesoncheck/new_window.py` (71줄): 새 창 띄우기 `spawn(files)` — 창 하나가 프로세스 하나이므로 파일마다 새 앱 하나(빈 목록이면 파일
  없는 새 앱 하나). 셸을 쓰지 않아 경로 하나가 인자 하나 그대로(공백·한글·`'`·`#`도). Mac 빌드 앱은 `/usr/bin/open -n <자기 번들>
  [--args 파일]`(`-n`이 이미 떠 있는 같은 앱 대신 새 인스턴스를 띄움 — 앱 ID로 찾지 않고 자기 번들 경로로) 하고 `open`이 끝나기를
  `OPEN_TIMEOUT_S`(30초)까지 기다림(0이 아니거나 시간이 지나면 명령·출력이 든 `RuntimeError`). 소스 실행과 Windows 빌드 앱은
  프로세스를 바로 띄우고 기다리지 않음(Windows는 `PYINSTALLER_RESET_ENVIRONMENT=1`로 같은 exe를 새 앱으로). 실패(`OSError`·
  `RuntimeError`)는 감싸거나 삼키지 않고, 파일이 여럿일 때 한 파일이 실패하면 거기서 멈춤 — Qt 없음
- `yesoncheck/mac_app_events.py` (310줄): 파일 열기·앱 다시 열기를 새 창으로 — `install`(QApplication 바로 다음)이 Mac이면 `FileOpenRouter`를
  QApplication의 이벤트 필터(`QFileOpenEvent`)로 걸고, `ready(open_here)`(창을 보인 뒤)가 모아 둔 파일(시작 인자 + 시작 중 온
  이벤트, 받은 차례)의 첫 파일은 이 창의 A·나머지는 `new_window.spawn`, 그 뒤의 파일 열기는 이벤트마다 새 창. 같은 곳에서 Mac은
  `'aevt'/'rapp'`(kAEReopenApplication — Dock 클릭, 켜져 있을 때 Finder·Launchpad·Spotlight로 앱 다시 실행)를 받는 처리기를
  ctypes로 등록(`NSAppleEventManager`에 Objective-C 클래스 하나, PyObjC 없음) → `spawn([])`(빈 새 창). 실패는 바로 기록하고 오류 창은
  Qt 루프에서 `error_window`로(`_report_error`). 모듈 설명에 Step 1 실험(고른 방법·버린 방법·등록 시점·부작용)이 있음
- `yesoncheck/default_app.py` (494줄): Mac 동영상(.mov·.mp4) 기본 앱 — LaunchServices C API를 ctypes로(`LSCopyDefaultRoleHandlerForContentType`·
  `LSSetDefaultRoleHandlerForContentType`(`kLSRolesAll`)·`LSRegisterURL`·`LSCopyApplicationURLsForBundleIdentifier`, PyObjC 없음).
  `set_default`는 정한 뒤 두 종류를 역할 All과 Viewer(더블클릭 — `VERIFIED_ROLES`)로 다시 읽어 확인(OSStatus·다시 읽은 값을 모두 담은
  `DefaultAppError` — 조용한 성공 없음), `other_copies`는 같은 앱 ID의 다른 사본(알리기만, 지우지 않음), `should_ask`(순수 — 같은 두 역할),
  처음 켤 때 한 번 묻기(`asks_on_start`·`ask_at_start` — 다른 창이 열려 있으면 묻지 않음)
  와 Help 메뉴(`set_default_from_menu`), 답은 `prefs.json`에(`record_asked`) — 모듈 설명에 확인한 것(2026-10-21, macOS 26.2)과
  몬터레이에서 남은 것
- `yesoncheck/file_associations.py` (194줄): Windows 동영상 연결 프로그램 — `association_entries(exe)`(순수, HKCU의 12개 값: ProgID
  `YesonCheck.Video`·`.mov`/`.mp4`의 `OpenWithProgids`·`Applications\<exe>\SupportedTypes`·`Capabilities`·`RegisteredApplications`),
  `ensure_registered`(읽어서 없거나 다른 것만 쓰고, 쓴 것이 있으면 `SHChangeNotify`), `register_at_start`(빌드 Windows 앱이 켤 때 이 계정에
  등록), `open_default_apps_settings`(Help → "동영상 기본 앱 설정 열기…" — `ms-settings:defaultapps?registeredAppUser=YesonCheck`).
  `winreg`·`shell32`는 쓸 때 불러와 Mac에서도 모듈이 불림 — 설치 파일 `installer/yesoncheck.iss [Registry]`와 같은 내용(BUILD.md 8-2)
- `yesoncheck/error_window.py` (43줄): `default_app`·`file_associations`·`mac_app_events`·`player_base`(GL 뷰포트 폴백)가 함께 쓰는 오류 알림 — `show_error(prefix, text)`는 기록(stderr)에
  남기고 `show_window`: 앱의 예외 창(`sys.excepthook.dialog` = `app._ErrorDialog.show_text` — 기록 파일 경로를 붙이고 한 번에 하나만), 없으면(소스 실행)
  `QMessageBox.critical`; `show_unexpected`는 예외 처리 중에 트레이스백째(기록에는 전부, 창에는 `with_details` — 무엇이 실패했는지는 그대로, 트레이스백은 끝
  `DETAILS_LIMIT`(3000) 글자). 잡히지 않은 예외(`_ErrorDialog.show_error`)는 트레이스백만이라 끝 3000자
- `yesoncheck/review_sync.py` (97줄): OCR 검토 창 ↔ 웹 보고서 실시간 동기화 서버(`ReviewSyncServer`) — 창마다 127.0.0.1의 빈 포트와
  무작위 토큰(`ws://127.0.0.1:포트/?token=…`), 토큰이 맞지 않는 연결은 닫고 기록. 보고서는 그 주소(`generate_web_report`의
  `ws_url`)로만 접속하고, 주소가 없으면(듣기 실패) 접속하지 않고 "실시간 동기화 꺼짐"
- `yesoncheck/frame_utils.py` (21줄): 영화 산업 표준 프레임 계산 (feet.frames 형식)
- `yesoncheck/build_info.py` (89줄): 빌드가 앱에 넣은 `build_info.json`(버전·커밋·빌드 시각·플랫폼)을 읽어 창
  제목·Help → 정보에 보임 — 소스 실행이면 버전 "개발(소스)" — Qt 없음
- `yesoncheck/updates.py` (308줄): 업데이트 확인 핵심 — NAS·GitHub의 `latest.json`을 읽고 더 새 버전을 고름
  (예상된 실패와 오류를 구분, REST API는 쓰지 않음) — Qt 없음
- `yesoncheck/update_banner.py` (129줄): 창 맨 위 전체 너비 알림 띠(`UpdateBanner`) — 새 버전 알림·받는 중
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

### 새 창 · 동영상 열기 · 기본 앱 (설계 3-1~3-3)

새 창 = 새 프로세스(`new_window.spawn`). 들어오는 길은 셋이고 모두 `mac_app_events`의 라우터가 모아 `app.launch`가 넘긴 콜백으로 보냄:
- **명령 줄 인자**(`launch_args.parse`의 `files`): Mac 빌드 앱은 PyInstaller `argv_emulation`이 시작 때의 'odoc'을 먹고 파일을 argv에
  붙임(NFD 한글·링크 푼 경로 — `/tmp`는 `/private/tmp`로. 부트로더가 URL을 `CFStringGetFileSystemRepresentation`으로 바꾸며 이름을 분해함). Windows는
  연결 프로그램 명령 `"<exe>" "%1"`(탐색기는 보통 파일마다 한 번 부름 — 한 명령으로 여럿을 받아도 첫 파일은 이 창, 나머지는 새 창).
- **`QFileOpenEvent`**(Mac, Finder 더블클릭·다음으로 열기): ready 전(시작 중)에는 모아 두었다가 첫 파일은 이 창의 A·나머지는 새 창, ready 뒤에는
  이벤트마다 새 창 — 이 창이나 다른 창에 열린 영상이어도 무조건 새 창. 시작 인자와 같은 파일의 이벤트는 시작 중에만 인자 하나당 하나
  흡수(키 = NFC + realpath, `path_key`) — 실험에서 중복은 한 번도 없었고 안전망일 뿐.
- **reopen**(Mac `'aevt'/'rapp'` — Dock 클릭, 켜져 있을 때 Finder·Launchpad·Spotlight로 앱 실행): 빈 새 창(`spawn([])`). AppleScript
  `activate`·⌘Tab·창 클릭·Mission Control은 rapp를 보내지 않아 새 창이 안 뜸. **모든 창(프로세스)이 처리기를 등록**해야 함 — Dock 타일은
  프로세스마다 하나씩이고 타일은 자기 프로세스에만, `open -a`는 먼저 켜진 프로세스에 rapp를 보냄. `open -n <번들> --args 파일`(새 창 띄우기)은
  새 프로세스의 argv로만 가고 옛 프로세스에는 아무 이벤트도 없음.

콜백(`open_here`·`on_open_files`·`on_reopen`)은 Qt 루프에서(`QTimer.singleShot(0)`) 불림 — Apple Event 처리·이벤트 필터 안에서 `open`이 끝나기(Mac
`spawn`, 최대 30초)를 기다리지 않게. 실패하면 바로 기록(stderr — 빌드 앱은 기록 파일)에 트레이스백(`new_window`의 `RuntimeError`면 명령·출력)을 남기고,
오류 창은 Qt 루프에서 `error_window`로(빌드 앱은 앱의 예외 창 — 기록 파일 경로, 한 번에 하나만) — 이 창은 그대로. 알리다 또 실패하면 `sys.__stderr__`에
(`_last_resort` — eventFilter·IMP·Qt 루프 밖으로 내보내지 않음).

받은 첫 파일(`open_here` = `app.open_startup_file`)은 있는지 보지 않고 `player.open_file("A", …)`로 — 열지 못하면 `open_file`이 무엇을 왜 못 열었는지 오류 창
(디스크에 없음·확인하지 못함(NAS 연결 끊김·권한)·OpenCV가 읽지 못함 — 설계 3-2), 창은 그대로. 받은 경로가 그대로는 없으면 `paths.find_unicode_variant`가
이름의 정규화(NFC·NFD)만 다른 실제 경로를 찾아 그것으로 엶: NFS 공유는 이름을 바이트 그대로 비교해 NFC로 저장된 폴더(Windows·NAS에서 만든 것)의 NFD 경로는
없다고 나옴(로컬 APFS·SMB는 가리지 않음 — 2026-10-22 이 Mac의 NFS 공유에서 확인). 이름마다 위 폴더 목록에서 NFC가 같은 이름을 하나만 찾음(둘 이상이면 고르지 않음).

**시작 순서 (`app.launch`) — 순서를 바꾸면 말없이 깨진다**:
1. `QApplication`을 만든 **바로 다음** `mac_app_events.install` — 업데이트 확인 창·스플래시의 `processEvents`보다 먼저. 늦게 달면 그사이 온
   `QFileOpenEvent`가 말없이 사라짐(실험에서 2/2).
2. 업데이트 중이면(`update_in_progress_at_start`, 도우미가 켠 앱은 빼고) 창 없이 "업데이트 중" 창만 보이고 끝 — 그때 받은 파일은 열지 않고 기록.
3. `load_mount_map` → 스플래시 + `processEvents`(여기서 AppKit `-[NSApplication finishLaunching]`이 자기 'rapp' 처리기를 등록) → `VideoPlayer` → `show()`.
4. `QTimer.singleShot(0)`로 줄 세운 시작 일: 지난 업데이트 결과 판정(끝나면 동영상 기본 앱 묻기를 줄 맨 뒤에 세움) → 창 기록·연결 서버 → 사용자 파일
   문제 → GL 뷰포트 폴백 알림(`show_viewport_fallback` — 위젯 생성 중 모달 금지) → 공유 설정 읽기 → (Windows 빌드 앱) 연결 프로그램 등록.
5. `router.ready(open_here)` — 4의 일이 하나도 돌기 전에 launch 안에서 **동기로** 불림: 받은 첫 파일 열기(나머지 파일은 새 창)를 4의 일 뒤에 줄 세움.
   그래서 실제로 도는 차례는 4의 일 → 받은 첫 파일 열기 → (Mac 빌드 앱, `--update-result`로 켠 앱은 건너뜀) 동영상 기본 앱 묻기(창 기록이 이미 남아 있어
   다른 창이 이 창을 셈). 창을 보인 **뒤** Mac은 여기서 reopen 처리기를 **동기로** 등록(`register_reopen_handler`). 그 전에(`finishLaunching` 전)
   등록하면 AppKit이 **오류 없이 덮어써서** 콜백이 0번이고 덮였는지 알려 주는 API도 없음 — Dock 클릭에 새 창이 안 뜨고 최소화한 창이 올라오면 이 증상.
   `tests/test_mac_app_events.py`의 `test_launch_installs_router_first_and_readies_after_window_is_shown` 등이 순서를 지킴.

**Mac 기본 앱** (`default_app`):
- Info.plist의 `CFBundleDocumentTypes`(spec, `LSHandlerRank: Alternate`)가 "다음으로 열기"에 늘 보이게 함(BUILD.md 8-1). 더블클릭으로 여는 기본 앱은 이 모듈이 정함.
- 처음 켤 때 한 번(`asks_on_start` → `ask_at_start`, 빌드한 Mac 앱만): `prefs.json`에 답이 있으면 LaunchServices도 보지 않고 끝 → dmg(`/Volumes`)·
  같은 앱 자리의 다른 창이 열려 있으면(`instances.others` — 그 창이 묻고 있을 수 있음) 묻지도 기록하지도 않음(창 하나만 켜질 때 물음 — 답하기 전에 여러 파일·
  Dock 클릭으로 띄운 창마다 질문이 쌓이지 않게) → `AppTranslocation`이면 묻지도 기록하지도 않음(`location_problem`) → 두 종류가 두 역할(All·Viewer) 모두
  YesonCheck면 묻지도 기록하지도 않음(답한 것이 아님) →
  `ASK_TEXT` [예]/[아니요]. **단추를 누른 것만** 기록함 — Esc·⌘.(`_AskBox.keyPressEvent`가 `reject()`), 다른 창의 업데이트가 건 닫기 요청
  (`player_base.close_for_update`가 열린 대화 상자를 `reject()`), 앱 끝내기·로그아웃의 창 닫기는 답이 아님(다음에 켤 때 다시 물음). Qt 기본은 Esc가 탈출
  단추 [아니요]를 누르고 창 닫기도 `exec_()` 결과를 [아니요]로 두므로 `buttonClicked`로 직접 확인함. [아니요]는 탈출 단추로 남겨 둠(없으면
  `QMessageBox`가 창 닫기를 무시해 앱 끝내기·로그아웃이 막힘).
- `set_default`: `LSRegisterURL`(이 번들 등록) → 종류마다 `LSSetDefaultRoleHandlerForContentType`(`kLSRolesAll`) → 둘 다 역할 All과 Viewer로 다시 읽어 앱 ID
  확인(Viewer만 다른 앱이어도 실패 — Viewer를 따로 정하지는 않음). 한 종류가 실패해도 다른
  종류는 정하고 실패를 모두 담아 `DefaultAppError`. 이후 `other_copies`가 같은 앱 ID의 다른 사본을 알림(지우지 않음).
- 오류: 예상된 실패(`DefaultAppError`, prefs.json의 `UserFileError`)는 무엇이 왜인지 오류 창(트레이스백 없이), 예상 못 한 예외는 기록과 오류 창에 트레이스백
  (`error_window`). 소스 실행·dmg/격리 위치의 Help 항목은 안내 창만.

**Windows 연결 프로그램** (`file_associations`): HKCU 등록 12개 값(BUILD.md 8-2)을 `.iss [Registry]`(설치한 계정)와 `register_at_start`(켤 때, 빌드한 Windows 앱만 —
다른 계정·옮긴 설치 경로)가 같은 내용으로 씀. Help → "동영상 기본 앱 설정 열기…" = `os.startfile("ms-settings:defaultapps?registeredAppUser=YesonCheck")`.
시험은 레지스트리(`reg=`)·알림(`notify=`)·`_open_uri`를 바꿔 끼워 Mac에서도 돎 — 설치·제거가 실제로 쓰고 지운 값은 CI가 레지스트리를 다시 읽어 확인.

**함정** (이 기능을 만들며 겪은 것 — 다시 밟지 말 것):
- **PyQt5는 `eventFilter` 같은 가상 함수에서 빠져나간 예외로 프로세스를 끝낸다**(`qFatal` → SIGABRT, 오류 창 없음). 그래서 `FileOpenRouter.eventFilter`와
  Qt 루프로 미룬 콜백(`_run_guarded`)은 본문 전체를 `except BaseException`으로 잡아 같은 방법으로 보임(그 알림이 또 실패해도 `_last_resort`가 `sys.__stderr__`에 —
  밖으로 내보내지 않음). 같은 이유로 PyQt5가 감싸지 않는
  `QApplicationStateChangeEvent`의 `ev.applicationState()`는 `AttributeError`(상태가 필요하면 `QApplication.applicationState()`), `QFileOpenEvent`는
  만들 수도 없어(`TypeError`) 시험은 같은 모양(type·file·url)의 대역을 필터에 건넴.
- **ctypes 콜백(IMP)에서 빠져나간 예외는 `Exception ignored on calling ctypes callback function` 한 줄만 남기고 사라짐** — `_ReopenHandler._imp`가 직접 잡아 오류 창으로.
- `objc_msgSend`는 가변 인자로 부르지 않음(arm64에서 인자가 깨짐) — 호출 모양마다 인자·반환 형을 정한 `CFUNCTYPE`을 그 주소로. `AEEventClass`·`AEEventID`는
  `c_uint32`. 처리기 클래스 `YesonCheckReopenHandler`는 이름당 한 번만 만들 수 있어 프로세스에 하나이고, `NSAppleEventManager`는 처리기를 붙잡아 주지 않으므로
  객체와 IMP(CFUNCTYPE)를 놓지 않음.
- **처리기를 바꾸면 AppKit 기본 reopen 처리가 통째로 사라짐**: 최소화한 창을 올리지 않음(원하는 것). 그리고 Qt의 `applicationShouldHandleReopen`이 불리지 않아 Dock 클릭
  때의 강제 `applicationStateChanged(ApplicationActive)`도 없음 — 사이드바 다시 읽기(`sidebar_refresh`의 `_on_application_state_changed`)가 이 신호를 쓰지만 다른 앱에서 돌아오는
  평범한 `Inactive→Active`는 그대로라 유지됨(아래 한계).
- **LaunchServices가 돌려주는 앱 ID는 소문자일 수 있음**(Info.plist의 대문자가 섞인 앱 ID가 저장 파일에는 소문자로 있음을 확인) — 비교는 대소문자 무관(`_same_app`).
- **임시 폴더(`/tmp` 등)의 번들은 LaunchServices가 `in-temp-dir`로 표시해 앱 ID로 찾지 않음**: 정하기는 OSStatus 0인데 다시 읽으면 다른 앱, 사본 목록도 빔 —
  다시 읽어 확인하기 때문에 `DefaultAppError`로 드러남(조용한 성공 없음). 기본 앱을 시험하려면 홈 폴더나 Applications에 둔 번들로.
- `set_default`는 `kLSRolesAll`(Finder의 '정보 가져오기 → 모두 변경'과 같은 항목)로 정하고, 확인(`set_default`·`should_ask`)은 All과 Viewer(더블클릭이 여는 역할)
  둘로 읽음(`VERIFIED_ROLES`) — 다른 앱이 Viewer 역할만 따로 지정돼 남아 있으면 All만 봐서는 통과해도 더블클릭은 그 앱을 열므로 `DefaultAppError`. 그런 항목이 실제로
  생기는지는 확인한 적 없고, Viewer를 따로 정하지는 않음. 진짜 Mac의 기본 앱으로 시험하고 원래대로
  되돌릴 때도 같은 역할로 하면, 원래 명시한 항목이 없던 종류에는 그때의 기본 앱이 명시 항목으로 남음(항목을 지우는 API 없음). LaunchServices C API는 26.2 SDK에서
  "앞으로 deprecated"(`API_TO_BE_DEPRECATED`)일 뿐 있고 12.3~최신에서 동기로 돎(대안 NSWorkspace는 Objective-C 블록·비동기).
- **버튼 슬롯이 박스를 붙잡으면 순환 GC가 박스를 아무 때나(다른 이벤트 처리 중) 지워 크래시** — `_ask`는 `box.buttonClicked.connect(pressed.append)`로 박스를
  참조하지 않고 `box.deleteLater()`로 끝냄(다음 시험의 `app.launch`에서 간헐 세그폴트가 났었음).
- Windows에서 같은 exe로 새 창을 띄울 때 `PYINSTALLER_RESET_ENVIRONMENT=1`을 줘야 함(`update_install._helper_env`와 같은 이유 — PyInstaller 6.9+는 `_PYI_*`를 물려받은
  같은 exe를 부모의 하위 프로세스로 봄). `installer/yesoncheck.iss`는 **UTF-8 + BOM** 유지(한글 값 — BUILD.md 8-2).
- 소스 실행(`python -m yesoncheck.app`)의 Dock 타일 이름은 'python' — 그 클릭으로도 처리기가 불리지만 `open -a`로 소스 실행을 가리킬 수는 없음.

**알고 둔 한계**:
- 이미 맨 앞인 창의 Dock 아이콘을 누르면 이제 새 창이 뜸 — 예전에는 사이드바를 다시 읽었음. 다른 앱에서 돌아올 때의 다시 읽기는 그대로(새로고침 버튼·F5도).
- 이미 닫히는 중인 창(작업을 멈추고 기다리는 동안, 최대 약 30초)에 간 reopen은 아무것도 하지 않음 — 그동안 Dock 클릭·앱 다시 실행은 새 창을 못 띄움. 같은 때
  그 프로세스로 간 동영상 더블클릭·다음으로 열기(macOS는 켜져 있는 YesonCheck에 'odoc'을 보냄)도 열리지 않고 사라짐 — 오류 창도 없음. 확인한 경로: `app.exec_()`가
  끝난 뒤 `finish_released_workers`가 붙잡아 둔 작업을 최대 `EXIT_WAIT_S`(30초) 기다리는 동안은 Qt 루프가 없어 미룬 콜백(`QTimer.singleShot(0)`)도 이벤트 필터도
  돌지 않음.
- 창을 만드는 몇 초 동안 누른 Dock은 Apple Event 큐에서 기다림(확인 안 함): 보통은 `splash.finish`의 이벤트 처리에서 아직 남은 AppKit 기본 처리기가 먹어 새 창이
  뜨지 않고, ready가 처리기를 등록할 때까지 큐에 남아 있었다면 새 창이 하나 더 뜸 — 타이밍에 따라 다름.
- 기본 앱 묻기는 다른 창이 열려 있으면 하지 않으므로, 첫 창의 질문을 단추 없이 닫은 채 다른 창이 남아 있으면 창 하나만 켜질 때까지 다시 묻지 않음. (거의 동시에
  켜진 두 창도 둘 다 묻지는 않음 — 창마다 자기 기록을 남긴 뒤에 다른 창을 세므로 늦게 센 쪽이 먼저 남긴 쪽을 봄. 둘 다 묻지 않을 수는 있음.)
- Windows: 제거는 제거하는 계정의 HKCU만 지움 — 앱이 켤 때 다른 계정에 한 등록은 남아 없는 exe를 가리킴(그 계정에서 YesonCheck를 다시 설치하거나 켜면 새로 고쳐지고, 그 전에 고르면 Windows가 앱이 없다고 알려 다른 앱을 고르게 함 — 설정으로 지울 수 있다고 안내하지 않음). 설치하지 않은 frozen 사본을 켜면 그 계정의
  "연결 프로그램" 항목이 그 사본으로 다시 가리켜짐(설치한 앱을 다시 켜면 돌아옴). HKCU 쓰기가 막히면 켤 때마다 오류 창(조용히 넘기지 않음).
- 몬터레이(12.3)에서의 동작(기본 앱이 확인 창 없이 정해지는지, Finder 더블클릭·다음으로 열기, 처음 묻는 창)은 CI가 아니라 사람이 확인함. 실제 마우스 Dock 클릭·⌘Tab·창 클릭·Mission Control,
  Apple Silicon의 ctypes 경로(CI는 읽기 경로만)도 사람 확인 몫 — BUILD.md 8-4.

### 컴포넌트 역할

**VideoPlayerBase** (`player_base.py`, 부모 `PlayerOcrMixin`·`PlayerOverlayMixin`·`QMainWindow`):
- 메인 윈도우 초기화 및 UI 레이아웃, 어두운·밝은 테마 전환 (시트 문자열은 `main_window_styles.py`)
- 4K 최적화를 위한 프레임 캐싱 시스템
- 상태 변수 만들기: 북마크·작품 경로·오버레이·OCR 상태는 여기 `__init__`이 만들고 각 믹스인이 `self.`로 씀
- 메뉴바 생성
- 핵심 재생 컨트롤 및 상태 표시
- 창 닫기·작업 정지·창 사이 연결(`instance_link`)·사용자 파일 문제 알림

**PlayerOcrMixin** (`player_ocr.py`):
- OCR 모드 선택 처리(`on_ocr_mode_changed` — Titmouse, King, Bento, All, Animatic, Animatic2; 콤보 자체는 `VideoPlayerBase.initUI`가 만듦)와 ROI 선택 상태
- 분석 시작(`run_ocr_analysis`·`run_ocr_analysis_range`)과 진행·완료·오류 콜백, 검토 창 수명
- OCR 결과 저장·불러오기, 구간 내보내기(`start_ocr_export`)
- 워커(`OCRWorker`·`SceneDetectWorker`·`TransNetV2Worker`·`OCRExportWorker`)는 메서드 안에서 `.workers`로 불러옴 (앱 시작 때 불러오지 않음)

**PlayerOverlayMixin** (`player_overlay.py`):
- 영상 위 오버레이 컨트롤(V 키로 컨트롤 패널을 숨기면 보임)의 위젯 만들기, 위치·크기(드래그·크기 조절·하단 중앙 재배치)
- 설정 파일(`~/.yeson_overlay_settings.json`) 읽기·쓰기, 보이기·숨기기·값 갱신

**PlayerPlaybackMixin** (`player_playback.py`):
- 비디오 파일 로딩 및 OpenCV 캡처 관리
- 프레임 단위 재생 및 탐색
- FFmpeg 비디오 병합 기능
- ffprobe를 통한 비디오 코덱 감지
- 재생 속도 및 오디오 제어
- 프레임 탐색 (다음/이전 프레임, 프레임으로 이동)

**PlayerSidebarMixin** (`player_sidebar.py`, 부모 `SidebarBookmarksMixin`·`SidebarPlaylistMixin`·`SidebarConfigPathsMixin`·`SidebarRefreshMixin`·`SidebarSequencesMixin`·`SidebarAllMixin`·`SidebarThumbnailsMixin`):
- 파일 브라우저가 있는 사이드바 UI — 파일 드래그 앤 드롭 처리, 폴더·파일을 목록에 넣기
- 컨텍스트 메뉴 작업 (파일 복사 등)
- 작품 → 시즌 → job 순서 (시즌이 없는 The_Johnsons·TJS_Animatic은 작품 → job): 시즌을 고르기 전에는 job 목록이 'job선택'만,
  job을 고르기 전에는 영상 목록을 읽지 않음. 고른 것은 콤보의 `currentIndex() > 0`으로 판단 (`_picked`·`_job_picked` — 0번은
  안내 항목, -1은 비우는 중: clear가 빈 글자로 currentIndexChanged를 보냄)
- 나머지 사이드바 기능은 아래 부모 믹스인이 가짐 (이 모듈은 `SidebarScan`·`ThumbnailContext`·`gather_shared_config` 등을 옛 경로용으로 다시 내보냄)

**SidebarBookmarksMixin** (`sidebar_bookmarks.py`):
- 북마크 생성 및 탐색 — 북마크 파일 읽기·더하기·지우기, 북마크 관리 창, 북마크 폴더 열기(영상 불러오기 + 그 폴더의 썸네일 폴더 설정)

**SidebarPlaylistMixin** (`sidebar_playlist.py`):
- 선택 재생(Play Selected): 사이드바에서 고른 영상들을 차례로 열어 재생, 디스크에 없는 영상 건너뛰기, 현재 항목 강조 색 되돌리기

**SidebarConfigPathsMixin** (`sidebar_config_paths.py`, 읽는 코드는 `shared_config_load.py`):
- 앱이 켜질 때 공유 설정(작품 경로·변환표·마운트 맵)을 읽어 창에 넣기와 문제 알림, (Windows) 변환표 자동 설정
- 작품 경로 관리 창, 작품 → 이 PC 경로(`get_work_path`), 관리 비밀번호

**SidebarRefreshMixin** (`sidebar_refresh.py`):
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
- 목록 항목 모델(`_sidebar_sources`·`_sidebar_generation`·`_sidebar_scan` — 상태는 `VideoPlayerBase.__init__`이 만듦)과 목록 문제 알림 (읽지 못한 폴더·지워진 폴더·확인하지 못한 파일)

**SidebarThumbnailsMixin** (`sidebar_thumbnails.py`):
- 목록/썸네일 모드 바꾸기와 사이드바 폭, 썸네일 생성 및 캐싱 (`generate_thumbnail` — `ThumbnailWorker`), 저장된 썸네일 붙이기, 다시 만들기·지우기
- 썸네일 반복(썸네일 버튼·새로고침·파일 넣기·`generate_thumbnail`의 기다림)은 목록이 바뀌거나 목록 모드로 바꾸거나 창을
  닫으면 멈춤 (`_thumbnail_pass_stopped`). 끝난 썸네일 워커는 그 finished를 받을 때만 목록에서 뺌 (먼저 놓으면 partial로 이은 failed 신호가 사라져 실패 창이 안 뜸)
- 썸네일 폴더 정하기와 문제 알림, 목록의 썸네일 파일을 뒤 스레드(`ThumbnailLoaderWorker`)로 읽어 아이콘으로

**OCRReviewDialog** (`player_review.py`, `QDialog`):
- 3패널 레이아웃(씬 목록, 상세정보, 미리보기)이 있는 OCR 리뷰 대화상자
- 세그먼트 편집: 병합, 삭제, 이름 변경, 분할
- 자동 씬 이름 지정 및 이름 변경
- 프레임 정확도의 타임라인 시각화
- 품질 프리셋이 있는 내보내기 컨트롤
- 재생 중 실시간 미리보기 업데이트

**OCRTimelineWidget·CollapsibleBox** (`player_timeline.py`, `QWidget`):
- 썸네일 미리보기가 있는 OCR 타임라인 위젯
- 더 나은 UX를 위한 접을 수 있는 컨트롤 패널
- 프레임 정확도의 세그먼트 탐색
- 세그먼트 경계에 대한 시각적 피드백
- ROI 종횡비 보존

**CustomVideoWidget** (`video_widget.py`):
- QGraphicsView를 사용한 비디오 프레임 렌더링 — Mac(cocoa)은 GL 뷰포트 기본(풀스크린 FPS, 위 '주요 파일' 참고)
- 줌, 팬 및 윈도우에 맞추기 컨트롤
- A/B 비교를 위한 와이프 효과 (X/Y축)
- OCR을 위한 ROI(관심 영역) 선택
- 마우스 및 휠 이벤트 처리

**Workers** (워커별 모듈 + 옛 경로용 `workers.py`):
- `ocr_worker.py`: `OCRWorker` — PaddleOCR을 사용한 백그라운드 OCR 분석 (PaddleOCR 도우미 `paddleocr_base_dir`·`use_ascii_paddleocr_dir`·`guard_paddle_buffer_growth`도 여기)
- `ocr_export_worker.py`: `OCRExportWorker` — FFmpeg 기반 세그먼트 내보내기 (구간 목록을 받아 병렬로 내보냄 — 구간이 하나여도, 여럿이어도 이 워커)
- `scene_workers.py`: `SceneDetectWorker` — 애니매틱 모드를 위한 PySceneDetect 래퍼, `TransNetV2Worker` — 점진적 전환 감지가 있는 향상된 애니매틱 모드를 위한 TransNetV2 래퍼
- `thumbnail_workers.py`: `ThumbnailWorker` — 캐싱이 있는 비동기 썸네일 생성, `ThumbnailLoaderWorker` — 파일 브라우저를 위한 비동기 썸네일 로딩
- `ffmpeg_worker.py`: `FFmpegWorker` — 백그라운드 FFmpeg 비디오 병합 작업
- `workers.py`: 위 클래스를 불러와 다시 내보내기만 함 (`from yesoncheck.workers import X`가 그대로 동작, 앱 시작 때 `scene_workers`까지 불러 scenedetect·transnetv2_detector가
  시작 때 불리는 것도 그대로 — TensorFlow는 첫 애니매틱2 분석 때). 시험에서 워커가 읽는 모듈 전역(`TRANSNETV2_AVAILABLE`·`QImage`·`paddleocr_base_dir` 등)을 바꿔치기할 때는
  **그 이름을 읽는 워커 모듈**에서 바꿈 (`workers`에 다시 내보낸 이름을 바꿔도 워커에 닿지 않음)

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
- ProRes류 CFR mov는 ffmpeg 파이프 프레임 소스(`movie_pipe_source`)로 재생 — 4K ProRes 4444의 디코드는 cv2 22fps → 파이프 50.7fps이고, 앱 안의 4K 재생은 이 Mac에서 약 20fps(표시 경로가 병목, 1080p는 실시간)
  (위 '주요 파일'의 해당 항목: 게이트·토글·전송·실패 처리·알고 둔 한계)

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

### 자동 시험 (pytest)

**시험은 반드시 `~/coding/p310_tf/bin/python -m pytest`로 돌릴 것** — TensorFlow가 없는 `~/coding/p310`으로 돌리면 11개가 실패함.

`tests/`에 시험 파일 84개 (수집 2,009개). `python -m pytest tests -q`로 돌리며(약 14분), 이 Mac의 소스 실행에서 1,964개가 통과하고 45개는 건너뜀 —
다른 OS 전용 시험과 CI의 설치 파일 단계에서만 도는 시험이 건너뜀 (2026-10-29 기준). Qt는 화면 없이(`QT_QPA_PLATFORM=offscreen`), ffmpeg는 저장소의
정적 빌드(`vendor/ffmpeg/`)를 씀 (`tests/conftest.py`). 시험을 건너뛰거나 지워서 통과시키지 말 것.

시험 구성 (파일 이름 기준):
- **업데이트**: `test_updates`·`test_update_install`·`test_update_flow`·`test_update_ui`·`test_update_helper_mac`·`test_update_helper_windows`·`test_update_e2e`
- **새 창·기본 앱·창 사이 연결**: `test_new_window`·`test_mac_app_events`·`test_default_app`·`test_file_associations`·`test_launch_args`·`test_instances`·
  `test_instance_link`·`test_error_window`·`test_app_logging`
- **경로·공유 설정·작품**: `test_paths`·`test_paths_windows`·`test_mac_mounts`·`test_shared_config`·`test_path_map_setup`·`test_path_map_setup_dialog`·
  `test_path_map_auto_ui`·`test_stored_paths`·`test_work_paths_ui`·`test_work_season_job`
- **사이드바·썸네일·북마크**: `test_sidebar_refresh`·`test_video_list`·`test_thumbnails`·`test_bookmarks`·`test_sidebar_all_tab`
- **워커·OCR·내보내기**: `test_workers_split`·`test_workers_transnetv2_guard`·`test_ocr_worker_lifetime`·`test_animatic2_availability`·`test_transnetv2_detect`·
  `test_runtime`·`test_export`·`test_unsaved_ocr_flag`·`test_review_sync`
- **창 모양**: `test_stylesheet_freeze`(테마 시트를 해시로 고정)·`test_scrollbar_style`·`test_slider_click`·`test_window_resize`·`test_high_dpi`·`test_force_focus`·`test_middle_panel_toggle`·`test_gl_viewport`(Mac GL 뷰포트 — 선택 규칙·GL 적용 시 보존 설정·테마 배경)·`test_overlay_slider_sync`(화살표 프레임 이동의 오버레이 슬라이더 동기화·대체 탐색 경로 한 칸 어긋남)
- **ffmpeg 파이프 재생(ProRes)**: 실제 ffprobe·ffmpeg로 클립 공장(`tests/prores_clips.py` — numpy 프레임을 `prores_ks`에 파이프, 글꼴 의존인 drawtext 금지; 번호 클립·유채색 클립·경계 클립 voff·held·neg·rot·audio_first·truncated·vfr_h264)의 클립을 읽음 (mock 없음 — 오류 창 호출만 바꿔치기)
  - `test_pipe_spike`: 플랫폼 가정을 고정하는 스파이크 — 클립 공장 자가 검증, 파이프(`-fps_mode passthrough`) 대 cv2의 프레임 정렬과 바이트 기준(4:4:4 동일·4:2:2 ≤5), `-ss` 착지(K=0·K=2), 재시작 시간(시간은 print만)
  - `test_movie_pipe_gate`: 게이트 ①~⑥ — 좋은 probe의 필드 하나만 바꾼 사본으로 조건별 경계, 경계 클립의 판정
  - `test_movie_pipe_capture`: 캡처 코어 — 순차 읽기의 cv2 의미(EOF·`get`·`set`)·cv2와 바이트 대조·도중 실패의 자체 완결(예외 없이 죽음 + 기록 1회 + 오류 창 1회)·`release`/GC 뒤 프로세스 종료
  - `test_movie_pipe_seek`: 지연 set과 이동 경로(그대로·링 버퍼·앞으로 버리기·`-ss` 재시작+트랙 오프셋) — 정답은 프레임에 그린 번호, 어느 경로를 탔는지는 시간이 아니라 세션(프로세스) 수·pid로 실증. 링 보관본을 읽기 스레드가 만들어 재활용하는지(`test_ring_copy_made_by_reader_and_recycled` — 새로 만드는 버퍼 ≤ 16장)도 봄
  - `test_movie_pipe_transport`: 전송 계층 — 프레임당 recv 1회(`recv_calls`)·메인 스레드가 GIL을 50ms 쥐어도 읽기 스레드가 큐를 채워 둠(읽기 직전 큐 장 수 평균, 근거 수치는 그 시험의 docstring)·release가 막힌 recv를 깨움(shutdown+close)·Windows 경로(TCP 리스너의 accept·EOF·정리·접속 실패)를 `sys.platform` 바꿔치기로
  - `test_display_single_draw`: 재생 틱 한 번에 `updateFrame` 정확히 한 번(주석을 구운 마지막 그림)·`redraw=False`에서도 편집 대상·목록·상태 라벨 갱신은 그대로·다른 호출처는 여전히 그림·드래그 + OCR 검토 창 분기는 와이프가 켜져 있을 때만 다시 그림 — 사용자 승인 예외(중복 그리기 제거)의 보증
  - `test_movie_pipe_integration`: `maybe_pipe_capture`의 모드(auto·pipe·cv2)·예외 경계, `open_any_capture`와 `_open_movie_capture`의 삽입 분기, `app.launch`의 모드 검증 — **게이트 음성 파일은 어떤 모드에서도 `FFmpegPipeCapture`를 만들지 않고 `cv2.VideoCapture`가 열림**(만들면 실패하는 센티널로 바꿔 증명 = cv2 경로 무변경 단언)
  - `test_pipe_player`: 실제 `VideoPlayer`(offscreen)에서 열기·화살표/휠·슬라이더·A/B 와이프·주석 내보내기·재생 도중 ffmpeg 사망(앱 생존·오류 창 1회·재오픈)과 끝난 뒤 프로세스·스레드 잔존 없음
  - `test_smoke_pipe_step`: 실행 시험(`smoke_test.py`)의 'ProRes 파이프 열기' 단계 단위 시험 — 성공·게이트가 cv2를 주면 실패·모드가 auto가 아니면 실패 (번들 ffmpeg는 CI의 빌드 앱 smoke가 봄)
- **그 밖**: `test_smoke`·`test_fast_startup`·`test_files`·`test_user_files`·`test_frame_annotations_merge`·`test_annotation_click`·`test_external_tools`·`test_build_info`·
  `test_check_frozen_imports`·`test_release_tool`·`test_print_crash_reports`·`test_screenshot_check`·`test_refactor_checks`

CI(`.github/workflows/windows-build.yml`)는 세 플랫폼 — Windows(`windows-latest`), Mac Apple Silicon(`macos-15`), Mac Intel(`macos-15-intel`) — 에서
Python 3.10 환경을 만들고 소스 시험(`pytest tests`)을 돌린 뒤 앱을 빌드해 번들 검사와 빌드된 앱의 실행 시험(`ci/`)까지 함.
`test_paths_windows`·`test_update_helper_windows`처럼 한 OS에서만 도는 시험은 다른 OS에서 건너뛰므로, 어느 OS의 시험을 고쳤는지에 따라 CI에서 확인해야 함.

**코드를 옮기기만 하는 변경(동작이 그대로여야 할 때)의 검증 도구**:
- `ci/screenshot_check.py capture --out DIR` / `compare --baseline DIR --current DIR`: 장면 9개(처음 켠 창·밝은 테마·영상 A 열기·A/B 와이프·썸네일 모드·
  접는 상자 펼침·오버레이·주석 모드·OCR 검토 창)를 오프스크린으로 찍어 PNG 바이트와 위젯 트리까지 견줌
- `tools/refactor_checks/mixin_coupling.py snapshot|compare`: `VideoPlayer`의 MRO·메서드 본문 해시·`self` 결합을 정적 분석으로 스냅샷해 이동 전후를 견줌
  (예상된 차이는 `--allow` 목록에 적은 것만 통과)
- `tools/refactor_checks/runtime_globals.py`: 모든 함수가 쓰는 모듈 전역 이름이 풀리는지 확인 (코드를 옮기며 import를 빠뜨려 드물게 도는 분기에서만 터질 `NameError`를 잡음)

기준 폴더(`.refactor_baseline/`)는 저장소에 넣지 않음 (`.gitignore`). 시험 자체의 시험은 `test_screenshot_check`·`test_refactor_checks`.

### 수동 확인 (자동 시험이 닿지 않는 것)

UI를 건드린 변경은 소스 실행(`./run_app.sh`)으로 눈으로도 확인합니다:
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
13. 4K ProRes 재생(ffmpeg 파이프) — 캐시 없는 파일의 첫 재생 fps·소리·탐색·와이프·주석·h264 무회귀·킬 스위치: 내부(비공개) 저장소의 `docs/superpowers/records/2026-10-29-prores-pipe-design/eye-check.md`

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
- 동영상 기본 앱 질문의 답(Mac): `~/Library/Application Support/YesonCheck/prefs.json` — `{"asked_default_video_app": true}`([예]·[아니요] 단추를 누른 뒤에만,
  `default_app.record_asked`: 잠금 안에서 다시 읽고 다른 키는 그대로 두며 씀. 지우면 다시 물음, 깨진 파일은 빈 값으로 치지 않고 `UserFileError` 오류 창). HOME을 부를 때마다
  읽음. `ci/update_e2e.py`가 Mac 사례마다 미리 심음(BUILD.md 8-3)
- Windows 동영상 연결 프로그램: 파일이 아니라 레지스트리 HKCU의 12개 값(`file_associations.association_entries` — BUILD.md 8-2)
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
- `Info.plist`: 낡은 파일 — spec이 데이터로 복사만 하며 번들의 진짜 Info.plist가 아님. 번들의 `Info.plist`는 spec의 `BUNDLE(info_plist=…)` dict로 만들어짐(`LSMinimumSystemVersion`·버전·`CFBundleDocumentTypes` — BUILD.md 8-1)
- `installer/yesoncheck.iss`: Windows 설치 파일(Inno Setup) — `[Registry]`가 동영상 연결 프로그램을 HKCU에 등록(`file_associations`와 같은 내용), UTF-8 + BOM 유지 (BUILD.md 8-2)
- `icon.icns`: 애플리케이션 아이콘
- `check_frozen_imports.py`: 빌드된 앱에 실행 중 필요한 파이썬 모듈이 모두 들어 있는지 검사 — `yesoncheck/*.py` 소스의 모든 import(함수 안 지연 import 포함)를 모으므로
  새 모듈을 평면(`yesoncheck/` 바로 아래)에 두고 평소처럼 import하면 spec에 따로 적지 않아도 됨 (하위 패키지에 두면 검사 범위가 말없이 좁아짐 — `tests/test_workers_split.py`가 워커 모듈에 대해 지킴)
  PIL처럼 지연 import하는 모듈은 import만으로는 안 잡히므로 실제로 실행해야 함 — 시퀀스 TGA·EXR 한 장 디코딩(`exercise_sequence_decode`)이 그 예 (`tests/test_check_frozen_imports.py`)
- `.github/workflows/windows-build.yml`·`ci/`·`requirements-test.txt`: CI와 시험 도우미 ('테스트 전략')
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
- **`재생: n FPS` 라벨은 측정값이 아님**: `update_playback_fps`가 1초마다 영상의 원래 fps(`cap_a.get(CAP_PROP_FPS)`)를 다시 쓸 뿐이라 실제로 느리게 돌아도 24로 보임
  (`playback_fps_counter`는 세기만 하고 읽는 곳이 없음). 재생 속도는 처음부터 끝까지 재생한 시간(프레임 수 ÷ fps — 재생 타이머 간격이 `int(1000/fps)`ms라 약간 짧을 수 있음)이나
  캡처 `read()` 처리량으로 잼
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
3. 워커 모듈(씬 감지는 `scene_workers.py`)에 `QThread`를 상속하는 새 워커 클래스를 추가하고, 옛 경로용으로 `workers.py`에서도 불러와 다시 내보냄
4. 새 모드 추가:
   - `player_base.py`의 `initUI`에서 새 모드를 포함하도록 `ocrModeComboBox` 업데이트
   - `player_ocr.py`의 `on_ocr_mode_changed`와 `run_ocr_analysis()`·`run_ocr_analysis_range()`에 새 워커를 사용하는 조건부 로직 추가
5. 다양한 비디오 콘텐츠 유형으로 테스트

## 최근 변경 사항

### 2026-10-29 (4K ProRes 재생 — ffmpeg 파이프 프레임 소스)
- 4K ProRes 4444 mov가 실시간 재생이 안 되던 원인은 cv2 내장 FFmpeg의 단일 스레드 픽셀 변환으로 보임(cv2 22fps, 번들 ffmpeg 50.7fps). ProRes류 CFR mov를 번들 ffmpeg(rawvideo bgr24)로 디코드하는
  새 모듈 `movie_pipe_source.py`(`FFmpegPipeCapture`)를 `ImageSequenceCapture` 선례의 덕타이핑 캡처로 열기 경로에 꽂음: 게이트 ①~⑥을 전부 통과한 파일만(opt-in), 나머지는 기존 cv2 그대로
- **기존 재생·탐색 코드는 수정하지 않음**: 바뀐 열기 경로는 `_open_movie_capture`의 삽입 분기·`open_any_capture`·`app.launch`의 모드 검증뿐. 도중 실패는 캡처가 스스로 죽은 cv2 캡처의 겉모습 + 기록 1회 + 오류 창 1회로 끝냄(예외는 열 때만)
- 눈 확인 중 4K가 실시간에 못 미치는 것을 발견해 두 가지를 고침: ① **전송을 stdout 파이프에서 소켓으로**(POSIX `socketpair`, Windows TCP 127.0.0.1 — 프레임당 `recv` 1회, GUI가 GIL을 쥐고 있어도 읽기 스레드가 굶지 않음)
  ② **링 보관본 복사를 GUI 스레드에서 읽기 스레드로**(캡처당 4K 메모리 ~350MB → 약 550MB). 그리고 사용자가 승인한 예외로 ③ **`update_frame`의 중복 그리기 제거**(틱당 `updateFrame` 2→1, 픽셀 동일 — 이 브랜치에서 기존 표시 코드를 바꾼 유일한 곳)
- 4K 4444 334장 재생(이 Mac): 22.0초(15.2fps, 처음 구현) → 18.54초(18.0fps, 소켓 전송) → **16.57초(20.2fps, 최종)**. 1080p ProRes는 실시간. **4K는 완전한 실시간이 아님** — 남은 병목은 4K `QPixmap`의 GL paint(48ms/프레임),
  Windows(raster) 4K는 더 느릴 것(약 8fps 수준 추정). 다음 후보: 4K 표시 경로(직접 GL 텍스처 스트리밍·Windows GL 뷰포트) — '주요 파일'의 `movie_pipe_source.py` 항목
- 토글 `YESONCHECK_MOVIE_SOURCE=auto|pipe|cv2`(`cv2`는 킬 스위치). 로그 `[재생] ffmpeg 파이프: …` 줄이 있으면 파이프 경로
- 지켜야 할 것: `-fps_mode passthrough`·`-map 0:V:0`, 재시작 `-ss`의 트랙 오프셋 보정, 정확 등식 게이트(④), 소켓은 blocking(타임아웃을 걸지 말 것), 4:2:2는 Apple Silicon에서 cv2 대비 ±4 레벨(4:4:4는 완전 동일)
- 시험 파일 9개(+ 공장 `tests/prores_clips.py`)·빌드 앱 smoke 단계 추가. 눈 확인(실물 4K ProRes — 이 Mac 필수, Windows 1회)은 사용자 몫

### 2026-10-22 (큰 파일 나누기 — 동작은 그대로)
- **`workers.py`**(3,189줄 — 쓰이지 않는 메서드를 지운 뒤 나누기 직전)를 워커별 모듈 5개(`ocr_worker`·`ocr_export_worker`·`scene_workers`·`thumbnail_workers`·`ffmpeg_worker`)로 나누고, `workers.py`는 다시 내보내기만 하는 18줄 모듈로 남김
- **`player_base.py`**(5,443줄 → 1,740줄): OCR 묶음 → `player_ocr.py`(`PlayerOcrMixin`), 오버레이 묶음 → `player_overlay.py`(`PlayerOverlayMixin`), 스타일시트 문자열 → `main_window_styles.py`,
  붙잡아 둔 워커 정리 → `worker_lifecycle.py`
- **`player_sidebar.py`**(3,404줄 → 518줄): 북마크·선택 재생·공유 설정/작품 경로·목록 다시 읽기·썸네일을 믹스인 5개(`sidebar_*.py`)로, 공유 설정 읽기 코드는 `shared_config_load.py`로,
  항목 상수는 `sidebar_items.py`로 옮김
- 쓰이지 않는 코드(약 750줄)와 파일 둘(`yesoncheck/styles.py`·`reproduce_issue.py`) 제거. 메서드·클래스는 코드를 바꾸지 않고 옮기기만 했고, 창 화면(픽셀)·MRO·시험 1,273개가 나누기 전과 같음을 확인
- **자동 시험**: pytest 시험이 이 저장소에 있고 CI(Windows·Mac Apple Silicon·Mac Intel)가 매번 돌림 — 아래 '테스트 전략'

### 2025-12-11
- **Spec 파일 업데이트**: `YesonCheck_Autocut.spec`으로 이름 변경 (자동 씬 컷 기능 강조)
- **웹 내보내기**: `web_info.py` 모듈 추가로 OCR 분석 결과를 HTML 보고서로 내보내기

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
