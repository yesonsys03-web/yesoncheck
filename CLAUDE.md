# CLAUDE.md

이 파일은 Claude Code (claude.ai/code)가 이 저장소의 코드 작업 시 참고할 수 있는 가이드를 제공합니다.

## 프로젝트 개요

YesonCheck는 PyQt5로 구축된 전문 비디오 비교 및 OCR 분석 도구입니다. A/B 비디오 비교, OCR 기반 텍스트 세그먼트 감지, 자동 씬 컷 감지(애니매틱 모드), 애니메이션 제작 워크플로우에 최적화된 클립 내보내기 기능을 제공합니다.

**주요 기술**: PyQt5, OpenCV, PaddleOCR, PySceneDetect, TransNetV2, FFmpeg (Mac 빌드만 PyObjC — VideoToolbox 네이티브 재생)

## 주요 명령어

### 개발 환경
```bash
# 빌드·개발 환경 만들기 (최초 1회): ~/coding/p310_tf에 Python 3.10 + 아키텍처별 lock의 고정 버전
# (PyQt5, opencv 4.6.0.66, paddle, paddleocr 2.7.3, scenedetect 0.6.7.1, TensorFlow 2.15.1, Mac은 PyObjC 12.2.2 등 — BUILD.md;
#  PyObjC를 lock에 넣기 전에 만든 환경은 `uv pip install --python ~/coding/p310_tf/bin/python -r requirements-build-<arch>.lock`)
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
  `SidebarRefreshMixin`·`SidebarSequencesMixin`·`SidebarAllMixin`·`SidebarOpenWithMixin`·`SidebarThumbnailsMixin` 8개를 상속
- `VideoPlayerBase`(`player_base.py`)는 `PlayerOcrMixin`·`PlayerOverlayMixin` 2개와 `QMainWindow`를 상속

그래서 `VideoPlayer.__mro__`는 `VideoPlayer > PlayerUpdateMixin > PlayerAnnotationsMixin > PlayerSidebarMixin > SidebarBookmarksMixin >
SidebarPlaylistMixin > SidebarConfigPathsMixin > SidebarRefreshMixin > SidebarSequencesMixin > SidebarAllMixin > SidebarOpenWithMixin > SidebarThumbnailsMixin > PlayerPlaybackMixin > VideoPlayerBase >
PlayerOcrMixin > PlayerOverlayMixin > QMainWindow …`. 이 구조에서 지킬 것:
- 같은 이름의 메서드를 두 믹스인에 두지 않음 (MRO에서 먼저 나오는 쪽이 가림 — `PlayerSidebarMixin`의 `dragEnterEvent`·`dropEvent`는 `QMainWindow`의 가상 함수를 가림).
  부모 믹스인 모듈(`sidebar_*`·`player_ocr`·`player_overlay`)은 상속받는 쪽(`player_sidebar`·`player_base`)을 모듈 수준에서 import하지 않음 (순환).
  상태(`self.…`)는 `VideoPlayerBase.__init__`이 만들고 믹스인은 `self.`로 부름.
- 시험이 모듈 전역을 바꿔치기할 때는 **그 이름을 읽는 코드가 있는 모듈**에서 바꿈 — 다른 모듈에 다시 내보낸 이름을 바꾸면 말없이 닿지 않음.
  예: `sidebar_thumbnails.ThumbnailWorker`·`shared_config_load.gather_shared_config`·`sidebar_config_paths.PathMapSetupDialog`·`ocr_worker.paddleocr_base_dir`.
- 옛 import 경로는 다시 내보내기로 남아 있음: `yesoncheck.workers`(워커 전부), `player_base`(`EXIT_WAIT_S`·`release_worker`·`wait_for_released_workers`),
  `player_sidebar`(`SidebarScan`·`ThumbnailContext`·`gather_shared_config` 등).

**주요 파일**:
- `yesoncheck/app.py` (457줄): 애플리케이션 부트스트랩 및 CLI 진입점 — 빌드 앱은 `setup_app_logging`이 stdout·stderr를
  창(프로세스)마다 기록 파일 `yesoncheck_<날짜>_<pid>.log`로(Mac `~/Library/Logs/YesonCheck`, Windows
  `%LOCALAPPDATA%\YesonCheck\logs` — update.log와 같은 폴더, 30일 지난 것은 켤 때 지움) 보내고 예외 창(`sys.excepthook`)을
  설치. 업데이트 중(다른 창이 넘긴 업데이트 — 도우미가 `--update-result`로 켠 앱은 빼고)에 켜면 창을 만들지 않고
  "업데이트 중입니다 — 끝난 뒤 다시 열어 주세요" 창만(8초 뒤 저절로 닫힘) 보이고 끝남. 받은 파일·Dock 클릭은
  `mac_app_events`가 받아 첫 파일은 이 창의 A(`open_startup_file` — 있는지 보지 않고 `open_file`로, 열지 못하면 그 오류 창), 나머지와
  켜진 뒤의 것은 새 창(`new_window`)으로 보내고, 창을 보인 뒤 Mac 빌드 앱은 처음 한 번 동영상 기본 앱을 묻고(`default_app`) Windows 빌드
  앱은 이 계정에 연결 프로그램을 등록(`file_associations`) —
  시작 순서는 아래 '여러 창과 업데이트'의 '새 창·동영상 열기·기본 앱'. 스플래시 전에 `movie_pipe_source.movie_source_mode()`·`frame_cache_mode()`를 한 번씩 불러
  `YESONCHECK_MOVIE_SOURCE`·`YESONCHECK_FRAME_CACHE`의 나쁜 값을 시작 때 ValueError로 멈춤 (같은 자리에서 `gl_video_item.video_item_mode`가 `YESONCHECK_VIDEO_ITEM`도, `mac_native_gate.native_wanted()`가 `YESONCHECK_MAC_NATIVE`도 — 값과 함께 macOS가 아닌데 `on`이면 여기서 ValueError, 열 때마다 늦게 실패하지 않게). 그 바로 앞에서 Mac이면 `load_playback_decoder()`가 재생 디코더 설정(`prefs.json`의 `playback_decoder` — `mac_prefs`)을 **한 번** 읽어 `mac_native_gate`의 캐시에 두고 기록 한 줄 `[재생] 디코더: <videotoolbox|ffmpeg> (<출처>)`(출처 넷 — 환경 변수 `YESONCHECK_MAC_NATIVE=on|off`·`prefs.json`·`기본값`·`prefs.json 읽기 실패 — 이 세션만 ffmpeg`); 깨진 파일·나쁜 값(`UserFileError`·`ValueError`)은 기본값으로 치지 않고 트레이스백 + 창 1회(`재생 디코더 설정` — 끝 줄 `PLAYBACK_DECODER_FALLBACK_NOTE` `이 세션은 예전 방식(ffmpeg)으로 재생합니다 — Settings → 재생 디코더 (Mac)에서 바꿀 수 있습니다`) 뒤 **그 세션만 ffmpeg**(`SOURCE_FALLBACK` — 설정을 읽지 못한 채 새 경로를 켜지 않음; 파일은 건드리지 않음)
- `yesoncheck/main_window.py` (12줄): 믹스인 구성 (`VideoPlayer`)
- `yesoncheck/player_base.py` (2,131줄): 핵심 UI 및 윈도우 관리 — `VideoPlayerBase`(UI 만들기·메뉴·테마 전환·창 닫기·작업 정지·창 사이 연결). 창을 만들 때 `videoWidget`에 네이티브 프레임용 공급자 둘을 등록(`set_overlay_provider(_overlay_text_for_native)`·`set_annotation_provider(_annotations_for_native)` — 아래 `video_widget.py`).
  **Settings → 재생 디코더 (Mac)**(2026-11-04 — `sys.platform == "darwin"`일 때만 만듦, Windows 메뉴는 글자 하나 안 바뀜): GPU Acceleration 서브메뉴 바로 뒤에 체크 항목 `VideoToolbox (기본)`·`ffmpeg (예전 방식)`(`DECODER_MENU_TEXT`·`DECODER_ACTION_TEXTS`, `decoder_actions` 이름 → QAction·`decoder_action_group` — Mac 밖에서는 빈 채). `_sync_decoder_menu()`가 체크·활성·툴팁을 `mac_native_gate.effective_decoder()`에 맞춤(만들 때·고른 뒤·폴백 뒤): `YESONCHECK_MOVIE_SOURCE=cv2`면 두 항목 비활성 + `DECODER_CV2_TIP`(환경 변수보다 먼저), 출처가 `환경 변수`로 시작하면(`DECODER_ENV_SOURCE_PREFIX`) 비활성 + `<출처>이|가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다`(on이·off가), 그 밖은 활성 + `DECODER_TIP`(이 창은 바로, 이미 열린 다른 창은 다음에 켤 때부터)이고 prefs.json·기본값이 아닌 출처(`SOURCE_FALLBACK`·`SOURCE_GL_FALLBACK`)는 체크된 항목의 툴팁이 그 글. `set_playback_decoder(name)`(macOS 밖 RuntimeError, 모르는 이름은 쓰기 전에 ValueError): 같은 값이 prefs.json·기본값에서 왔으면 체크만 맞춤(체크된 항목을 다시 누르면 Qt가 끔) → ① `mac_prefs.update_pref("playback_decoder", name)` — 실패(`UserFileError`·`OSError`·잠금 `TimeoutError`)면 트레이스백 + 창 1회(`재생 디코더 설정`) + 체크 되돌림, 캐시·캡처 그대로(재시도 없음) ② `set_preferred_decoder(name, source=SOURCE_PREFS)` ③ 기록 `[재생] 디코더 설정: <이름> (Setting 메뉴)` — 유효 디코더가 들어올 때와 같으면(환경 변수가 덮음·폴백 세션에서 ffmpeg 저장) `[재생] 유효 디코더가 그대로(…) — 캡처를 다시 열지 않음`과 메뉴만 ④⑤⑥ `_swap_captures_and_settle_latch(log)`: `swap_movie_captures_for_decoder()`(False면 그 함수가 이미 창을 띄웠으므로 기록 한 줄만) → 바꿔 끼운 **뒤** 스트림 아이템의 걸쇠를 `reset_failure()`로 풂(Ruling 9 — 바꿔 끼우는 동안 뜬 모달의 이벤트 루프가 옛 프레임을 그려도 걸쇠가 걸린 채라 다시 실패하지 않음; 반대 순서면 다시 걸림) — 단 `_latched_on_native_under_ffmpeg()`(걸림 `latched` + `has_native_side()` + 유효 ffmpeg)면 풀지 않고 `KEEP_LATCH_LOG` → `finally`로 `_sync_decoder_menu()`(예외는 그대로 올림 — 두 항목이 함께 체크된 채 남지 않게). **재시도 트리거**(Ruling 11 + 최종 리뷰 F1): 걸쇠가 걸린 창(`_latched_under_ffmpeg` — 네이티브 면이든 RGB 그림이든, 유효 ffmpeg)에서는 유효 디코더가 그대로인 두 길(저장할 것 없는 다시 누름, ③의 '그대로')에서도 `DECODER_RETRY_LOG` (`[재생] 이 창은 그리기가 멈춰 있어(걸쇠) ffmpeg로 캡처를 다시 바꿔 끼우고 걸쇠를 정리함`) 뒤 헬퍼를 다시 부름(네이티브 면이 남으면 헬퍼가 걸쇠를 유지 — 아래 한계 ⑦, RGB면 풀어 다시 그림) — 창 글이 권하는 'ffmpeg (예전 방식)'이 아무 일도 안 하면 빈 영역이 남음. `videoWidget.streamPaintFailed` → `_on_stream_paint_failed`(아래 `video_widget.py`의 '큰 소리 폴백'). 시험 `tests/test_decoder_menu.py`·`tests/test_native_paint_fallback.py`
  OCR 묶음은 `player_ocr`, 오버레이 묶음은 `player_overlay`로 나눠 부모로 붙였고, 스타일시트 문자열은 `main_window_styles`, 붙잡아 둔 워커 정리는
  `worker_lifecycle`로 옮김 (`worker_lifecycle`의 이름은 여기서 다시 내보냄)
- `yesoncheck/player_ocr.py` (1,845줄): `PlayerOcrMixin` — ROI·분석 방식 UI 상태, 분석 시작(OCR·애니매틱·애니매틱2)과 진행·완료 콜백, 검토 창 수명,
  결과 저장·불러오기, 구간 내보내기 (`VideoPlayerBase`의 부모)
- `yesoncheck/player_overlay.py` (753줄): `PlayerOverlayMixin` — 영상 위 오버레이 컨트롤(V 키)의 위젯·위치·크기·설정 파일(`~/.yeson_overlay_settings.json`)
  (`VideoPlayerBase`의 부모)
- `yesoncheck/main_window_styles.py` (940줄): 어두운·밝은 테마 시트(`DARK_STYLESHEET`·`LIGHT_STYLESHEET`)와 큰 인라인 시트 상수 — 데이터만 있는 잎 모듈
  (한 글자도 바뀌지 않게 `tests/test_stylesheet_freeze.py`가 해시로 지킴)
- `yesoncheck/worker_lifecycle.py` (76줄): 놓아 준 `QThread` 워커를 끝날 때까지 붙잡아 두기 — `release_worker`·`wait_for_released_workers`·`EXIT_WAIT_S`(30초)
- `yesoncheck/player_playback.py` (2,928줄): 비디오 재생, 프레임 탐색 및 FFmpeg 작업 — `_open_movie_capture`는 `os.stat` 확인 뒤·`cv2.VideoCapture` 앞에 `_native_or_pipe_capture`를 끼움: `YESONCHECK_MOVIE_SOURCE=cv2`면 맨 먼저 그대로 파이프 게이트 함수로(그 안에서 probe 없이 `None` — 네이티브 토글도 읽지 않음), `native_wanted()`가 거짓이면(Windows·재생 디코더 ffmpeg·`YESONCHECK_MAC_NATIVE=off`) 예전 파이프 게이트 줄 그대로(`mac_native_source`는 import도 안 함 — 지연 import, `tests/test_native_open_path.py`가 새 프로세스로 고정), 원하면 ffprobe 한 번(`probe_for_open`)으로 네이티브 게이트(아래 'Mac 네이티브 재생') → 양성이면 `open_native_capture`, `NativeCaptureError`(PyObjC 없음 포함)면 트레이스백·기록 줄 `[재생] 네이티브(VideoToolbox): 열지 못해 ffmpeg 파이프로 계속: <이름>`·오류 창 `영상을 열 수 없음(네이티브)` 1회(끝 줄 `NATIVE_ESCAPE_HINT`) 뒤 파이프로, 음성이면 `[재생] 네이티브(VideoToolbox): 아님 — <사유>: <이름>` 뒤 파이프로 — 파이프 게이트는 `maybe_pipe_capture(…, full_cache=True, probe=)`(같은 probe — ffprobe 한 번; 전체 프레임 캐시를 원하는 곳은 여기뿐)(아래 `movie_pipe_source`; 둘 다 음성이면 기존 cv2 줄이 그대로 돎). 네이티브 프레임(`frame_handles.native_surface_of`가 손잡이를 줌)은 `process_frame`·`optimize_for_4k`·드래그 미리보기(`process_frame(…, gpu=False)`)가 변환 없이 그대로 돌려주고 `frame_cache`에 넣지 않음(복사 4K 33MB — 파이썬 쪽 픽셀 접근 0을 `tests/test_native_player_paths.py`가 고정). 재생이 마지막 프레임에 닿거나 read가 끝나면 Play마다 기록 한 줄 `[측정] <N>장 <초>초 (<fps>fps) 네이티브=yes|no 와이프=on|off 표시=gl|pixmap|raster — <파일>`(`measurement_line`·`_measure_tick`·`_print_measurement` — 모든 캡처; N은 Play 뒤 진행한 장 수, 초는 Play 직후부터 마지막 틱의 그리기까지, 도중에 멈추면 줄 없음; 실시간 재생 판정용). `overlay_text`(B 키 — 프레임에 굽는 파일 이름·프레임 번호, 글자는 `overlay_label`)는 `overlay_text_layout.overlay_layout`으로 크기를 프레임에 비례시킴(`overlay_metrics`·`OVERLAY_TEXT_SCALE`, 2026-11-03 — 2026-11-04에 네이티브 아이템 길과 함께 쓰려고 `overlay_text_layout.py`로 옮김, `overlay_metrics`는 옛 import 경로로 다시 내보냄). `update_frame`은 그린 직후 `refresh_frame_annotations_display(redraw=False)`를 불러 같은 프레임을 두 번 그리지 않음 (틱당 `updateFrame` 2→1, 픽셀 동일 — 이 브랜치에서 기존 표시 코드를 바꾼 유일한 곳, 사용자 승인 예외; 드래그 + OCR 검토 창 분기는 앞 그림이 B를 뺀 그림이라 와이프가 켜져 있을 때만 다시 그림; 같은 패턴인 `_overlay_slider_ui_update`는 무변경; tests/test_display_single_draw.py) — 화살표·휠 프레임 이동 모두 오버레이(V 모드) 슬라이더를 함께 갱신(`_update_ui_fast`도 `update_overlay_controls`를 부름 — tests/test_overlay_slider_sync.py) — 전역 단축키(`keyPressEvent`): V(컨트롤 전체 숨김·오버레이), N/ㅜ(가운데 컨트롤 열 숨김 — `toggle_middle_panel`, V·전체화면 복원 뒤에도 유지), P/ㅔ(북마크 관리 창 — `show_bookmarks`). 사이드바 목록이 포커스를 가질 때는 `player_base.eventFilter`가 같은 키(V·N·P)를 받음
  **디코더 전환**(2026-11-04): `swap_movie_captures_for_decoder()`(메뉴·네이티브 그리기 폴백이 캐시를 바꾼 뒤 — Qt 루프에서만) — `open_file`을 부르지 않음(그 길은 OCR 상태를 지우고 — 돌아가는 분석·검토 창·저장 안 한 결과 — 주석을 다시 읽고 소리를 `setMedia`하고 줌을 `initial_fit`으로 되돌리고 재생을 멈춤; 여기서는 `filename_*`·`mediaPlayer`·`annotation_store`·OCR 상태·줌·와이프 체크/축/위치·`is_playlist_playing`을 건드리지 않음). 열린 A·B 중 **디코더가 실제로 바뀌는 쪽**만 다시 연 캡처로 바꿔 끼움: `YESONCHECK_MOVIE_SOURCE=cv2`면 아무것도 안 하고 True(probe 없음), 시퀀스·빈 쪽은 건너뜀, 영상이면 ffprobe 한 번(`probe_movie`) → `native_ineligible_reason(probe) is None`인 쪽만(같은 게이트 함수 — HDR·VFR ProRes·h264는 어느 설정에서나 같은 길이라 그대로; 파이프 → 파이프로 다시 열면 채운 전체 캐시만 버림), ffprobe 실패(`RuntimeError`)는 기록 + 창 1회(`재생 디코더를 바꾸지 못함`) + 그 쪽 옛 캡처 그대로 + False. 고른 쪽이 있으면 지금 번호와 **B의 자리**(`b_next`, 읽어 둔 `frame_b`가 있는지)를 먼저 기억 → 재생 중이면 `pause_video`(열기 창의 이벤트 루프에서 틱이 돌지 않게) → 쪽마다 `_open_movie_capture`(못 열면 창은 그 함수, 옛 캡처·프레임 그대로, False; 새 B는 옛 B 자리로 `set`) → 옛 캡처 release·프레임 None(실패한 GL 길의 네이티브 프레임일 수 있어 다시 쓰지 않음) → `clear_cache()`·`_measure_run = None`(한 `[측정]` 줄이 두 디코더에 걸치지 않게 — 줄 없이 닫음)·`seek_to_frame(번호 + 1)` → **B 오프셋 복원**(와이프인데 B가 A와 어긋나 있었거나 — ←→·휠은 A만 움직임 — 와이프 꺼진 B를 바꿔 끼웠으면 B의 그 번호를 한 장 읽어 `frame_b`, 와이프면 `update_frame`) → 재생 중이었으면 `play_video`(새 `[측정]` 기록). 바꾼 쪽마다 `[재생] 디코더 전환: <A|B> 캡처 바꿔 끼움 — <이름> (<번호>번)`. 스크롤 범위는 다시 정하지 않음(네이티브 게이트가 파이프 ①~⑥을 포함 — 같은 nb_frames). 시험 `tests/test_decoder_swap.py`
- `yesoncheck/player_annotations.py` (1,089줄): 수정 사항 주석(프레임별 텍스트·도형) UI와 재생 연동 (`PlayerAnnotationsMixin`) — 주석 모드 버튼은 켜짐을 빨강으로 표시(`ANNOTATION_MODE_BUTTON_STYLE`). `refresh_frame_annotations_display(redraw=True)`·`_redraw_frame_with_annotations(draw=True)`: `False`면 다시 그리기만 빼고 목록·상태 라벨·편집 대상 갱신은 그대로. `prepare_frame_for_display`·`burn_frame_annotations`는 네이티브 프레임(읽기 전용 IOSurface)을 복사·굽기 없이 그대로 돌려줌(복사본은 손잡이 없는 4채널 배열이라 GL 아이템의 RGB 길에서 실패) — 그 프레임의 B 키 글자·주석은 `videoWidget`의 아이템이 그림(공급자 `_annotations_for_native` — 보이는 프레임의 `annotation_store` 주석). 내보내기는 예전처럼 자체 캡처로 구움
- `yesoncheck/player_sidebar.py` (563줄): `PlayerSidebarMixin` — 드롭·파일 넣기·폴더 불러오기, 우클릭 메뉴·파일 복사, 작품 → 시즌 → job 콤보,
  선택한 영상을 A에 열기. 나머지는 아래 부모 믹스인 모듈에 있고 이 모듈은 옛 import 경로를 위해 일부 이름을 다시 내보냄
  - `yesoncheck/sidebar_bookmarks.py` (433줄): `SidebarBookmarksMixin` — 북마크 읽기·더하기·지우기, 북마크 관리 창(경로를 그 자리에서 고치기·우클릭 메뉴 — 아래 컴포넌트 역할), 북마크 폴더 열기
  - `yesoncheck/sidebar_playlist.py` (218줄): `SidebarPlaylistMixin` — 선택 재생(Play Selected) 재생목록 시작·차례대로 열기·없는 영상 건너뛰기 (`_playlist_selection`: Mov 탭은 Mov 목록 선택, All 탭은 mov만)
  - `yesoncheck/sidebar_config_paths.py` (883줄): `SidebarConfigPathsMixin` — 공유 설정 읽기 시작·창에 넣기·문제 알림, (Windows) 변환표 자동 설정,
    작품 경로 관리 창·`get_work_path`·관리 비밀번호
  - `yesoncheck/sidebar_refresh.py` (496줄): `SidebarRefreshMixin`·`SidebarScan` — 목록 항목 모델(출처·세대·다시 읽기 보류)과 목록 다시 읽기·목록 문제 알림
  - `yesoncheck/sidebar_all.py` (233줄): `SidebarAllMixin` — All 탭(`self.all_sidebar`): Mov·Seq 목록을 복제(clone)해 한 목록에 이름 자연 정렬로 섞음(시퀀스 글자는 테마별 하늘색 `ALL_SEQ_FG`,
    종류는 `ALL_KIND_ROLE`). 원본 모델(rowsInserted·rowsRemoved·modelReset·dataChanged)이 바뀌면 보이는 동안만 미뤄서 통째로 다시 만듦 — All은 늘 파생, 원본에서만 고침(선택 재생 강조도 이 길로 따라옴).
    누르면 종류대로 A에 열고, 우클릭은 'Mov만 모두 선택' + 선택을 원본 목록에 비춘 뒤 그 종류의 기존 메뉴(`_build_sidebar_menu`·`_build_seq_menu`). 선택 재생은 `sidebar_playlist._playlist_selection`이 All 탭에서 mov만 고름(시퀀스 연속 재생은 메모리 한계로 안 함).
    **목록 아래 개수 줄**(`self.sidebar_count_label` — `player_base`가 탭 바로 아래에 둠, 2026-11-06)도 여기: 원본 Mov·Seq 모델의 rowsInserted·rowsRemoved·modelReset과 탭 바뀜에 0ms 타이머로 미뤄 한 번(`_schedule_sidebar_count` — 인자를 버림: `QTimer.start`에 바로 이으면 탭 번호가 밀리초로 들어감) `_update_sidebar_count`가 **원본 목록에서** 셈(All 목록은 보일 때만 80ms 미뤄 다시 만들어지므로 거기서 세지 않음 — 숨은 탭의 변화도 셈). 글은 `sidebar_counts.count_text`
  - `yesoncheck/sidebar_counts.py` (105줄): 개수 줄의 글 — Mov `12개`, Seq `시퀀스 3개`(시퀀스 수), All `15개 — mov 10 · mp4 2 · tga 2 · exr 1`(확장자 소문자, 영상 포맷 먼저 그다음 시퀀스의 프레임 확장자, 각각 많은 순·같으면 이름 순). **종류마다, 그 안에 버전·테이크 괄호**(사용자 요청 셋을 거쳐 — FL_106 job이 `_TK1` 225 + `_TK1_HD` 225인데 450개로만 보였음 → Hazbin의 `_OSAN_v02`·`_OSRO_v01`도 → TK1·TK2·v001·v002도; 모양은 사용자 결정 '종류 안에 버전 괄호'): `kind_and_version`이 이름을 `_`로 나눠 **끝에서만** 봄 — 끝이 버전·테이크(`VERSION_TOKEN` — `TK`·`v` + 숫자, 대소문자 무시, `TK1`·`v01` 꼴로 보임)면 그것, 그 바로 앞이 ASCII 영문자뿐이면 종류; 끝이 영문자뿐이면 그것이 종류, 그 바로 앞이 버전·테이크면 버전; 첫 토막은 종류·버전이 아님(샷 이름). 끝의 하나만 보는 까닭: FL_106에 샷 코드가 `V005`인 샷(`FL_106_V005_TK1`)이 있어 `v` + 숫자를 어디서나 버전으로 보면 샷 코드를 버전으로 셈(실제 목록으로 찾음). `kind_version_text`: 종류 없는 묶음 `기본` 먼저, 종류마다 많은 순, 괄호 안 버전도 많은 순(같으면 이름 순), 같은 종류에 버전 없는 파일이 섞이면 `없음 n`(합이 맞게 — 내 결정), 종류도 버전도 없으면 나누지 않음. Mov `450개 — 기본 225 (TK1 225) · HD 225 (TK1 225)`, Seq는 시퀀스 이름(base)으로, All은 첫 줄 포맷·둘째 줄(`\n`) 종류(버전)(괄호 두 겹을 피함 — 내 결정). 실제 job 목록으로 확인: FL_106 위와 같음, KOTH 1604 `189개 — 기본 189 (v001 189)`, Hazbin 305 `638개 — OSAN 615 (v01 397 · v02 176 · v03 38 · v04 4) · TX 10 (v01 7 · v02 3) · PBRO 6 (v02 5 · v01 1) · OSRO 4 (v01 2 · v02 2) · OSFX 3 (v01 2 · v02 1)`. 인자 `sequences`는 (base, 프레임 확장자) 목록. Qt 없음
  - `yesoncheck/sidebar_open_with.py` (190줄): `SidebarOpenWithMixin` — Mov·Seq·All 우클릭 메뉴 맨 아래의 'QuickTime Player로 열기'(Mac만 — 고른 것 중 영상만, 영상이 없으면 꺼짐)·'다른 앱으로 열기 ▸'(등록한 앱마다 — 없어졌으면 `(찾을 수 없음)`으로 꺼짐, `앱 등록…`, `앱 지우기 ▸`)를 `_add_open_with_actions(menu, entries)`로 붙임. 세 `show_*_context_menu`가 부름 — `_build_sidebar_menu`·`_build_seq_menu` 안이 아님: All 메뉴는 원본에 비춘 선택이 아니라 All의 선택(`_all_open_entries`)을 넘겨야 섞인 선택이 다 감. 넘기는 것(목록 순서): 영상은 경로, 시퀀스는 첫 프레임 파일 — 메뉴에는 `SeqInfo`로 들고 있다가 **누를 때** `sequence_source.first_frame_path`로 실제 이름을 찾음(`SeqInfo.ext`는 늘 소문자라 `.TGA` 프레임은 대소문자를 가리는 NFS에서 `frame_name`을 그대로 이으면 없는 파일 — 리뷰에서 잡음; 메뉴를 만들 때는 NAS를 읽지 않음). 세 목록 모두 메뉴를 연 줄이 고른 것 밖이면 그 줄만 고른 뒤(Mov는 `show_sidebar_context_menu`가 이제 Seq·All처럼 맞춤 — 같은 메뉴의 파일 복사 등과 같은 선택) 고른 항목. 등록한 앱이 있는지는 메뉴를 만들 때마다 GUI 스레드에서 stat(네트워크 위의 앱이 끊겼으면 그동안 멈춤 — 알고 둠). 띄우기 전: 지금 없는 파일이 있으면 띄우지 않고 오류 창, `OPEN_CONFIRM_COUNT`(20)개를 넘으면 물음. 띄우기·등록·지우기 실패는 트레이스백째 오류 창(`error_window.show_unexpected` — `open_with.DllDirectoryRestoreError`면 '열었지만 DLL 검색 경로를 되돌리지 못했습니다 — … 다시 켜세요'), 설정 파일을 읽지 못하면 하위 메뉴 첫 줄이 꺼진 '설정 파일을 읽지 못했습니다'(툴팁에 사유·기록에 트레이스백 — 메뉴를 만드는 동안 모달 없음). 플랫폼은 메뉴를 만들 때 `sys.platform`(Mac·Windows가 아니면 붙이지 않음). 기록 `[다른 앱으로 열기] <앱>: 파일 n개 — <첫 파일>`
  - `yesoncheck/open_with.py` (279줄): 다른 앱으로 열기의 명령·등록한 앱 목록·띄우기 — Qt 없음. Mac: QuickTime Player는 `/usr/bin/open -b com.apple.QuickTimePlayerX <파일…>`(문서 열기 이벤트), 등록한 앱은 `open -n -a <앱> --args <파일…>`(**명령 줄 인자** — DJV 3.7.5는 문서 열기 이벤트를 받지 않아 `open -a <앱> <파일>`로는 앱만 켜졌음, 사용자 보고; 인자를 적는 가짜 앱으로 확인: 문서 열기는 인자 0개, `--args`는 공백·한글 경로 그대로; `-n`은 떠 있는 앱에도 인자가 닿게 새로 띄움; **파일마다 따로 띄움**(Mac·Windows — DJV 3.7.5는 인자로 여럿을 받아도 마지막 하나만 엶: `djv one.mov two.mov -exit -log` → `Files opened: 1`, 사용자 보고 '둘을 골라 열면 하나만'; 실패하면 거기서 멈추고 'n개 중 k개는 열었고' RuntimeError — 원인은 `__cause__`; Windows 빌드 앱은 DLL 검색 경로를 한 번 풀고 다 띄운 뒤 한 번 되돌림); 문서 열기로만 파일을 받는 Mac 전용 앱은 이 길로 파일이 안 들어감 — 알고 둠), `open`이 돌아오기를 `OPEN_TIMEOUT_S`(30초)까지 기다려 0이 아니면 RuntimeError(명령·출력 — `new_window`와 같은 모양). Windows: `[exe, 파일…]`을 앱 폴더에서(`cwd`) 기다리지 않고 띄움, 명령 줄 한도(`external_tools.WINDOWS_COMMAND_LIMIT`)를 넘으면 ValueError.
    **Windows 빌드 앱의 함정**: PyInstaller가 바꾼 것이 자식에게 그대로 가서 다른 Qt 앱이 이 앱의 Qt 플러그인·DLL을 읽을 수 있음(PyInstaller 문서 'Launching external programs from the Frozen Application', 6.14.1의 `pyi_rth_pyqt5`가 `QT_PLUGIN_PATH`·`QML2_IMPORT_PATH`를 넣고 PATH 앞에 `sys._MEIPASS`) → 빌드 앱이면 PATH에서 `_MEIPASS`와 **그 아래 폴더**(paddle이 불러올 때 `paddle\base`·`paddle\libs`를 PATH 앞에 넣음 — 리뷰에서 잡음)를 빼고, 값(`;`로 나눈 어느 조각이든)이 `_MEIPASS` 아래를 가리키는 다른 변수(`QT_PLUGIN_PATH`·`QML2_IMPORT_PATH`·`TCL_LIBRARY` 등)는 통째로 빼고(Windows 규칙 — `;`·대소문자 무시·`..` 풀기) `PYINSTALLER_RESET_ENVIRONMENT=1`. 부트로더의 DLL 검색 경로는 `_WindowsDllDirectory`(ctypes `GetDllDirectoryW`·`SetDllDirectoryW`)로 띄우기 전 값을 읽고 띄우는 동안만 NULL로 풀었다 **그 값으로** 되돌림(띄우기가 실패해도 — 뒤늦게 불러오는 이 앱의 DLL 때문에 풀어 둔 채 두지 않음; 풀지 못하면 띄우지 않고 OSError, 띄운 뒤 되돌리지 못하면 `DllDirectoryRestoreError`, 띄우기도 되돌리기도 실패하면 되돌리기 OSError에 띄우기 실패가 `__context__`로). 푼 동안 다른 스레드가 이 앱의 DLL을 이름으로 불러오면 못 찾을 수 있음(아주 짧음 — 알고 둠). 진짜 kernel32 묶기는 Windows CI의 시험 하나(`test_real_windows_dll_directory_binding_round_trips`)만 돌림
    등록한 앱 목록은 이 PC의 prefs.json `open_with_apps`(Mac `mac_prefs.prefs_path()`, Windows `%LOCALAPPDATA%\YesonCheck\prefs.json` — PR #25의 `windows_display.prefs_path`와 같은 파일): 더하기·빼기는 `mac_prefs.edit_prefs`(잠금 안에서 다시 읽고 고침 — 다른 창이 그사이 더한 앱을 지우지 않음), 글자 목록이 아니면 UserFileError(덮어 지우지 않음), 앱은 Mac `.app` 폴더·Windows `.exe` 파일만, 같은 경로는 `paths.same_path`로 한 번만
  - `yesoncheck/sidebar_sequences.py` (881줄): `SidebarSequencesMixin`·`SequenceExportDialog` — Mov·Seq·All 탭 전환과 Seq 목록(위아래 화살표로 고른 시퀀스를 A로 — `load_selected_seq_item`, `player_base.eventFilter`; 2026-11-06 전에는 누를 때만), 끌어다 놓은 프레임 파일 처리, Seq 우클릭 메뉴(A/B로 열기·MOV 만들기·썸네일·정보),
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
- `yesoncheck/video_widget.py` (1,209줄): 줌, 팬, ROI 선택 기능이 있는 커스텀 비디오 뷰포트 — 주석 모드 동안 오른쪽 위에 '주석 모드' 배지(마우스 투과), 텍스트 입력 요청은 '텍스트' 도구에서만(도형 도구의 드래그 없는 클릭은 무시).
  **GL 뷰포트(Mac 전용)**: cocoa에서만 `QOpenGLWidget` 뷰포트가 기본 — 풀스크린 재생이 레티나 CPU 확대 블릿 때문에 13.5fps로 떨어지던 것을 GPU 확대로 24.8fps로 되돌림(창 모드는 동일 — 2026-10-28 실측). Windows는 풀스크린 저하가 없고(사용자 실측) offscreen(시험·CI)은 QOpenGLWidget 미지원이라 raster 그대로 — CI의 실행 시험·`ci/screenshot_check.py`도 전부 offscreen/windows라 GL 경로는 CI를 타지 않음(cocoa 실기 확인 몫).
  `YESONCHECK_VIEWPORT=gl|raster`로 명시 전환(그 밖의 값은 ValueError — 조용한 폴백 금지, `viewport_mode`; 시험은 `tests/conftest.py`가 이 변수를 지우고 시작). cocoa 기본 GL은 먼저 `gl_context_available`로 컨텍스트 생성을 확인하고, 실패하면 기록에 바로 남기고 raster로 계속하며 사유를 `viewport_fallback_reason`에 남김 — 오류 창은 `app.launch`가 스플래시를 닫은 뒤 `show_viewport_fallback`으로(위젯 생성 중 모달은 `splash.finish`의 processEvents 안에서 열려 시작 순서를 멈추고 업데이트 '잘 켜짐' 표시까지 늦춤). 조용한 빈 화면 금지; 토글로 강제한 GL은 확인 없이 그대로(`viewport_forced`). GL일 때 지키는 것(전부 실측 근거): ① 블록 위치 — `setAcceptDrops(True)` 뒤·줌/배지 라벨 생성 앞(`setViewport`가 새 뷰포트를 쌓임 맨 위에 둬서, 라벨이 뒤에 만들어져야 가려지지 않음 — hole punch) ② `setViewport`가 끄는 뷰포트 마우스 추적 다시 켬 ③ `FullViewportUpdate` ④ MSAA 4(GL2 엔진의 AA는 MSAA뿐 — 없으면 와이프 선·ROI·주석 미리보기가 계단짐; FPS 영향 없음 실측) ⑤ `WA_OpaquePaintEvent`(없으면 창 스타일시트 폴리시 뒤 풀스크린이 다시 16fps — 스타일시트 배경을 매 프레임 CPU로 칠하게 됨) ⑥ 영상 주변 여백은 스타일시트 대신 `backgroundBrush`로 테마 색을 GPU가 칠함(`apply_theme_background` — 창 생성과 `set_dark_theme`/`set_light_theme`가 부름, 색 `VIDEO_BG`는 시트의 테마 배경과 짝). 알고 둔 한계: GL 선 AA는 MSAA라 raster의 해석적 AA보다 거칢(눈 확인 통과 기준), `GL_MAX_TEXTURE_SIZE`(보통 16384) 초과 프레임은 QPixmap 경로에서 미확인(GL 텍스처 스트리밍은 축소 없이 큰 실패 — 아래), raster를 골랐을 때는 로그가 없음(기록에 `[뷰포트] GL` 줄이 있으면 GL 경로), 컨텍스트 확인은 통과했는데 위젯 초기화(컨텍스트 공유·MSAA FBO)가 실패하는 드문 경우는 qWarning만 남음, GL이 안 되는 Mac은 창(프로세스)마다 폴백 알림이 뜸(조용히 넘기지 않는 쪽을 택함). 시험 `tests/test_gl_viewport.py`
  **GL 텍스처 스트리밍(2026-11-02 — GL 뷰포트일 때 기본)**: GL 뷰포트에서는 영상 아이템이 `VideoFrameItem(stream=True)`(`yesoncheck/gl_video_item.py`, 735줄)라 `updateFrame`이 `QImage`·`QPixmap`을 만들지 않고 RGB 배열을 `set_frame`으로 넘기고(와이프면 위에서 합성한 `result`, 아니면 `frame_a` 그 자체 — 복사 없음), 아이템이 `paint()` 안에서 `beginNativePainting` → 동기 `glTexSubImage2D(GL_RGB)` 한 번 → 고정 기능 텍스처 사각형(`GL_QUADS`; 필터는 `transformationMode()`가 Smooth면 `GL_LINEAR`, 가장자리 `GL_CLAMP_TO_EDGE`) → `endNativePainting`으로 그림. **왜**: 4K에서 `QPixmap.fromImage`와 Qt 내부 텍스처 변환·업로드가 프레임당 ~48ms(31차 실측 — `movie_pipe_source.py` 항목 '알고 둔 한계' ⑦의 병목)였고, 스파이크에서 이 경로가 그 약 1/3(네 실행 모두 0.27~0.39배), 동기 업로드가 PBO·client storage보다 느리지 않았음(그래서 PBO 없음). GL 함수 21개(2026-11-04에 네이티브 와이프용 `glScissor`를 더함)는 `yesoncheck/gl_bindings.py`(132줄)가 `QOpenGLContext.getProcAddress` + ctypes로 묶음 — 새 의존성 없음(PyOpenGL 안 씀), 앱 컨텍스트의 주소가 OpenGL.framework의 dlsym과 전부 같음을 실측해 macOS용 CDLL 분기는 두지 않음. 화면은 예전 QPixmap 경로와 같음(실제 화면 `screencapture -R` 대조 — 4K·1080p·1002×562 × 8장면 24쌍 최대 차 2·평균 ≤ 0.011), raster 경로는 아이템 클래스·`updateFrame` 줄이 글자 그대로(`ci/screenshot_check.py` 9장면 PNG 바이트 동일).
  선택 규칙(`use_stream_item(viewport_is_gl, mode)` — 플랫폼 조건 없이 뷰포트 종류를 따름): 뷰포트 결정(`mode`·`forced`·`gl_ok` — 폴백 기록 줄·`viewport_fallback_reason` 글은 그대로)을 `__init__` 맨 위, 영상 아이템 생성 앞으로 옮겼고 GL이면 `VideoFrameItem(stream=True)`를 와이프 선·ROI보다 먼저 `addItem`(쌓임 맨 아래 — 뒤에 끼우면 선이 가려짐), 아니면 기존 `scene.addPixmap(QPixmap())`. 어느 쪽인지는 `video_item_stream`. GL 적용 블록(setViewport 등)은 자리 조건 때문에 제자리(조건만 `if gl_ok:`). 토글 `YESONCHECK_VIDEO_ITEM=auto|gl|pixmap`(`video_item_mode` — 없거나 비면 auto, 대소문자 무시, 그 밖의 값 ValueError; `app.launch`가 스플래시 전에 검증, `tests/conftest.py`가 지우고 시작): `pixmap`은 킬 스위치(GL 뷰포트에서도 예전 QPixmap 경로), `gl`은 GL 뷰포트가 아니면 ValueError(raster 엔진에는 native painting이 없음 — 강제로 틀지 않음). 기록: GL 블록의 `[뷰포트] GL(QOpenGLWidget) 사용 …` 다음 줄에 `[표시] GL 텍스처 스트리밍(VideoFrameItem)` 또는 `[표시] QPixmap 경로(토글 YESONCHECK_VIDEO_ITEM=pixmap)` — **기록에 `[표시] GL 텍스처 스트리밍` 줄이 있으면 새 경로**, raster면 `[표시]` 줄 없음.
  지킬 것·함정(전부 실측 근거): ⓐ **스트림 모드의 `pixmap()`은 크기 자리표시자**(`set_frame`이 크기가 바뀔 때만 내용 없는 `QPixmap(w, h)`를 둠 — `isNull`·`width/height`·`boundingRect`·`fitInView` 계약용)이지 그림 내용이 아님 — 내용은 `frame()`(마지막 배열; 앱 안에서 픽스맵 내용을 읽는 곳은 없음). `set_frame` 뒤에는 그 배열을 고치지 말 것(컨텍스트가 바뀌면 같은 배열을 다시 올림), 비연속·dtype·채널이 어긋나면 ValueError(조용한 복사 없음) ⓑ **뷰포트로 쓰인 `QOpenGLWidget`은 `grab()`도 `grabFramebuffer()`도 내용을 못 찍음**(흰 그림 — 흰 그림 둘을 견주면 "차이 0"이 나옴) — GL 화면 검증은 `screencapture -R`(뷰포트의 전역 좌표 영역)로만 ⓒ 좌표: `painter.combinedTransform()`은 아이템 좌표 → **물리** 픽셀, `painter.device().width()/height()`는 **논리** 픽셀 → `glViewport`·`glOrtho(0, pw, ph, 0, -1, 1)`(y 아래 — Qt와 같음)은 논리 × `devicePixelRatioF()`를 **qRound처럼 `int(x + 0.5)`로** 반올림(파이썬 `round`는 은행가 반올림이라 dpr 1.5·논리 1487에서 2230 대 Qt의 FBO 2231 — 1px 작아져 아래·오른쪽 가장자리, 와이프·ROI 정렬에 이음매), 정점은 매핑값 그대로(정점에 dpr을 또 곱하거나 뷰포트를 논리로 잡으면 레티나에서 왼쪽 아래 1/4에 2배로 그려짐 — 스파이크 첫 실행) ⓓ **paint 가드**: PyQt5 가상 함수에서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음 — 아래 '새 창 · 동영상 열기 · 기본 앱'의 함정)이라 스트림 paint 본문 전체를 `except BaseException`으로 받아 첫 실패만 기록(`[표시] GL 텍스처 스트리밍 실패 …` + 트레이스백 전문) + 오류 창 1회(Qt 루프에서 `error_window` — paint 안에서 모달 금지; 끝 줄에 킬 스위치 안내)로 알리고 그 뒤로는 그리지 않음(빈 영상 영역 — 재생·UI는 계속; 알리다 또 실패하면 `_last_resort`). 걸쇠(`latched` — 읽기 전용 속성)를 푸는 길은 `reset_failure()`(2026-11-04): `_failed`만 풀고 다시 그리기 예약 — `failure_count`·GL 상태는 그대로(단계마다 성공한 뒤에만 기록하므로 다음 paint가 실패한 단계부터 다시; `_prepare`는 옛 컨텍스트 신호를 끊은 즉시 `_context = None` — 아니면 재설정 뒤 매 paint가 `disconnect` TypeError), 텍스처는 버리지 않음(paint 밖에는 current 컨텍스트가 없고, IOSurface에 묶인 면 텍스처를 놓으면 그 표면이 창을 닫을 때까지 남음). Mac의 창 글은 킬 스위치 안내 앞에 `DECODER_MENU_HINT` `Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식) 으로 바꾸면 예전 방식으로 재생합니다` ⓔ **엔진 없는 paint**: 컨텍스트가 생기지 않은 GL 뷰포트(offscreen에서 강제한 GL — 시험, 또는 위젯 컨텍스트 생성 실패)에서도 QGraphicsView는 paint를 부르는데 painter에 엔진이 없음 → 아이템마다 기록 한 줄(`[표시] 페인트 엔진이 없어 영상 프레임을 그리지 못함 …`)만, 창 없음·실패로 치지 않음(여기서 창을 띄우면 offscreen 시험의 모달이 끝없이 기다림 — `test_gl_viewport`가 멈췄던 원인) ⓕ GL 준비(함수 묶기·텍스처)는 생성 때가 아니라 첫 paint에서 그때 current인 위젯 컨텍스트로(위젯의 진짜 MSAA 컨텍스트는 첫 show 때 생김), GL 호출은 전부 native painting 안에서(들어가자마자 `check_error("native 진입 …")` — Qt 엔진이 남긴 GL 오류를 우리 업로드 탓으로 적지 않되 삼키지도 않고 ⓓ로), 업로드 뒤 `GL_UNPACK_ALIGNMENT`를 4로 되돌림(`finally` — Qt의 뒤이은 업로드에 1을 남기지 않음); 컨텍스트가 죽으면(`aboutToBeDestroyed`) 텍스처를 놓고 다음 paint가 새 컨텍스트에서 다시 준비·업로드 ⓖ **ES(ANGLE)·core profile 컨텍스트는 거부**(`GLBindingError` — 고정 기능 GL이 없음; 다른 경로로 몰래 돌지 않고 ⓓ의 실패 창 → `YESONCHECK_VIDEO_ITEM=pixmap` 또는 `YESONCHECK_VIEWPORT=raster`), `GL_MAX_TEXTURE_SIZE`(이 Mac 16384)를 넘는 프레임도 축소하지 않고 ⓓ로 크게 실패, 한도를 0으로 읽으면(컨텍스트가 current가 아님) 그것도 `GLBindingError`. 알고 둔 한계: 고정 기능 GL(2.1 호환 — Qt가 이 앱에 만드는 기본 컨텍스트) 전용이라 Windows 기본 GL 전환은 ES2/데스크톱 공용 셰이더 경로가 선행 조건, 텍스처는 `GL_RGB` 3바이트(BGRA가 업로드 ~8ms 빠르지만 `frame_a` RGB 계약을 바꿔야 함), 와이프는 numpy 합성 한 장을 올림(GPU 와이프 — scissor — 는 아래 네이티브 프레임의 `set_sides`만), RGB 면 첫 실패 뒤에는 그 창(프로세스)을 다시 켜거나 Mac에서 Settings → 재생 디코더 (Mac)를 고를 때까지 영상 영역이 빔(네이티브 면 실패는 아래 '큰 소리 폴백'), 4K 성능은 배치 부하 아래 실측뿐이고 하니스 틱은 설계 게이트(≤ 35ms)를 넘음(`movie_pipe_source.py` 항목 '알고 둔 한계' ⑦ — idle 재측정은 머지 전 내부 눈 확인 ①). **Windows**: 기본이 raster라 아무것도 바뀌지 않음; `YESONCHECK_VIEWPORT=gl`로 켜면 이 아이템도 켜짐 — Windows 실기는 미확인(ANGLE이면 ⓖ로 실패 창, 고DPI 1.25·1.5의 좌표는 스튜디오 PC 눈 확인 몫). CI는 GL 경로를 못 봄(offscreen = raster): 선택 규칙·토글·`updateFrame` 분기·`set_frame` 검증·paint 가드·GL 호출 순서와 좌표(가짜 GL 함수로 기록)는 `tests/test_gl_video_item.py`·`tests/test_gl_bindings.py`, 실제 그리기·성능은 cocoa 눈 확인(내부 저장소 `docs/superpowers/records/2026-11-02-gl-stream-design/eye-check.md` ①, 실측 `task4-gate.md`)
  **네이티브(IOSurface) 프레임 그리기(2026-11-04 — Mac의 ProRes(HDR 제외), 아래 'Mac 네이티브 재생')**: `updateFrame`은 A나 B가 네이티브 프레임(`frame_handles.native_surface_of`)이면 `_show_native_frames`로 감 — RGB 변환·numpy 합성 없음(예전 RGB 길은 글자 그대로).
  스트림 아이템(GL)은 `VideoFrameItem.set_sides(a, b, axis, ratio)`: 표면 전체인 네이티브 면(`whole_surface_handle`로만 가름 — 조각·뒤집힌 뷰는 ValueError, 복사하지 않음)은 `gl_surface.CGLTexImageIOSurface2D`로 `GL_TEXTURE_RECTANGLE_ARB` 텍스처에 그대로 묶고(CPU 복사 0, 텍스처 좌표는 픽셀 단위; 같은 손잡이면 다시 묶지 않음), RGB 면(혼합 A/B의 h264 등)은 면마다 따로 둔 2D 텍스처에 `set_frame`과 같은 업로드(같은 배열이면 다시 올리지 않음 — 넘긴 배열을 제자리에서 고치지 말 것).
  와이프는 GL scissor: A를 전체에, B를 `wipe_scissor`(물리 픽셀, GL 창 좌표 — 원점 왼쪽 아래; 나눔 자리는 `int(x + 0.5)` 반올림 뒤 [0, pw]·[0, ph]로 자름) 상자 안에 — `axis` "x" = 오른쪽, "y" = 아래, X·Y가 함께면 "xy"와 `ratio=(rx, ry)`로 상자 둘(numpy 합성의 합집합과 같은 그림). 와이프인데 B가 없거나 크기가 다르면 B 자리 검정(기존 `np.zeros_like` 규칙), 와이프가 꺼지면 B를 그리지도 쥐지도 않음. 블렌딩은 끔(BGRX의 X·4444의 알파가 섞이지 않게), 끝나면 실패해도 scissor·RECT·2D를 끄고 바인딩 0.
  자리표시자 픽스맵·`frame()`은 A를 따름. 아이템은 묶인 표면의 손잡이를 다음 묶기·컨텍스트가 죽을 때까지 쥠(버퍼가 VideoToolbox 풀로 돌아가 다른 프레임으로 덮이지 않게 — 면당 한 장). paint 가드(ⓓ)·컨텍스트 재생성(ⓕ)은 RGB 길과 같음(컨텍스트가 바뀌면 면 텍스처를 버리고 다시 묶음).
  픽스맵 아이템(킬 스위치 `YESONCHECK_VIDEO_ITEM=pixmap`·raster 뷰포트 — 느려도 되는 끄는 길)은 **A만**: 네이티브 A를 `QImage.Format_RGB32`(리틀 엔디언 BGRX 바이트 그대로, 행 간격 `strides[0]`)로 표면 메모리 위에 복사 없이 씌우고 그 배열을 `_pixmap_backing`에 다음 그림까지 쥠(RGB32 픽스맵이 그 메모리를 함께 씀) — 와이프 선은 보이지만 B는 그리지 않음. `display_path()`("gl"·"pixmap"·"raster")가 `[측정]` 줄의 `표시=` 값.
  **B 키 글자·주석은 굽지 않고 아이템으로**(네이티브 프레임은 읽기 전용): 흰 상자 `overlay_box_item`(z `OVERLAY_ITEM_Z` = 13 — ROI 10 위, 주석 미리보기 14·편집 핸들 16 아래)과 그 자식인 검정 글자 `overlay_text_item`(자식이라 z·넣은 차례와 상관없이 늘 상자 위, 보임/숨김도 상자 하나로 — `set_overlay_text`), 주석 층 `annotation_overlay`(`annotation_overlay.AnnotationOverlay`, z `ANNOTATION_OVERLAY_Z` = 13.5 — 굽는 길도 B 글자를 먼저, 주석을 그 위에 구움). 둘 다 장면 원점·프레임 좌표라 줌·맞춤에 구운 그림처럼 따라 커짐.
  `updateFrame`의 네이티브 분기가 한 곳에서 플레이어가 등록한 공급자(`set_overlay_provider` — 글자 또는 None, `set_annotation_provider` — 보이는 프레임의 주석 목록)에게 프레임마다 물어 갱신(`prepare_frame_for_display`를 거치지 않는 `_minimal_preview_seek`·편집 뒤 다시 그리기에서도 새 프레임); A가 RGB면(B만 네이티브 — 그때는 A에 구움) 숨기거나 비우고, RGB 길·빈 화면도 앞 네이티브 프레임의 아이템을 숨김.
  B 키 기하는 굽는 길과 같은 규칙(`overlay_text_layout.overlay_layout`): 기준선 (margin_x, 높이 − margin_y), 상자의 왼쪽·위는 구운 흰 상자와 같은 픽셀, 아래는 max(pad, cv2 꼬리, Qt 꼬리), 오른쪽은 Qt 글자 끝 + pad. 글꼴(`overlay_font`)은 앱 기본 글꼴의 대문자 높이(`QFontMetricsF.capHeight`)를 cv2 글자 높이에 맞추고 넘치면 줄임, cv2 획 3px 이상이면 Bold — 모양은 Hershey와 다름(사용자 결정 "같아 보이면 OK"); 대문자 높이를 잴 수 없는 글꼴이면 ValueError(크기를 지어내지 않음).
  **구운 그림과 다른 점(알고 둠 — 결함 아님, M1 눈 확인에서 그대로 둘지 판정)**: ① 와이프 선(z 0)·ROI(z 10)가 B 키 흰 상자 아래로 그려짐(구움 길은 선·ROI가 글자 위) ② 와이프를 켜도 네이티브 A의 B 키 글자·주석이 와이프 선에서 잘리지 않고 B 쪽까지 이어짐(구움 길은 B 반쪽이 덮음 — 주석은 GL 길에서 층 사각형을 A가 보이는 [0, w·rx)×[0, h·ry)로 자르면 맞출 수 있음) ③ 주석이 ROI·와이프 선 위 ④ 주석은 안티앨리어싱·레티나에서 더 또렷, B 키는 Qt 글꼴. 시험은 '테스트 전략'의 'Mac 네이티브 재생'; 실제 그리기(RECT+CGL 수락·레티나 좌표·글자 모양)는 M1 눈 확인 몫
  **네이티브 면 그리기 실패 → 이 창만 ffmpeg(큰 소리 폴백, 2026-11-04 — 스펙 §5.8)**: Intel까지 기본으로 켠 뒤 어떤 GPU·드라이버에서 `CGLTexImageIOSurface2D`가 실패하면 예비 전환만으로는 풀리지 않으므로 — `VideoFrameItem._fail`은 첫 실패 때 그리던 그림에 IOSurface 면이 있었는지(`has_native_side()` — 지금 그리는 `_sides`에 `handle`이 있는 면; B는 `set_sides`가 실은 때만, RGB `set_frame`은 `_sides`를 비움)를 값으로 실패 콜백(`set_failure_callback(cb|None)` — 부를 수 없는 값은 TypeError; 위젯이 등록해 `streamPaintFailed(bool)` 신호로 플레이어에)을 창 예약 **뒤** `QTimer.singleShot(0)`로 부름(paint 안에서 모달·캡처 교체 금지; 콜백 예외는 `_last_resort`). 창 첫 줄은 네이티브 면 + macOS + 콜백 등록이면 `NATIVE_FALLBACK_LINE` `네이티브 화면 그리기에 실패해 이 창은 ffmpeg 방식으로 바꿉니다(설정 파일은 그대로 — 다음 창은 다시 시도)`, 아니면 예전 `FAILURE_LINE`; 그 뒤 `<예외 종류>: <글>`, Mac은 `DECODER_MENU_HINT`, 끝 줄 `YESONCHECK_VIDEO_ITEM=pixmap 으로 켜면 예전 방식으로 그립니다`; stderr는 예전 그대로 `[표시] GL 텍스처 스트리밍 실패 — 영상 영역을 비워 둡니다 (탈출구: YESONCHECK_VIDEO_ITEM=pixmap)` + 트레이스백. 플레이어 `player_base._on_stream_paint_failed(native)`: RGB 면·macOS 밖은 아무것도 안 함(예전 규칙), 환경 변수가 덮으면(`on`/`off` — 다시 열어도 같은 디코더) 기록 `[표시] GL 텍스처 스트리밍 실패 — 디코더를 바꾸지 않음(우선: …) — 영상 영역은 비워 둠`만·걸쇠 유지, 그 밖은 캐시를 `set_preferred_decoder("ffmpeg", source=SOURCE_GL_FALLBACK)`(**prefs.json은 쓰지 않음** — 다음 창은 다시 네이티브) → 기록 `GL_FALLBACK_LOG` `[표시] GL 텍스처 스트리밍 실패 — 이 창을 ffmpeg 방식으로 바꿉니다` → `_swap_captures_and_settle_latch`(위 `player_base.py` 항목 — 바꿔 끼움 `[재생] 디코더 전환: A 캡처 바꿔 끼움 — …` → 조건부 `reset_failure` → 메뉴: ffmpeg 체크, 툴팁 `네이티브 화면 그리기 실패 — 이 창만 ffmpeg`). **고리 막기 규칙**: 걸쇠는 바꿔 끼운 뒤 아이템에 네이티브 면이 남아 있지 않을 때만 품 — 걸림 + 네이티브 면 + 유효 ffmpeg(`_latched_on_native_under_ffmpeg`)면 `KEEP_LATCH_LOG` 찍고 유지: 무조건 풀면 바꾸지 못한 쪽(ffprobe·열기 실패, 바꿔 끼우다 예외)의 같은 IOSurface를 다시 묶다 또 실패 → 창 → 폴백 → 창이 끝없이 되풀이됨. 걸쇠가 남은 창은 영상 영역이 빈 채 — 창 글이 권하는 메뉴 `ffmpeg (예전 방식)`을 (이미 유효해도) 고르면 다시 바꿔 끼우고 풂(`DECODER_RETRY_LOG`); VideoToolbox를 고르면 풀어서 다시 그려 봄(다시 실패하면 자동 폴백). RGB 프레임이 오면 저절로 푸는 안은 GL이 전반적으로 깨진 경우 프레임마다 창이 뜰 수 있어 채택 안 함. 진짜 `CGLTexImageIOSurface2D` 실패는 이 Mac에서 만들 수 없어 가짜 GL(CGL 컨텍스트 NULL)로만 증명 — `tests/test_native_paint_fallback.py`
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
- Mac 네이티브 재생 (2026-11-04 — Mac(Intel·Apple Silicon)의 HDR이 아닌 ProRes를 VideoToolbox가 IOSurface로 디코드하고 GL이 그 표면을 텍스처로 그대로 묶음, CPU 픽셀 일 0; 처음 PR은 Apple Silicon의 4K 4:4:4만이었고 다음 PR에서 Mac 전체 ProRes + Settings 메뉴 전환으로 넓힘; 사용자 설명은 README 'Mac의 ProRes 재생'):
  **왜**: M1 Mac mini(기본형, 16GB, 10GbE NAS)에서 1.6.1의 ffmpeg 파이프로 4K ProRes 4444 334장이 18.2~18.7초(≈18fps)인데 같은 M1의 QuickTime은 13.5초 — M1 기본형에는 ProRes 엔진이 없어 QuickTime도 소프트웨어 디코드이고, 차이는 디코드 뒤의 CPU 일(파이프는 한 장 25MB를 CPU가 여러 번 옮김). 처음 범위는 사용자 결정으로 Apple Silicon 4K만. **넓힌 까닭(사용자 결정 2026-11-04)**: 4K 4444 경로가 M1(2회차)과 Intel 모두에서 파이프를 재생 fps·파일 전환·스크럽 체감에서 앞섬 → "모든 파일을 이 방식으로, 재생 관련만"(ffmpeg는 파일을 만드는 기능에 남음); 4:2:2·태그 없는 파일도 포함(결정 때 근거로 든 'VideoToolbox = QuickTime과 같은 필터·화면 색'은 2026-11-05 실측에서 틀림 — 아래 '색'). h264·HEVC 네이티브는 취소(cv2 그대로). 예비로 ffmpeg 재생을 Settings 메뉴에 남김("혹시 몰라서" — 바로 적용, 창을 다시 켜지 않음).
  흐름: `_open_movie_capture` → `player_playback._native_or_pipe_capture`(게이트 — 위 `player_playback.py` 항목) → `mac_native_source.NativeVTCapture`(프레임 = `frame_handles.NativeFrameArray`) → `video_widget._show_native_frames` → `VideoFrameItem.set_sides`(`gl_surface` CGL) — 위 `video_widget.py` 항목의 '네이티브(IOSurface) 프레임 그리기'.
  실측: M1 기본형(스파이크 빌드 — 4K 4444 334장) 창 13.93초·전체화면 14.13초(≈24fps), 와이프(A·B 둘 다 네이티브) 23.06초(14.4fps — 소프트웨어 VideoToolbox 리더 둘이 각 16fps라 디코드 한계; 사용자 결정으로 와이프는 된 만큼); M1 2회차(빌드 02888a0): 단일·Play Selected 실시간, 4K 스크럽 즉시 체감, ↑↓ 전환 즉각, 누수 없음. Intel 이 Mac(i9-9900K·RX 5700 XT·10GbE NFS, 2026-11-05, 이 브랜치 — 파일을 OS 캐시에 미리 읽고, 측정 하니스는 App Nap을 끔(아래 '알고 둔 한계')): Play Selected 실파일 넷(334·97·159·245장) — 1080p 4:2:2 HQ 네이티브 25.0×4 대 파이프 24.9·24.9·25.0·25.0, 4K 4444 네이티브 25.0×4 대 파이프 23.4·22.6·22.9·23.3(25.0은 앱 재생 타이머의 상한 — 실제 틱 40ms; int(1000/24)=41ms 지정이 40ms로 도는 까닭은 미확인), 파일 전환 간격(앞 `[측정]` → 다음 열기 줄) 네이티브 0.11~0.16초 대 파이프 0.25~0.28초(1080p)·0.69~0.76초(4K); 와이프(같은 파일 A·B) 4K 네이티브 25.0 대 파이프 14.4, 1080p 둘 다 25.0; 먼 탐색 10번(`seek_to_frame` + 이벤트 한 번) 4K 네이티브 앞으로 41~47ms·뒤로 141~149ms(뒤로 재시작은 8장 미리 채움) 대 파이프 전체 캐시 뒤 13~30ms(채우기 전 46~909ms), 1080p 네이티브 18~20·42~47ms 대 파이프(캐시 뒤) 6~16ms; 1080p 4:2:2 HQ 네이티브 디코드만 ≈325fps(창 없이). 메뉴 전환(재생 중 4K): ffmpeg로 1.43초(와이프면 3.38초 — 파이프 열기가 GUI 스레드에서 ffprobe·열기를 함), VideoToolbox로 0.26초(와이프 0.58초), 번호·재생·와이프 B 오프셋 이어짐. 색: 4K 4444는 ffmpeg 파이프(bgr24) 대비 실파일 최대 1·평균 0.03; **1080p 4:2:2 HQ**(bt709 태그) 실파일은 평균 1.4·최대 73·4 넘는 픽셀 2.6%가 전부 홀수 열 — 색차(4:2:2 → 4:4:4) 수평 보간 필터 하나의 차이(가장자리 1픽셀).
  **색(2026-11-05 QuickTime Player 화면 실측으로 정정 — 이 Intel Mac, LG HDR 5K·DELL P2419H; M1·Monterey는 안 잼)**: 앱은 파일 값을 모니터 색 변환 없이 그림(VideoToolbox·ffmpeg 모두). QuickTime Player는 **파일 태그 → 색공간 → 모니터 프로파일**로 변환: 태그 없음·709 = `kCGColorSpaceCoreMedia709`(709 원색 + 감마 1.961), ICC 태그 = 그 프로파일(`CVImageBufferCreateColorSpaceFromAttachments`). 그래서 회색 128이 LG에서 QuickTime 139·앱 128, DELL에서 QuickTime은 초록 (32,191,32) → (0,191,48). 4:2:2 색차 경계도 셋이 다름 — 빨→파 전이 픽셀 QuickTime (63,61,218)·VideoToolbox (122,43,123)·ffmpeg 없음. `AVPlayerLayer`는 QuickTime과 픽셀까지 같음(실파일 평균 0.000). 맞는 것은 태그 없는 HD를 709로 읽는 해석뿐(ffmpeg swscale 기본은 601). QuickTime과 맞추는 일은 1.7 뒤로 미룸(사용자 결정) — 시험판과 측정은 내부(비공개) 저장소의 2026-11-04 기록 `quicktime-compare/`. VideoToolbox와 ffmpeg의 차이는 4:2:2 가장자리 보간(위)과 태그 없는 파일의 601/709 둘뿐이고, 그래서 Mac 화면은 1.6.1 이하의 Mac 화면(파이프)과도 그만큼 다름 — 의도된 변화.
  - `yesoncheck/mac_native_gate.py` (138줄): 쓸지의 판단만 — Qt·PyObjC·**파일 I/O 없음**, 어디서나 import. 토글 **`YESONCHECK_MAC_NATIVE=auto|on|off`**(`native_mode` — 없거나 비면 auto, 대소문자 무시, 그 밖 ValueError; `tests/conftest.py`가 `off`로 고정 — '테스트 전략'): `native_wanted()` — `off`는 킬 스위치(파이프), `on`은 켬 강제(macOS가 아니면 ValueError), `auto`는 **macOS(darwin)이고 선호 디코더 캐시가 videotoolbox면** 켬(칩 무관 — Intel·Apple Silicon·Rosetta 아래 x86_64 빌드; Windows·Linux는 설정과 무관하게 꺼짐; `platform_mod` 인자는 호출처·시험의 시그니처를 지키려고 받기만 함 — 옛 `is_apple_silicon`은 지움). **재생 디코더 설정**: 우선순위 환경 변수 `on`/`off` > `prefs.json`의 `"playback_decoder"`(`PREF_KEY`, 값 `DECODERS` = `videotoolbox`·`ffmpeg`) > 기본 `DEFAULT_DECODER` videotoolbox. 이 모듈은 파일을 읽지 않음 — `app.load_playback_decoder()`가 Mac에서 시작 때 한 번 읽어 프로세스 캐시에 넣고(`set_preferred_decoder(name, source=)` — `DECODERS` 밖은 ValueError, 캐시 그대로; `preferred_decoder()`), `native_wanted`는 캐시만 봄(열 때마다 I/O 없음 — 열기 도중 파일 오류도 없음). 메뉴가 바꾸면 캐시와 파일을 함께, 다른 창(프로세스)의 캐시는 건드리지 않음(다음에 켤 때 따라옴 — 창마다 디코더가 다를 수 있음). `effective_decoder()` = (지금 유효한 디코더, 출처) — 출처 글은 넷 + 실행 중 하나: `환경 변수 YESONCHECK_MAC_NATIVE=on|off`(머리 `환경 변수` — 메뉴가 `startswith`로 판정)·`SOURCE_PREFS` `prefs.json`·`SOURCE_DEFAULT` `기본값`·`SOURCE_FALLBACK` `prefs.json 읽기 실패 — 이 세션만 ffmpeg`, 그리고 `SOURCE_GL_FALLBACK` `네이티브 화면 그리기 실패 — 이 창만 ffmpeg`(플레이어의 큰 소리 폴백 — 파일은 그대로). 플랫폼은 보지 않음(Mac 전용 호출처가 씀).
    파일 게이트 `native_ineligible_reason(probe)`(양성 증거로만 켜지는 opt-in — 첫 어긋남을 조건 번호·받은 값과 한 줄로, 통과하면 None; `native_eligible`): ①~⑥ 파이프 게이트 그대로(`movie_pipe_source.ineligible_reason`을 부름 — 다시 구현하지 않음) → ⑦ 코덱 prores(① 파이프 대상이 늘어도 네이티브는 ProRes 디코더 전용) → ⑨ HDR 아님(`_hdr_reason`: 전달 함수 smpte2084·arib-std-b67을 **먼저** — 진짜 HDR은 원색도 bt2020이라 반대 순서면 PQ·HLG라는 이유가 가려짐 — 그다음 원색 bt2020; 사유 `⑨ HDR(smpte2084)`·`⑨ HDR(원색 bt2020)`). **크기·크로마(4:2:2·4:4:4·알파)·색 공간/범위 태그는 보지 않음** — 옛 ⑥½(4K)·⑧(4:4:4)·⑨의 태그 조건과 그 상수(`NATIVE_MIN_WIDTH/HEIGHT`·`NATIVE_PIX_FMTS`·`COLOR_SPACES_OK`·`COLOR_RANGES_OK`·`UNTAGGED` — 남아 있지 않음을 시험이 고정)는 지웠고 번호는 다시 매기지 않음(기록·문서의 `⑨ HDR(…)`이 그대로 읽히게).
    **왜 HDR만 거르나**: 4:2:2·태그 없는 파일도 포함(사용자 결정), 크기로 가르지 않음(모든 Mac·모든 ProRes가 같은 디코더·같은 색), HDR은 이 앱이 톤매핑을 하지 않으므로 SDR 행렬로 잘못 칠하지 않게 파이프에. 음성이면 파이프·cv2가 예전대로 돎(기록 `[재생] 네이티브(VideoToolbox): 아님 — <사유>: <이름>` 뒤). 읽는 값은 `probe_movie`의 필드(`pix_fmt`·`color_space`·`color_range`·`color_transfer`·`color_primaries`·`codec_tag` — ffprobe 글 그대로, 없으면 ""; 파이프 게이트는 보지 않음)
  - `yesoncheck/mac_prefs.py` (63줄): (Mac) 사용자 설정 파일 `~/Library/Application Support/YesonCheck/prefs.json` — `prefs_path()`(HOME을 부를 때마다 읽음 — 시험·업데이트 끝까지 시험은 HOME을 바꿈)·`read_prefs(path=None)`(없으면 `{}`, 깨졌거나 JSON 객체가 아니면 `UserFileError` — 빈 값으로 치지 않아 다음 저장이 덮어 지우지 않음)·`update_pref(key, value, path=None)`(`user_files.update_json` — 잠금 안에서 다시 읽고 그 키만, 다른 키·모르는 키 그대로, 원자적 쓰기; 잠금은 같은 PC의 프로세스 사이 전용)·`edit_prefs(edit, path=None)`(잠금 안에서 다시 읽은 dict를 `edit`가 제자리에서 고침 — 앞 값에 따라 정해지는 키용, 2026-11-06). `path`는 다른 위치(Windows `%LOCALAPPDATA%\YesonCheck\prefs.json` — `open_with`; `read_prefs`·`update_pref`의 `path=None` 고침은 PR #25와 글자 그대로 같게 둠 — 합칠 때 겹치지 않게). 키 `asked_default_video_app`(`default_app`)·`playback_decoder`(`app.load_playback_decoder`가 읽고 Settings 메뉴가 씀 — 값의 뜻·검증은 `mac_native_gate`)·`open_with_apps`(`open_with` — 사이드바 '다른 앱으로 열기'에 등록한 앱 경로 목록). 2026-11-04에 `default_app`에서 떼어 냄(`default_app` 시험 무수정 통과). NAS 공유 설정(`shared_config`)·Windows `settings.json`에는 넣지 않음 — Intel/Apple Silicon·사람마다 다른 선택이 서로 덮어씀. 시험 `tests/test_mac_prefs.py`
  - `yesoncheck/mac_native_source.py` (733줄): `NativeVTCapture` — `cv2.VideoCapture` 자리에 꽂는 캡처(`FFmpegPipeCapture`와 같은 계약·같은 낱말 — `isOpened`·`read`·`get`·`set`·`release`): `AVAssetReader` + 트랙 출력(`kCVPixelFormatType_32BGRA`, IOSurface 속성, `alwaysCopiesSampleData=False`)이 디코드한 CVPixelBuffer를 읽기 잠금하고 그 메모리 위에 `NativeFrameArray`(BGRX 읽기 전용 뷰)를 씌워 그대로 내줌 — 복사·색 변환·tobytes 없음(링에서 다시 내줄 때도 같은 객체).
    읽기 스레드(`native-vt-reader…`, 데몬 — `copyNextSampleBuffer` 동안 PyObjC가 GIL을 놓음)가 선읽기 `NATIVE_READAHEAD`=4장, 링 `NATIVE_KEEP_BEHIND`=8장(리더에서 최근 꺼낸 연속 구간 = 뒤로 재시작이 미리 채우는 장수), 앞으로 `NATIVE_SEEK_FORWARD_MAX`=24장까지는 꺼내 버리고 그보다 멀면 그 프레임 시각부터 `timeRange`로 새 리더(재시작 — 파이프와 같은 스트림 우선 순서·뒤로 재시작은 목표 8장 앞에서; 정상 상태 ~24ms, 프로세스의 첫 재시작만 ~190ms — 그래서 전체 프레임 캐시 없이 링만), 빈 큐 대기 한도 `NATIVE_READ_TIMEOUT_S`=30초.
    번호는 받은 순서가 아니라 PTS에서(`_frame_index` — `round((PTS − 트랙 시작) × r)`, CMTime의 value/timescale과 probe의 정확한 r을 `Fraction`으로 — 쌓이는 오차 없음), 시작 번호부터 빈틈 없이 이어지지 않으면 죽음, EOF 불변식(받은 수 == nb_frames — 일찍 끝나거나 넘치면 죽음). FPS·장 수·크기는 probe(파이프·cv2와 같은 출처). 캡처당 메모리 ≈ 13장 × 33.2MB ≈ 430MB — 전부 VideoToolbox의 IOSurface라 앱 RSS가 아니라 `VTDecoderXPCService` 쪽에 잡힘.
    지킬 것·함정(전부 실측 근거): ⓐ **샘플 버퍼 누수** — PyObjC 12.2.2 메타데이터에 `copyNextSampleBuffer`(Copy 규칙 +1)의 `already_cfretained`가 없어 샘플마다 참조 하나가 남아 CVPixelBuffer·IOSurface를 영구히 붙듦(M1 스파이크 빌드에서 `VTDecoderXPCService` 83GB) → `_pyobjc()`가 첫 리더 전에 `objc.registerMetaDataForSelector(b"AVAssetReaderOutput", b"copyNextSampleBuffer", {"retval": {"already_cfretained": True}})`를 한 번. 호출처마다 CFRelease를 더하지 말 것(하나라도 빠지면 다시 새고, 뒤의 PyObjC가 메타데이터를 넣으면 이중 해제) ⓑ **cancelReading은 읽기 스레드만** — GUI 스레드에서 cancel하면 그때 `copyNextSampleBuffer` 안에 있던 읽기 스레드가 AVFoundation 안에서 SIGSEGV(이 Mac, 재시작 연타에서 확률적으로). 재시작은 옛 리더가 하던 한 장을 마치고 스스로 멈춰 끝나기를 기다린 뒤 새 리더(같은 애셋의 리더 둘이 겹치지 않게 — 재시작이 디코드 한 장만큼 더 걸림) ⓒ 손잡이가 죽는 즉시 버퍼가 VideoToolbox 풀로 돌아가 다음 프레임으로 다시 쓰임 — 손잡이 없이 이 메모리를 가리키는 것(원시 memoryview·포인터)을 밖에 내주면 누수 대신 엉뚱한 픽셀; 프레임은 읽기 전용(제자리 쓰기 ValueError) ⓓ PyObjC는 `_pyobjc()` 안(잠금 아래 한 번 — 두 스레드의 첫 동시 import가 멈춘 일이 있음)에서만 — 이 모듈 자체는 PyObjC 없는 Windows에서도 빌드 모듈 검사가 import함.
    **실패(B 방식 — 파이프와 같은 모양)**: `NativeCaptureError`(원인·파일)는 열 때만(생성자·`open_native_capture` — PyObjC 없음·AVFoundation이 못 읽음·크기가 probe와 다름·리더를 시작하지 못함·첫 프레임이 한도 안에 안 오거나 번호가 0이 아님). 그 뒤의 도중 실패(리더 status failed·읽기 스레드 예외·번호 어긋남·30초 동안 프레임 없음·일찍 끝남/넘침·재시작 실패)는 남은 정상 프레임을 다 준 뒤 죽은 cv2 캡처의 겉모습(`is_dead`) + 기록(stderr) 즉시 1회(`VideoToolbox로 영상을 읽다가 도중에 실패해 …` + 파일·원인·트레이스백) + 오류 창 1회(Qt 루프 — 파이프의 `_window_relay`를 같이 씀, 끝 줄 `NATIVE_ESCAPE_HINT` = `탈출구(네이티브 재생을 끄고 ffmpeg 파이프로 엶): Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식) — 또는 환경 변수 YESONCHECK_MAC_NATIVE=off (그 실행만)`). M1 1회차의 재생 중 `-11821`(Cannot Decode)은 이 Mac에서 재현되지 않아(재시작 2,200번 남짓) 재시도 없이 이 길로 둠 — 그날의 누수와 겹쳐 있었음, M1 2회차에서 확인.
    **기록**: `open_native_capture`가 `[재생] 네이티브(VideoToolbox): <이름> (prores 3840×2160 24fps, 프레임 334, 32BGRA, hw=yes|no|?)` 한 줄(`NATIVE_LOG_PREFIX`) — **기록에 이 줄이 있으면 네이티브 경로**. `hw=`(`HW_LABELS` — `check_frozen_imports`의 결과 줄도 같은 상수)는 `VTIsHardwareDecodeSupported(코덱 FourCC)`: PyObjC VideoToolbox 래퍼가 있으면 그것, 없으면(빌드에는 넣지 않음) ctypes로 `VideoToolbox.framework`를 직접(`c_bool(c_uint32)` — `Boolean`은 unsigned char라 `c_int`면 틀림), `?`는 프레임워크·함수를 열지 못했을 때만(사유를 기록에 한 번). **능력 보고일 뿐(best effort)**: CI Apple Silicon 러너는 4444에 `yes`, 같은 호출을 쓴 스파이크는 M1 기본형에서 `no`, 이 Intel Mac은 `no` — `yes`를 ProRes 엔진의 증거로 읽지 말 것
  - `yesoncheck/frame_handles.py` (120줄): 네이티브 프레임 손잡이 — `NativeHandle`(IOSurface 포인터·크기·프레임 번호·keepalive = 버퍼 주인; 같음은 동일성)와 그 메모리 위의 `NativeFrameArray`(ndarray 하위 클래스 — `.native`, `wrap_native`가 만듦). Qt·PyObjC 없음. 픽셀은 (높이, 너비, 4) uint8 **BGRX** 뷰(행 끝 패딩이 있으면 strided — 넷째 채널은 알파로 읽지 말 것)라 배열을 그대로 쓰는 기존 코드는 손잡이를 몰라도 됨.
    수명: 모든 뷰의 `.base` 사슬이 손잡이를 쥔 작은 홀더(`_SurfaceBuffer` — `__array_interface__`)에서 끝나 `np.asarray`·`.view(np.ndarray)`·`np.ascontiguousarray` 같은 일반 뷰도 keepalive를 살리고, 한 방향(배열 → 홀더 → 손잡이 → keepalive)이라 순환 없이 마지막 뷰가 사라지는 즉시(gc 없이) 풀림. 전파는 `np.may_share_memory` — 슬라이스·reshape는 손잡이를 물려받고 copy·astype·ufunc 결과는 일반 ndarray.
    `native_surface_of(frame)`은 조각·뒤집힌 뷰에도 손잡이를 주고, `whole_surface_handle(frame)`은 shape·strides `(bytesPerRow, 4, 1)`·시작 주소·uint8이 표면과 정확히 같을 때만 — **GPU처럼 표면을 그대로 쓰는 쪽은 이것만**(조각·상하 반전·채널 역순 뷰를 표면으로 오인하지 않게)
  - `yesoncheck/gl_surface.py` (88줄): IOSurface → GL 텍스처의 CGL 함수(`CGLGetCurrentContext`·`CGLTexImageIOSurface2D`, 오류 글용 `CGLErrorString`)를 ctypes로 `OpenGL.framework`에서 묶음(`bind_cgl` — CGL은 GL 확장이 아니라 프레임워크 C API라 `getProcAddress`가 주지 않음; 프로세스에 하나) + `GL_TEXTURE_RECTANGLE_ARB`·`GL_BGRA`·`GL_UNSIGNED_INT_8_8_8_8_REV`·`GL_SCISSOR_TEST` 상수. 묶기 인자는 스파이크에서 확인한 `(ctx, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, w, h, GL_BGRA, GL_UNSIGNED_INT_8_8_8_8_REV, surface, 0)`. 어느 플랫폼에서나 import(프레임워크는 `bind_cgl` 때 엶), 못 열거나 함수가 없거나 CGLError ≠ 0이면 `GLBindingError`(코드·설명·IOSurface·크기) — 아이템의 paint 가드가 첫 실패를 크게 알림
  - `yesoncheck/annotation_overlay.py` (170줄): 주석 층 `AnnotationOverlay` — 네이티브 프레임의 주석을 굽지 않고 Qt 아이템으로(위젯이 층 하나를 장면에 두고, 데이터는 플레이어). 층은 장면 원점의 프레임 사각형(층 좌표 = 프레임 픽셀, 그리지 않음)이고 자식을 그 사각형으로 자름(`ItemClipsChildrenToShape` — cv2가 프레임 밖을 자르는 것과 같게), 주석마다 자식(사각형·타원·선·화살표 경로·글자)을 주석 차례대로 쌓고 프레임마다 값이 바뀐 것만 고침(`set_annotations`·`clear`).
    기하는 굽는 길과 **같은 함수** — `annotation_burn.annotation_spec`(좌표·기본 굵기·글자 크기)·`rect_corners`·`ellipse_center_axes`·`arrow_tip_points`·`annotation_font`로 굽기 코드를 나눴고 굽는 결과는 바이트 그대로(나누기 전 함수와 대조). 격자에 놓는 법만 아이템 몫: cv2 정수 좌표 p → p + 0.5(픽셀 가운데 — `PIXEL_CENTER`), 획 폭은 cv2가 그 굵기로 실제로 칠하는 폭(`burned_stroke_extent` — 굵기 3을 5px로), 둥근 끝·이음, 글자 기준선은 굽는 패치와 같은 자리(`TEXT_PATCH_INSET`). 구운 그림과 다른 점은 위 `video_widget.py` 항목
  - `yesoncheck/overlay_text_layout.py` (57줄): B 키 오버레이("File: <이름>, Frame: n/N")의 크기·자리 규칙 — 굽는 길(`player_playback.overlay_text` — cv2)과 네이티브 아이템 길(`video_widget.set_overlay_text`)이 함께 써서 어긋나지 않게: `overlay_metrics(너비, 높이)`(2026-11-03 규칙 그대로 `player_playback`에서 옮김 — `OVERLAY_TEXT_SCALE`·`OverlayMetrics`)와 `overlay_layout(text, 너비, 높이)` → `OverlayLayout`(배율·굵기·여백·cv2 글자 너비/높이/꼬리·들어갈 너비 — 넘치면 줄임). Qt 없음
- `yesoncheck/movie_pipe_source.py` (1,574줄): **ffmpeg 파이프 프레임 소스** — ProRes류 CFR mov를 번들 ffmpeg(`-f rawvideo -pix_fmt bgr24`, 출력 대상 `pipe:1` — 바이트가 오는 길은 아래 '전송')로 디코드해
  `cv2.VideoCapture` 자리에 꽂는 덕타이핑 캡처 `FFmpegPipeCapture`(`isOpened`·`read`·`get`·`set`·`release`, `ImageSequenceCapture`와 같은 계약)와 그것을 고르는 게이트.
  **왜**: 4K ProRes 4444(3840×2160 24fps)가 cv2로는 디코드만으로 22fps라 실시간에 못 미침. 원인은 cv2 내장 FFmpeg의 단일 스레드 픽셀 변환(12bit 4:4:4 → BGR)으로 **보임**(간접 실측 2026-10-29:
  번들 ffmpeg도 단일 스레드로 돌리면 8.5fps, cv2에 `OPENCV_FFMPEG_CAPTURE_OPTIONS="threads;0"`은 효과 없음 23.0fps) — 번들 ffmpeg의 디코드+bgr24 변환은 8코어를 써서 50.7fps(이 Mac Intel 8코어 실측;
  코덱·기계 탓이 아님 — 다른 재생기는 같은 파일을 실시간으로 틀었음). 새 의존성 없음(ffmpeg·ffprobe는 이미 번들, `external_tools` 경로).
  **앱 안에서의 실측(같은 Mac, 4K 4444 334장 처음부터 끝까지 재생)**: 처음 구현(stdout 파이프 전송) 22.0초(15.2fps) → 소켓 전송 18.54초(18.0fps) → 중복 그리기 제거 등을 거친 **16.57초(20.2fps)** — 링 보관본 복사를 읽기 스레드로 옮긴 판(그 이동은 되돌림)에서 잰 값. 그 뒤 표시 경로를 GL 텍스처 스트리밍으로 바꿔(2026-11-02, `video_widget.py` 항목) **13.60~14.54초**(배치 부하 아래 5회 — 같은 때 예전 경로 17.57~18.13초; idle 재측정은 머지 전 내부 눈 확인 항목).
  1080p ProRes는 실시간, **4K는 이 Mac에서 24fps 경계**(아래 '알고 둔 한계' ⑦), **Windows(raster) 4K ≈22fps**(한 바퀴 334장 15.1초)·**M1 Mac mini(2020·16GB, GL) 파이프 경로 ≈18fps**(18.4초) — 2026-11-03 스톱워치 실측(1.6.1; 24fps = 13.9초). 둘 다 GUI 스레드의 색 변환·업로드 변환을 없앤 BGRX 스파이크로도 그대로(아래 '알고 둔 한계' ⑦). (Windows 값은 2026-11-05에 타이머 한계로 밝혀짐 — '최근 변경 사항') 2026-11-04부터 Mac(Intel·Apple Silicon)의 ProRes(HDR 제외)는 네이티브 경로(`mac_native_source.py` 항목) — 이 파이프는 Windows와 Mac에서 ffmpeg를 고른 창·HDR ProRes 몫.
  - **게이트 `pipe_eligible(probe)`** (`probe_movie`가 ffprobe 1회로 `MovieProbe`를 읽음 — 2026-11-04부터 네이티브 게이트용 `pix_fmt`·색 태그·`codec_tag`도 담지만 이 게이트는 보지 않음; **양성 증거로만 켜지는 opt-in** — 한 조건이라도 확인 못 하면 거짓): ① 코덱 `prores`(`PIPE_CODECS`)
    ② `r_frame_rate` 유효(0 < r ≤ 240)이고 `avg_frame_rate == r`(Fraction 등식) ③ nb_frames ≥ 1·크기 ≥ 1 ④ **정확 등식** `Fraction(nb_frames,1)/r == duration_ts × time_base`(프레임 수·길이·속도 삼자 일치)
    ⑤ 회전 0이고 화소 비율(SAR) 없음/1:1 ⑥ 영상 트랙·컨테이너 시작 시각이 유한한 값(0이 아니어도 됨 — 탐색이 오프셋을 보정). 어긋난 첫 조건을 `ineligible_reason`이 조건 번호와 함께 한 줄로 알려 줌.
    ④⑤가 필요한 이유(전부 경계 클립으로 재현한 실측): 느슨한 비율(0.5%) 판정은 편집 목록으로 앞 2장이 잘린 파일(nb_frames 120인데 실제 118장 — cv2·ffmpeg 동일)과 한 프레임이 길게 머무는 파일(avg가 r과 0.33%만 다름)을
    통과시켜 EOF 불변식이 매번 거짓 경보를 내거나 정지 프레임 뒤부터 탐색이 한 칸 일찍 착지함. 회전 메타(90°) 파일은 ffprobe가 320×180인데 cv2는 180×320을 줘서 바이트 수가 같은 채 reshape만 조용히 깨짐. h264 등 나머지와 게이트 음성 ProRes는 기존 cv2 줄이 그대로 돎.
  - **진입점**: `maybe_pipe_capture(path, full_cache=False, probe=None)` 한 함수가 모드·판정·캡처 생성을 묶고(양성이면 캡처, 음성이면 `None`), `sequence_source.open_any_capture`(주석 내보내기 — 링)와 `VideoPlayer._open_movie_capture`(영상 열기 — `full_cache=True`, 아래 '전체 프레임 캐시'; 2026-11-04부터 `_native_or_pipe_capture`를 거쳐) 둘이 같은 함수를 부름 —
    판정 중복 금지. `probe=`는 플레이어의 네이티브 분기가 네이티브 게이트를 본 probe를 넘길 때(주면 ffprobe를 다시 돌리지 않고 그 값으로 모드·게이트·기록 줄 그대로). ffprobe가 파일을 못 읽을 때의 규칙(아래 '로그' — auto는 기록 + `None`, pipe는 `PipeCaptureError`)은 `probe_for_open(path, mode)` 한 곳에 있고 두 분기가 같이 부름. `_open_movie_capture`의 `PipeCaptureError`는 트레이스째 오류 창(끝 줄은 킬 스위치 안내) + `None`(`_open_sequence_capture`처럼 보던 영상은 그대로), `open_any_capture`는 받지 않고 그대로 올리며 `AnnotationExportWorker.run`의 기존 `except Exception`이 받아 error 신호로 알림.
    **기존 재생·탐색 코드는 수정하지 않음**(사용자 최우선 제약: 기존 파일 재생 무회귀) — 바뀐 열기 경로는 `_open_movie_capture`의 삽입 분기와 `open_any_capture`의 한 호출뿐이고, 기존 표시 코드를 바꾼 유일한 곳은 사용자가 승인한
    `update_frame`의 중복 그리기 제거(위 `player_playback.py` 항목). OCR·씬 감지·썸네일 워커, OCR 검토 창·타임라인의 미리보기 캡처는 `cv2.VideoCapture`를 직접 열어 cv2 그대로(4K ProRes에서는 여전히 느림 — 필요해지면 별도 작업); 미디어 정보 창은 2026-11-03부터 cv2 없이 ffprobe만(`media_info`).
  - **토글 `YESONCHECK_MOVIE_SOURCE=auto|pipe|cv2`** (진단·킬 스위치, `YESONCHECK_VIEWPORT` 선례): 없거나 비면 `auto`, 대소문자 무시, 그 밖의 값은 ValueError(조용한 폴백 금지) — `app.launch`가 시작 때 한 번 `movie_source_mode()`로 검증(스플래시 전).
    `cv2`는 킬 스위치(probe도 하지 않고 1.5.0 동작 그대로 — Mac 네이티브 판정보다도 먼저라 네이티브 토글도 읽지 않음). `pipe`는 ① 코덱만 면제하고 정확도 조건 ②~⑥은 유지(Mac에서 네이티브 게이트를 통과한 ProRes는 `pipe`에서도 네이티브 — 네이티브가 음성일 때의 강제) — 불통과면 열 때 `PipeCaptureError`로 크게 실패(어긋날 파일을 강제로 틀어 주지 않음),
    ffprobe가 파일을 못 읽어도 cv2로 조용히 가지 않고 같은 예외. 시험은 `tests/conftest.py`가 이 변수를 지우고 시작. 프레임 캐시 토글 `YESONCHECK_FRAME_CACHE`는 아래 '전체 프레임 캐시'.
  - **로그**(print): 파이프를 골랐으면 `[재생] ffmpeg 파이프: <이름> (prores 3840×2160 24fps, 프레임 334)` — **기록에 이 줄이 있으면 파이프 경로**. 게이트 음성이면 `[재생] cv2: <이름> (파이프 아님 — ② 프레임 속도가 일정하지 않음 …)`처럼
    사유 한 줄. `auto`에서 ffprobe가 파일을 못 읽으면(`RuntimeError` — 깨진 파일·확인 불가) 스택 트레이스·stderr 전문을 남기고 cv2로 엶(cv2도 못 열면 기존 오류 창). `ToolNotFoundError`(번들 ffprobe 없음)·probe 해석 오류(`KeyError` 등 코드 버그)·
    캡처 생성의 `PipeCaptureError`는 잡지 않고 그대로 올림. 전체 프레임 캐시를 원한 캡처(플레이어 A/B)는 첫 read에서 `[파이프] 프레임 캐시: …` 한 줄을 더 남김(아래 '전체 프레임 캐시').
  - **ffmpeg 명령**(`_pipe_command`): `ffmpeg -nostdin -v error [-thread_type slice] [-ss <t>] -i <파일> -map 0:V:0 -fps_mode passthrough -f rawvideo -pix_fmt bgr24 <출력>` — **`-thread_type slice`는 Windows만**(2026-11-09 — Mac은 예전 명령 글자 그대로: 사용자 요청 '1.8.0의 Mac은 그대로 유지', `tests/test_pipe_command.py`가 고정): 기본(프레임 스레드)은
    여러 프레임을 함께 디코드하느라 첫 장이 늦음 — 열기·탐색 재시작이 모두 그 첫 장을 기다림(Windows 선택 재생 전환의 약 70%). 이 Mac 4K 4444 첫 프레임 0.56초 → 0.17초, 334장 연속 48~49 → 52fps(OS 캐시에 올린 파일), 픽셀은 같음(실파일 334장·`-ss` 20장 bgr24 framemd5 일치). **`-fps_mode passthrough` 필수**(없으면 rawvideo가 CFR에 맞추려
    프레임을 복제해 섞음: 영상 start 0.5s 클립에서 파이프 132장 vs cv2 120장), **`-map 0:V:0`** 대문자 V(attached_pic 제외 — `probe_movie`가 고른 트랙과 같음; 소문자 `v:0`은 attached_pic을 포함). 경로는 인자 리스트 그대로(비ASCII 안전),
    Windows는 `subprocess_kwargs()`(CREATE_NO_WINDOW). 출력 대상은 POSIX `pipe:1`, Windows `tcp://127.0.0.1:<포트>?send_buffer_size=32768`.
  - **전송 — 왜 stdout 파이프가 아니라 소켓인가(실측)**: 처음에는 ffmpeg stdout 파이프를 읽었는데, 4K 한 장(24.9MB)이 64KB 파이프에서 ~467번의 read로 들어오고 호출마다 읽기 스레드가 GIL을 다시 잡아야 해서
    GUI 스레드가 파이썬을 실행 중이면(재생 틱의 `process_frame`·`update_frame`) 매번 switch interval(5ms)을 기다림 → 읽기 스레드 기아(메인이 GIL을 쥔 결정 실험에서 공급 28fps → 0.4fps, 실제 재생 15fps).
    소켓에서 `recv_into(..., MSG_WAITALL)`은 커널이 한 장을 다 채울 때까지 GIL을 놓은 채 syscall 한 번이라 **프레임당 recv 1회**(`recv_calls`로 시험이 구조 단언 — 무부하에서는 정확히 1회이고, 메모리 대역 경합 아래서는 커널이 `MSG_WAITALL`을 일찍 돌려준 일이 관측 1회(메모리 대역을 먹는 프로세스 4개 아래 295장에 +2) 있어 시험은 `프레임 수 + 1 + 2%`까지 허용; 조각 읽기로 돌아가는 회귀는 한 장에 수십~수백 번이라 여전히 잡힘) — 메인이 GIL을 쥐고 있어도 공급이 유지됨.
    **POSIX**는 `socketpair(AF_UNIX)`의 한 끝을 ffmpeg의 stdout으로 넘김(명령의 출력 대상은 `pipe:1` 그대로; `Popen` 직후 부모에서 자식 쪽 끝을 닫아야 EOF가 옴). 측정(4K 정상 상태 60장, 메인 idle/40ms GIL 쥠):
    ffmpeg가 직접 여는 `unix://` 리스너 12~22fps(macOS 로컬 소켓 기본 버퍼가 8KB이고 ffmpeg unix 프로토콜에 버퍼 옵션이 없음), TCP 루프백 21~33fps, socketpair 30~43fps — 가장 빠르고 리스너·임시 폴더·경로 길이·접속 상대 확인이 없음.
    **Windows**는 socketpair 끝을 자식 stdout으로 넘길 수 없어(소켓 핸들은 CRT fd가 아님) 127.0.0.1 임시 포트 TCP 리스너에 ffmpeg가 접속(`accept`는 하나만, 상대가 127.0.0.1인지 확인, 대기 한도
    `CONNECT_TIMEOUT_S` = `READ_TIMEOUT_S`). **소켓은 blocking, 타임아웃 없음**: `settimeout`은 CPython이 내부적으로 non-blocking으로 바꾸는데 Windows는 non-blocking 소켓의 `MSG_WAITALL`을 거절하고
    (macOS에서는 `settimeout`의 타임아웃이 `MSG_WAITALL` 수신의 첫 바이트까지만 적용됨 — 구현자 실측) — 멈춘 ffmpeg 보호는 `take(READ_TIMEOUT_S)` 실패 → `stop()`의 shutdown+close+kill이 막힌 recv를 깨우는 길로. 버퍼 `SOCKET_BUFFER_BYTES` = 64KiB — 근거는 처리량뿐
    (8KB 26~29fps → 32KB부터 꺾여 34~39fps, 64KB·128KB·4MB는 잡음 수준이라 더 키워도 안 빨라짐; **Windows TCP의 절반씩(32K+32K)은 재 보지 않은 값**). 시험 `tests/test_movie_pipe_transport.py`는 Windows 경로를
    `sys.platform` 바꿔치기로 이 플랫폼에서도 돌림(Windows 실기는 CI).
  - **세션과 선읽기**: `_PipeSession` = ffmpeg 프로세스 하나 + 전송 소켓·읽기 스레드·stderr 스레드(상시 비움)·유한 큐·정지 플래그 한 덩어리. 탐색 재시작·`release`가 세션을 통째로 버려 옛 프로세스의 프레임·실패가 새 큐에 섞이지 않음. 소켓은 읽기 스레드만 읽음.
    선읽기 `READAHEAD_FRAMES=6` — 디코드와 표시를 떼어 프레임당 시간이 합이 아니라 max가 되게 하고 NAS 순간 끊김을 누그러뜨림; 큐가 비면 채워질 때까지 기다림(자연 감속, 프레임을 건너뛰지 않음).
    **보관과 복사(`_FrameStore`)**: 세션에서 꺼낸 프레임은 내주든 버리든 그 번호로 보관본 `_FrameStore`(번호 → 배열, 가득 차면 가장 오래 전에 넣은 번호부터 내보냄 — FIFO, 같은 번호는 교체)를 지남. 보관은 **세션이 준 배열 그대로**(읽기 스레드가 프레임마다 새 배열을 할당하고 아무도 고치지 않음 — 재사용 버퍼 없음)이고
    호출자에게는 늘 **새 복사본**(`copy()`)을 줌 — 복사는 내주는 프레임마다 한 번, `read()`가 GUI 스레드에서 함(4K 24.9MB ~2.7ms 실측 — 호출자 배열은 틱마다 놓여 할당자가 재활용). 호출자가 받은 배열을 고쳐도 보관본은 그대로.
    (1.5.1은 반대로 보관본을 재사용 버퍼 8개에 덮어쓰고 원본을 내줬는데, 전체 모드에서 보관본을 매번 새 배열로 복사하면 새 페이지에 쓰는 비용이 10.5~11ms라 바꿈 — 링 모드도 같은 방식.) 캡처의 보관본은 둘: **링 `_ring`**(`KEEP_BEHIND=8`장, 주 세션에서 꺼낸 프레임이 지나는 곳 — **두 모드 모두** 읽는 동안은 여기만, 재시작·`release`에서 비움 — 보관 번호가 늘 최근 꺼낸 연속 구간이라 1.5.1의 링과 같음, 단 뒤로 재시작은 목표 8장 앞에 착지해 그 장들을 보관 — 아래 '탐색')과
    **전체 저장소 `_full`**(전체 모드만 — 파일 장수까지, 재시작을 건너 남음, **쉬는 시간 채움기만 씀** — 아래 '전체 프레임 캐시'; 링 모드는 0장). 복사를 읽기 스레드로 옮겨 본 판(버퍼 풀 재활용)이 있었으나 **되돌림** — 틱 ~3ms 절감이 paint 병목 아래에서 fps를 바꾸지 못하고, 캡처당 메모리가 약 174MB(쌍 7장분) 늘고, 메모리 대역 경합 때 읽기 스레드 공급이 약해지고 시험이 불안정했음(재검토 실측).
    **캡처당 메모리(4K bgr24 24.9MB/장, 십진)**: 링 모드는 선읽기 큐 6장 ≈149MB + 보관 8장 ≈199MB + 읽기 스레드가 손에 든 1장 ≈25MB ≈ **~373MB**, A/B 와이프에 4K 둘이면 **~750MB**. 전체 모드는 여기에 **채움기 세션**(선읽기 큐 6장 ~150MB + 손에 든 1장 — 처음 쉬는 때 띄워 다 채울 때까지)과
    **전체 저장소**(쉬는 동안 채운 만큼, 다 차면 4K 13.9초 334장 **≈8.3GB**, 1080p 334장 ≈2.1GB)가 더해져 A/B에 4K 둘이면 **≈16.6GB + 링 둘**. 호출자가 쥔 프레임(플레이어의 `frame_a` 등)과 플레이어 자체 `frame_cache`(드래그 미리보기 RGB 복사 — 기존·무수정, 4K 50~300장 1.2~7.5GB)는 따로라
    4K A/B 전체 모드의 최대는 ~25GB. 보관본은 `release`·죽음에서 바로 비움(파일을 닫으면 메모리가 돌아옴). 스레드는 데몬, GUI 스레드는 무한 join하지 않음(NFS hard mount에서 kill해도 안 죽는
    프로세스는 데몬 스레드가 거둠). `weakref.finalize`가 `release` 없이 버려진 캡처의 ffmpeg를 끝냄. A/B 와이프는 ffmpeg 2개.
  - **탐색**: `set(CAP_PROP_POS_FRAMES, n)`은 **지연(lazy)** — 목표만 기록하고(cv2처럼 0~count로 자르고 소수 버림, `get`은 곧바로 그 값) 실제 이동은 다음 `read()` 머리에서 목표 n으로 — **스트림 우선**:
    ① n == 스트림 위치(`_stream_pos` — 세션이 다음에 줄 번호, 재시작에서 시작 번호로·꺼낼 때마다 +1) → 스트림에서 꺼내 내줌(이미 보관된 번호여도) ② 보관본에 있음 → 그 복사본(세션 그대로 — 링 모드는 최근 꺼낸 `KEEP_BEHIND=8`장: 뒤로 한 칸이 재시작 없이,
    없으면 4K에서 449~634ms로 cv2의 329~372ms보다 느려지는 실측 회귀; 전체 모드는 링 다음에 채움기가 채운 전체 저장소도 봄) ③ 스트림 위치 < n ≤ 스트림 위치 + `SEEK_FORWARD_MAX=24` → 꺼내 버림(버린 것도 보관) ④ 그 밖 → `-ss` 재시작 — 앞으로(n > 스트림 위치)는 목표에서 바로(`SEEK_BACK_K=0`),
    뒤로(n < 스트림 위치)는 목표 `KEEP_BEHIND`(8)장 앞(0에서 자름)에서 띄워 그 장들을 꺼내 버리며 보관(**뒤로 재시작 미리 채우기** — 아래).
    **①이 ②보다 먼저인 까닭**: 보관본을 먼저 주면 되감아 재생할 때 스트림이 보관 구간 앞에 서 있게 되어(100~200을 본 뒤 0으로 되감아 재생 → 100~200을 보관본에서 주는 동안 스트림은 100에 서 있다가 201에서 101장 앞이라 재시작) 1.5.x에 없던 끊김이 생김 —
    스트림이 제자리면 스트림을 따라가므로 보관 구간을 벗어날 때의 재시작은 많아야 한 번.
    **재시작 `-ss`는 `t = n/r + (영상 트랙 start − 컨테이너 start)`로 트랙 오프셋 보정 필수** — `-ss`는 컨테이너 start 기준이라 빼면 영상 start 0.5s 파일에서 12프레임 앞에 착지(`external_tools`의 선례와 같은 보정).
    지연 set은 연속 set을 이동 한 번으로 합칠 수 있지만 **앱에서는 그 병합이 발동하지 않음** — 앱의 모든 탐색 경로(`seek_to_frame`·`_quick_preview_seek`·`_seek_direct_fast` 등)가 set 직후 read함
    (그래서 슬라이더 드래그도 미리보기 장마다 이동하고, 새 파일을 열 때 옛 캡처의 `seek_to_frame(1)`도 실제로 돎 — 아래 '알고 둔 한계' ⑧⑨).
    **뒤로 재시작 미리 채우기(2026-11-02, 사용자 보고 — 4K ProRes에서 →는 즉시인데 ←가 느림)**: 예전에는 재시작한 세션이 목표에서 시작해 그 앞이 하나도 없어, 링(8장) 밖으로 뒤로 가면
    ← 한 번마다 재시작(~0.5초)이었음(슬라이더로 안 본 구간에 뛴 뒤 ←를 눌러도 마찬가지). 이제 **뒤로 재시작은 목표 8장 앞에서 띄워 그 8장을 보관 → ←는 8번에 한 번 재시작(약 0.6초 — 재시작 ~0.5초 + 디코드 8장 ≈0.16초), 나머지는 보관본에서 즉시**.
    링은 8장 FIFO라 목표를 넣을 때 맨 앞 장이 밀려나 착지 뒤 링은 목표−7..목표(← 7번 즉시, 8번째에 다음 재시작 — 20에서 시작하면 재시작은 20·12·4) — 전체 모드도 같음(미리 채우기는 링에만 씀; 채움기가 이미 채운 번호면 애초에 재시작하지 않음).
    **앞으로 점프는 그대로**(링 밖이거나 24장을 넘게 앞 — 슬라이더를 앞으로 끄는 경우): 목표에서 바로 띄우고 미리 채우지 않아 느려지지 않음. 앞으로 가는 방향은 큐·스트림에서 이어짐.
    미리 채우는 장수는 따로 상수를 두지 않고 `KEEP_BEHIND`(링 깊이)를 그대로 씀 — 링을 끄면(시험의 `KEEP_BEHIND=0` 갈래) 미리 채우기도 꺼짐. 미리 채우는 동안 `pos`는 목표 그대로(다른 스레드의 `get(POS_FRAMES)`가 목표 앞 번호를 보지 않게).
    **전체 모드에서 채움이 끝난 뒤에는 파일 어디로든**(←·휠·슬라이더 드래그 미리보기·되감기·반복 재생의 처음으로) 보관본 복사라 재시작 0 — 채우기 전(또는 아직 안 채운 번호)은 링 모드와 같음.
  - **전체 프레임 캐시(2026-11-02, 스펙 §6·§6.5 — fps가 아니라 스크럽 체감)**: 파일의 모든 프레임을 메모리에 둬 되감기·탐색을 재시작 없이. **opt-in**: `full_cache=True`는 플레이어 A/B를 여는 `_open_movie_capture`만 넘기고,
    주석 내보내기 워커(`open_any_capture`)·빌드 앱 smoke는 한 번 순차로 읽을 뿐이라 링(예산도 차지하지 않음).
    **쉬는 시간 채우기(설계 변경 — 스펙 §6.5 방식 B, 사용자 결정)**: 처음 판은 재생 중 내준 프레임을 모두 붙잡았는데, 4K 첫 재생이 **16.0~16.2초 vs 링만 13.7~14.6초** — 장마다 24.9MB를 새 메모리에 붙잡는 일 자체(메모리 대역·VM)가 장당 GUI ~8ms를 먹었음(read는 두 모드 모두 3~4ms, 미리 페이지를 확보한 버퍼 풀도 효과 없음 — 17.0·16.6초).
    그래서 **읽는 동안은 전체 모드도 링(8장)만** 두고, **이 프로세스의 어느 파이프 캡처도 `IDLE_FILL_DELAY_S`(0.3초) 동안 read하지 않을 때만** 채움기 `_Filler`(캡처당 하나, 데몬 스레드 — 처음 쉬는 때 자기 ffmpeg 세션을 주 세션과 같은 명령·전송으로 `-ss` 없이 처음부터 띄움)가 프레임을 차례로 꺼내 전체 저장소에 그 번호로 넣음 —
    **4K 334장 약 7초(이 Mac, 배치 부하 없을 때), 1080p ~2초**. read가 오면(재생·드래그 — 24fps는 42ms 간격) 그 장을 넣고 다음 장부터 멈춤: 꺼내지 않으면 ffmpeg는 소켓에서 저절로 멈춤(CPU 0, `FILL_POLL_S`=50ms마다 다시 봄). 쉬는 때는 read가 들어올 때·나갈 때의 시각과 read 중인 수(`_ReadClock` — read 안의 재시작이 길어도 쉬는 때가 아님)로, **자기 캡처의 시계와 프로세스 시계 `_PROCESS_READS` 둘 다** 봄:
    A/B를 열고 와이프를 끈 채 A만 재생하면 플레이어는 B를 read하지 않는데(와이프가 켜져 있을 때만), 캡처마다만 보면 B의 채움기가 쉬는 줄 알고 8스레드로 디코드해 A의 재생과 다툼(최종 검토 Ruling 11) — 그래서 프로세스 전체 기준.
    주석 내보내기 워커(링 모드 캡처)의 read도 프로세스 시계를 움직여 그동안은 채우지 않음(디코드를 다투지 않음).
    채움기는 캡처를 붙잡지 않음(캡처의 잠금·전체 저장소·read 시계만 받음 — 버려진 캡처의 GC가 늘 돎), 넣을 때만 캡처의 잠금을 짧게 잡고 소켓을 기다리는 동안은 잡지 않음. 다 채우면 정상 끝(EOF — 넘침 검사)을 확인하고 채움 세션을 정리하고 기록 한 줄 `[파이프] 프레임 캐시 채움 끝: 334장 8.3GB (7.0초) — <파일>`(초는 채움 세션을 띄운 때부터 — 그사이 쉰 시간 포함).
    **채움기 실패**(채움 ffmpeg 사망·이른 끝·넘침·30초 동안 프레임 없음·띄우지 못함)는 캡처의 죽음이 아님 — 기록 한 번 `[파이프] 프레임 캐시 채움을 멈췄습니다 — …`(`FILL_FAILURE_HEADLINE` — 채운 장수·사유(트레이스백이 있으면 함께)·파일·명령·stderr) + 채움 중단, 재생·탐색은 링·재시작으로 그대로, **오류 창 없음**(스펙 §7-19 — 틀리면 비용: 채움 실패를 기록에서만 앎). 넘침이면 번호를 믿을 수 없어 채운 것을 비우고, 그 밖은 이미 넣은 장을 둠. 다시 채우지 않음.
    실패하면 **예산 장부의 몫을 곧바로 채운 만큼으로 줄임**(`_LEDGER.shrink` — 채우지 못한 몫은 다른 캡처가 씀; 채운 장과 그 몫은 release까지 남음, 이미 반환된 키는 되살리지 않음).
    채움 세션은 처음 쉬는 때 띄우되 Popen 바로 앞에서 정지 플래그를 다시 봄(그사이 release·죽음이면 띄우지 않음).
    `release`·죽음은 같은 잠금 안에서 두 저장소를 비우고 채움기를 세운 뒤(그 뒤 한 장도 넣지 못함) 채움 세션을 끝냄, release 없이 버려진 캡처는 캡처 단위 `weakref.finalize`가 채움기를 멈춤(장부 반환과 같은 사슬). 채우는 동안 안 채운 구간의 스크럽은 링 모드처럼 재시작(뒤로는 미리 채우기 포함 ~0.6초).
    읽기 규칙 ②는 링을 먼저, 그다음 전체 저장소(`self._ring.has(n) or self._full.has(n)`); 주 세션의 재시작·미리 채우기는 링에만 씀. **전체 저장소에서 내줄 때는 스트림을 보관본 끝으로 옮겨 둠**(2026-11-06 — `_store_frontier`·`_restart(…, park=True)`): 채움기가 앞부분만 채운 채 처음으로 돌아가면(반복 재생) 보관본을 내주는 동안 스트림은 멀리(파일 끝) 서 있다가 보관본이 끝나는 곳에서야 재시작해 재생 도중에 멈췄음(Windows 4K 2·3바퀴째 0.75·0.84초 — `ring`이면 0.1초 안팎). 그래서 전체 저장소에서 n을 내주면(링이 아니라) n 다음으로 저장소에 없는 첫 번호로 스트림만 옮겨 두고(`pos`는 그대로 — 지금 내주는 자리), ffmpeg가 그동안 준비해 끝에 닿을 때 ①로 이어짐. 파일 끝까지 다 있거나, 스트림이 이미 그 구간 안(n < 스트림 위치 ≤ 보관본 끝 — 재생이 스트림에 닿을 때까지 보관본)이면 옮기지 않음: 멈춘 동안 채움기가 보관본을 늘려 끝이 움직여도 다시 옮기지 않고(→를 천천히 눌러도 ffmpeg를 매번 띄우지 않음), 재생 중 스트림이 보관본 안에 있을 때 링 밖으로 뒤로 가도 옮기지 않음(리뷰에서 잡음). 옮겨 두기는 **링을 비우지 않음** — 보던 자리(링)로 돌아갈 때 재시작이 없게(링은 번호로 찾으므로 옛 장이 남아도 번호는 맞고, 새로 꺼낸 장이 들어오면 FIFO로 밀려남; 그래서 전체 모드에서는 '링 = 스트림 바로 앞의 연속 구간'이 아닐 수 있음). 옮기다 실패하면 `_restart`의 죽음 길(B) — 이 프레임은 그대로 내줌, 기록·창의 머리는 '보관본 끝(N번)으로 스트림을 미리 옮기려고…'. 알고 둔 비용: 선택 재생이 아닌 열기(사이드바 클릭·↑↓)의 `stop_video` → 옛 캡처 `seek_to_frame(1)`이 0을 보관본에서 내주면 놓을 캡처에도 한 번 옮겨 둠(ffmpeg 하나를 띄웠다 곧 끔 — 받아들임), 보관본 끝을 찾을 때 저장소를 훑음(4K 수백 장이면 무시할 만함). 시험용: `fill_done`·`fill_index`·`fill_failed`·`fill_session`(채움 세션은 `_PipeSession(…, is_filler=True)` — 시험이 재시작 횟수와 따로 셈)·`wait_fill(timeout)`.
    **판정은 첫 `read()` 머리에서 한 번**(`_decide_cache` — 생성자가 아니라): `open_file`이 새 캡처를 연 뒤 옛 캡처를 놓고 첫 프레임을 읽으므로, 생성 때 재면 나가는 파일 몫이 장부·사용 가능 메모리에 잡혀 4K를 4K로 바꿀 때 늘 링이 됨.
    첫 read 전에는 아무것도 보관하지 않아(생성자가 받은 첫 프레임은 세션 큐에) 모드 전환이 공짜. 판정 결과는 `cache_mode`(`None` 첫 read 전·`"ring"`·`"full"`).
    **예산**(`frame_cache_budget.full_cache_decision` — probe로 셈, 파일을 읽지 않음): `total = W×H×3 × nb_frames`가 ① `물리 RAM × FULL_CACHE_RAM_FRACTION(0.20) − committed` 이하이고
    ② `total + FULL_CACHE_HEADROOM_BYTES(2GiB) ≤ 지금 사용 가능 메모리 − committed`일 때만 전체(committed = 다른 살아 있는 전체 모드 캡처들이 잡은 바이트의 합) — ①을 먼저 봄, 메모리는 `psutil.virtual_memory()`.
    ②에서도 committed를 빼는 까닭(최종 검토에서 고친 식): 장부는 보관을 **잡은** 바이트이지 **채운** 바이트가 아님 — 보관은 판정 뒤 쉬는 동안 채움기가 채우는 만큼 차므로 A/B 둘 다 자기 첫 프레임에서 판정할 때는 어느 쪽도 아직 차지 않아
    사용 가능 메모리가 앞 캡처의 몫을 반영하지 않음(빼지 않으면 128GiB·사용 가능 15GiB에서 4K 둘이 함께 통과해 다 차면 여유가 바닥남 — `test_available_check_subtracts_other_captures_reservation`). 앞 캡처가 이미 다 찬 뒤면 그 몫이 두 번 빠져 링 쪽으로 기움(안전한 쪽).
    장부 `_LEDGER`(모듈에 하나 — A/B 둘이 같은 예산을 나눔, 프로세스(창)마다 하나 — 아래 '알고 둔 한계' ⑪)는 전체로 들어갈 때 더하고 `release`·죽음·GC(캡처 단위
    `weakref.finalize` — 재시작마다 바뀌는 세션 finalizer와 따로, 한 번만 돎)에서 뺌. 이 Mac(RAM 128GiB)은 예산 25.6GiB(기록에는 십진으로 27.5GB)라 4K A/B 둘 다 전체(B는 사용 가능 메모리가 18.8GB 이상일 때 — ②), 64GB PC는 4K A/B면 A만 전체·B는 링(4K 하나는 전체), 32GB PC는 4K 링·1080p 전체.
    **기록 한 줄**(판정했을 때만 — opt-in 안 함·킬 스위치는 기록 없음, 값은 `gb`의 십진 GB): `[파이프] 프레임 캐시: 전체 334장 8.3GB (예산 27.5GB, 사용 중 8.3GB) — <파일>` /
    `… 링 8장 — 파일 8.3GB > 남은 예산 6.9GB (물리 RAM 34.4GB의 20% = 6.9GB, 다른 캡처 0.0GB) — <파일>` / `… 링 8장 — 사용 가능 메모리 16.1GB − 다른 캡처 8.3GB < 8.3GB + 2.1GB — <파일>`(여유 2GiB가 십진으로 2.1GB).
    **토글 `YESONCHECK_FRAME_CACHE=auto|ring`**: 없거나 비면 `auto`, 대소문자 무시, 그 밖은 ValueError — `app.launch`가 시작 때 `frame_cache_mode()`로 검증(스플래시 전). `ring`은 킬 스위치(늘 링 8장 — 1.5.1 동작, 단 뒤로 재시작은 목표 8장 앞에 착지).
    **시험의 기본은 `ring`**: `tests/conftest.py`가 다른 토글처럼 지우지 않고 `ring`으로 고정 — 기존 탐색·플레이어 시험이 링 8장의 재시작 지점을 단언하므로(그 무수정 통과가 '링 모드 = 1.5.1'의 증거 — 뒤로 재시작 미리 채우기 뒤에도 무수정 통과: 재시작이 일어나는 지점은 같고 착지 뒤 링에 목표 앞 장들이 더 있을 뿐) 전체 모드 시험은 `auto`를 명시.
    판정이 실패하면(psutil 오류 등) read 예외가 아니라 도중 실패(B)와 같은 죽음 — 아래 '실패 처리'. 그 사유 끝에는 탈출구 안내 `탈출구: YESONCHECK_FRAME_CACHE=ring (psutil을 부르지 않음)`(`FRAME_CACHE_ESCAPE_HINT`)가 붙어 기록과 오류 창에 함께 실림.
  - **프레임 정확도(데이터 계약)**: 주석 JSON의 프레임 번호는 NAS에서 cv2 기반 옛 버전 PC와 함께 쓰고 OCR·씬 워커도 cv2라 "파이프 번호 = cv2 번호"가 깨지면 다른 PC·기능의 주석·구간이 어긋남. 위치는 자체 카운터(순차 전달이라 구조상 정확),
    전체 수는 ffprobe `nb_frames`(cv2 `FRAME_COUNT`와 같은 출처 — 실파일 334 일치), `get(FPS)`는 `float(avg)`(cv2와 같은 출처), 탐색 시각은 정확한 분수 r(병합용 `pick_frame_rate`의 표준값 스냅을 쓰면 2분대부터 반 프레임 어긋남).
    EOF 불변식: 정상 끝은 스트림 위치 == nb_frames에서의 EOF뿐 — 모자라거나 넘치면 도중 실패. 단 끝까지 재생해야 걸리므로 중간 어긋남의 실질 방어는 게이트와 시험.
  - **실패 처리(B 방식 — 사용자 확정)**: `PipeCaptureError`(원인·파일·명령·stderr 전문)는 **열 때만** 올라옴 — 생성자, 그리고 `pipe` 모드에서 게이트 불통과·ffprobe 실패일 때 `maybe_pipe_capture`가 직접 올림. 받는 곳은 `_open_movie_capture`의
    새 분기(오류 창)이고 `open_any_capture` 쪽은 위 '진입점'대로. 생성 뒤의 `read`·`get`·`set`은 예외를 내지 않음 — 도중 실패(프로세스 사망·프레임 중간에서 끊김·
    종료 코드 ≠ 0·EOF 수 불일치·`READ_TIMEOUT_S`=30초 동안 프레임 없음·재시작할 ffmpeg를 띄우지 못함·첫 read에서 프레임 캐시 예산을 정하지 못함 — 이것은 그 read에서 바로)는 큐에 남은 정상 프레임을 다 준 뒤 캡처가 스스로 '죽음' 상태가 되고(죽은 cv2 캡처와 같은 겉모습: `read` `(False, None)`·`isOpened` False·`get` 0.0·`set` False)
    기록(stderr)에 **즉시 1회**(원인·읽던 곳의 호출 스택·명령·stderr 전문) + **Qt 루프에서 오류 창 1회**(`error_window.show_window` — 큐드 연결이라 재생 타이머 슬롯 안에서 모달을 열지 않음; QApplication이 없으면 기록만). 재생은 영상 끝에 닿은 것처럼 멈추고
    다시 열면 정상. 죽음 전이에서 보관본을 비우고 예산 장부를 돌려줌. 사유 글(트레이스백)을 만들다 또 실패하면 고정 사유 + 원래 예외 한 줄(`_fallback_reason`)로 같은 길. **왜 호출처가 아니라 캡처 안에서 끝내나**: 기존 호출처 10여 곳이 read 예외를 삼키거나 print만 하고(매일 쓰는 h264 재생도 지나는 길이라 손대면 회귀 위험), 재생 타이머 슬롯 `next_frame_playback`은 try가 없어
    예외가 올라오면 소스 실행의 PyQt5가 프로세스를 abort함(exit 134 실측). `read()`는 한 번에 한 스레드만 부름(같은 캡처를 두 스레드가 동시에 read하는 건 미지원), `get`·`set`·`release`는 다른 스레드에서 불러도 됨.
  - **픽셀 동일성(스파이크 실측 2026-10-29, CI 세 플랫폼)**: 프레임 정렬(수·순서)은 전 플랫폼·전 클립 완벽. 바이트는 **4:4:4(4444·알파)가 세 플랫폼에서 cv2와 완전 동일**(실파일은 여기), **4:2:2는 Apple Silicon에서만 cv2 대비 ±4 레벨 이내**
    (단색 ±2, 색 경계 ±4 — chroma 보간의 CPU별 swscale 경로 차, 눈으로 구분 불가). 사용자 결정(2026-10-29): 4:2:2도 파이프에 포함 — 시험 기준은 4:4:4 = 바이트 완전 동일, 4:2:2 = 프레임 정렬 완벽 + 최대 차이 ≤ 5
    (`tests/prores_clips.py`의 `BYTE_EXACT`·`TOLERANCE_422`). 앱 의미: Apple Silicon에서 ProRes 422의 표시 색(주석 굽기 내보내기도)이 이전과 최대 4 레벨 다를 수 있음, 프레임 번호는 불변 (2026-11-04부터 Mac 재생 화면은 네이티브라 이 차이는 Mac에서 ffmpeg 방식으로 연 창·내보내기에만). bitexact 플래그는 cv2와 달라질 수 있어 안 씀(cv2 동일성 우선).
  - **시험 클립 함정**: CI Mac 러너의 cv2 디코드가 밝기를 레벨 ±2 틀어 버려(프레임 번호를 밝기 한 값에 그대로 실은 처음 방식이 깨짐) 번호를 회색 블록 두 개의 두 자리 수(`RADIX` 14·`STEP` 18 — ±8 레벨까지 견고)로 실음 — `tests/prores_clips.py`의 `frame_number`.
    정답은 늘 프레임에 그려 넣은 번호이고 cv2 픽셀에 기대지 않음(플랫폼 픽셀 차와 탐색 버그를 가르려고).
  - **알고 둔 한계**: ① 모든 영상 열기에 ffprobe 1회(~45ms, GUI 스레드·timeout 없음 — NAS가 멈추면 기존 `os.stat`과 같은 성질) ② 소스 실행에서 PATH에 ffmpeg·ffprobe가 없으면 h264 열기도 `ToolNotFoundError`(빌드 앱은 번들이라 해당 없음; `YESONCHECK_MOVIE_SOURCE=cv2`면 probe를 안 하므로 피함)
    ③ 파이프가 죽은 뒤 Play를 누르면 `get(FPS)`가 0이라 영상 타이머는 안 켜지지만 단추는 Pause로 바뀌고 소리 재생기는 시작함(오류 창은 이미 떴음 — 다시 열면 정상) ④ (2026-11-02 해소) 죽은 캡처도 죽음 전이에서 보관본을 비우고 예산 장부를 돌려줌 — 예전에는 `release` 전까지 링 버퍼(4K ≈199MB)를 쥐었음
    ⑤ 1GbE 링크 PC는 4K ProRes 첫 재생이 네트워크 대역 한계(131MB/s 필요 — 이 Mac은 10GbE 실측이라 해당 없음, 2회째부터는 캐시) ⑥ 같은 캡처를 두 스레드가 동시에 read하는 건 미지원(계약)
    ⑦ **4K 재생 속도 — 이 Mac(GL 뷰포트 + GL 텍스처 스트리밍, 2026-11-02)에서 334장 13.60·13.67·13.80·14.00·14.54초(마지막 프레임을 넘긴 때 `last` 기준 — 끝난 때 `end` 기준으로 14.0초 이내는 5회 중 3회; 같은 때 번갈아 잰 예전 QPixmap 경로 17.57~18.13초 → 0.78배) — 24fps(13.9초, 타이머 바닥 333틱 × 41ms = 13.65초) 경계. 전부 ML 배치 부하 아래(load1 4.9~18.9 — idle 창이 없었음)라 idle 재측정이 머지 전 필수(내부 눈 확인 ①)**. 사용자 기준(4K 실시간 재생)으로는 이 334장 시간이 직접 지표.
    재생 중 프레임 간격 중앙값 39.6~40.1ms(= 타이머 41ms), GUI 스레드 장당 38~42ms(QPixmap 경로는 53~55ms로 포화). 하니스 틱(`profile_4k_playback.py` YC_PAINT=1)은 53.3·61.1·56.2ms(QPixmap 71.9·88.0·79.0ms, 0.69~0.74배)로 **설계 게이트 ≤ 35ms를 부하 아래 3회 모두 넘음 — idle은 미측정이고 idle에서도 넘을 수 있음**:
    가장 낮은 부하(load 5.1)의 QPixmap 71.9ms가 31차 조건(load 5.7, 72.2ms)과 같은데 그때 GL이 53.3ms였음.
    분해(부하 아래): 업로드(`glTexSubImage2D`) 자체는 5~7ms(스파이크와 같음)이고, 스파이크 투영(29~37ms)보다 ~20ms 무거운 몫은 함께 도는 4K 디코드(ffmpeg 8스레드 + 읽기 스레드 recv 25MB/장 — CPU·메모리 대역 경쟁, +7~12ms)와 틱마다 라벨·슬라이더·오버레이 갱신이 부르는 창 합성(+~7ms) — **둘 다 idle에서도 남음**.
    `paint+events`에는 FBO 합성·swap(vsync) 대기가 섞여 있어 CPU 여유로 읽으면 안 됨. 틱 단축 후속 후보: BGRA 4바이트 업로드(스파이크 −8ms)·ffmpeg 디코드 스레드 수 제한 실험·틱마다의 라벨·슬라이더 갱신 비용 측정.
    (31차 QPixmap 경로의 병목이던 4K `QPixmap` GL paint 48ms/프레임이 이번에 없앤 것 — 그때 334장 16.57초, load 5.7.) **Windows 4K ≈22fps**(스튜디오 PC, 1.6.1 기본 raster — 334장 한 바퀴 15.37·14.93·15.19초, 사용자 스톱워치 2026-11-03): 이 Mac에서 raster로 잰 paint 107ms(≈9.3fps)를 Windows로 옮긴 '느릴 것' 추정은 과했고, 눈으로 "잘 됨"이라던 판단도 실측은 22였음(`YESONCHECK_VIEWPORT=gl`은 미확인). **M1 Mac mini(2020·16GB·10GbE, Apple Silicon 빌드, GL 뷰포트) 4K 4444 ≈18fps**(18.34·18.24·18.66초; 1080p는 24): ffmpeg 단독 디코드 34fps(bgr24)·37(변환 없음·VideoToolbox) — ProRes 엔진이 없어 디코드만으로 CPU 2/3. **BGRX 스파이크(2026-11-03 — 파이프 bgr0 + 플레이어 4채널 + GL BGRA/8_8_8_8_REV + raster RGB32, GUI 스레드 색 변환 0회)로도 M1 18.4초·Windows 15.1초 그대로 → GUI 스레드의 변환·업로드는 M1·Windows의 병목이 아니고 기계 전체 CPU 총량(디코드 + 소켓 전송·복사 + GUI + 합성)이 한계. 접음.** (2026-11-05 정정: Windows 15.1초는 CPU가 아니라 타이머 46.875ms에 막힌 값 — 처리를 줄여도 그대로였던 까닭. M1은 타이머로 설명되지 않음) 내부 저장소 `specs/2026-11-03-bgrx-frame-path-design.md`·`records/2026-11-03-bgrx-frame-path/spike.md`(남는 지식: RGB32 QImage는 QPixmap이 버퍼를 공유하므로 배열 수명을 붙잡아야 함, ffmpeg bgr0의 X=255, GL BGRA/REV+RGBA8 픽셀 동일). M1에서 24fps는 Mac 전용 네이티브 경로(VideoToolbox → IOSurface → GPU)·422 HQ 파일·프레임 건너뛰기 중에서 — 새 설계 항목.
    1080p ProRes는 실시간. 근거: 내부 저장소 `docs/superpowers/records/2026-11-02-gl-stream-design/task4-gate.md`.
    **Mac(2026-11-04)**: HDR이 아닌 ProRes는 Intel·Apple Silicon 모두 이 파이프 대신 네이티브 경로(위 'Mac 네이티브 재생')로 감(처음 PR은 Apple Silicon 4K 4:4:4만) — M1 기본형 스파이크 빌드 334장 창 13.93초·전체화면 14.13초(1.6.1 파이프 18.2~18.7초), 와이프 23.06초(14.4fps — 디코드 한계, 된 만큼). 이 파이프에 남는 것: Windows, Mac에서 Settings → 재생 디코더 (Mac)로 ffmpeg를 고른 창(또는 `YESONCHECK_MAC_NATIVE=off`·네이티브 그리기 실패 폴백 뒤), HDR·게이트 밖 ProRes.
    ⑧ 새 파일을 열면 옛 캡처를 놓기 직전 `stop_video` → `seek_to_frame(1)`이 옛 캡처에서 돎 — 링 모드면 ffmpeg를 한 번 더 띄움(~0.5초, cv2는 ~0.33초 — 뒤로 재시작이지만 목표가 0이라 미리 채울 장이 없어 그대로), 전체 모드면 채움이 끝난 뒤엔 0번이 전체 저장소에 있어 재시작 없음(채우기 전이면 링 모드와 같음)
    ⑨ 4K 슬라이더 드래그는 보관본·앞 24장 밖으로 뛰는 미리보기 장마다 재시작(449~634ms)이라 cv2(329~372ms)보다 무거움 — 전체 모드에서 채움이 끝난 뒤에는 파일 어디든 보관본 복사(~3ms)라 즉시, 채우기 전(멈춘 뒤 0.3초부터 4K 약 7초)·링 모드는 그대로(드래그 중에는 read가 촘촘해 채움기도 쉼).
    뒤로 끄는 미리보기 장이 보관본 밖이면 그 재시작에 미리 채우기 8장(≈0.16초)이 더해짐 — 대신 그 뒤 8장 안의 작은 뒤로 이동은 보관본에서 즉시. 앞으로 끄는 쪽은 미리 채우지 않아 그대로
    ⑩ Windows에서 보안 소프트웨어가 127.0.0.1 루프백 TCP를 막으면 ProRes 열기가 실패함(오류 창 끝 줄에 킬 스위치 안내) — 탈출구는 `YESONCHECK_MOVIE_SOURCE=cv2`(Windows 설정법은 README).
    ⑪ 전체 프레임 캐시: 예산은 첫 read에서 한 번만 봄 — 그 뒤 다른 프로세스(ML 배치 등)가 메모리를 먹어도 보관은 판정한 크기(파일 전체)까지 쉬는 동안 채움기가 계속 채움(되돌리는 길은 파일 닫기·킬 스위치). 채움 ffmpeg는 쉬는 동안 디코드하므로(4K는 8코어를 씀) 멈춰 둔 채 다른 무거운 일을 하면 약 7초 동안 CPU를 나눠 씀(쉬는 때는 이 프로세스의 파이프 read 기준이라 다른 창·다른 앱의 재생은 모름 — 창마다 따로 채움).
    **장부는 프로세스마다 하나이고 창 하나 = 프로세스 하나**(Finder에서 여러 파일을 열면 창이 여럿 — 위 '새 창 · 동영상 열기 · 기본 앱')라 20% 예산은 **창(프로세스)마다**임: 창 셋이 저마다 4K A/B를 열면 각자 20%까지 잡을 수 있고
    서로의 몫을 보지 못함 — 창 사이를 막는 것은 판정 때의 ②(사용 가능 메모리)뿐인데 다른 창이 이미 채운 만큼만 잡히고 아직 채우지 않은 몫은 잡히지 않음(README는 창마다 20%라고 안내). 다음 후보: **채우는 도중의 가드** —
    보관을 늘리기 전에 사용 가능 메모리가 `FULL_CACHE_HEADROOM_BYTES` 아래로 내려가면 그 캡처를 링으로 내려앉힘(위의 '첫 read에서 한 번만 봄'과 창 사이 문제를 함께 누그러뜨림).
    예산 확인(`_LEDGER.committed()`)과 장부 올리기(`add`)가 한 원자 동작이 아님 — 지금은 판정하는 캡처가 플레이어 A/B뿐이고 둘 다 GUI 스레드에서 첫 read를 하므로 겹치지 않지만, 다른 스레드에서 opt-in하는 캡처가 생기면 둘이 함께 통과할 수 있음.
    같은 파일을 A·B로 열면 보관을 따로 둬 둘 다 셈(4K 16.6GB — 채움기도 둘). 플레이어 `frame_cache`(기존 드래그 미리보기 캐시)는 전체 모드에서 중복 메모리(후속 후보). fps는 그대로(4K 병목은 ⑦ — 읽는 동안은 링만이라 첫 재생 속도는 링 모드와 같음)이고 채우기 전의 처음 보는 구간은 예전과 같음(재시작).
  - **다음 후보 — Windows offscreen의 텍스트 주석 굽기**: `render_text_patch`가 글자를 Qt 글꼴로 그리는데 Windows offscreen(CI)에서 글리프가 하나도 안 그려져 구운 그림이 원본과 같았음(글꼴 부재로 추정, 기존 동작 — 이 브랜치와 무관) — 글꼴 가드와 시험이 필요함. 이 브랜치의 `test_display_single_draw`는 도형(사각형) 주석으로 우회.
  - **다음 후보 — 4K 표시 경로의 나머지**: Mac의 직접 GL 텍스처 스트리밍은 2026-11-02에 들어감(`video_widget.py` 항목 — PBO는 스파이크에서 이득이 없어 안 씀). idle 재측정(2026-11-02 12:21, 외부 ML 배치 없음 — 내부 records `task4-gate.md`): 하니스 틱 GL 55.6ms(QPixmap 74.5)·334장 GL 14.02~14.04초(QPixmap 18.4~19.0, GUI 바쁜 시간 40.3ms/장 = 타이머 41ms 포화) — **설계 게이트 ≤ 35ms 미달 확정, 24fps는 경계(여유 없음)**; 머지·후속은 사용자 결정. 남은 것: 틱 단축 — BGRA 4바이트 업로드(스파이크 −8ms, `frame_a` 계약 변경 필요)·ffmpeg 디코드 스레드 수 제한 실험·틱마다의 라벨·슬라이더 갱신 비용 측정, Windows 기본 GL(ES2/데스크톱 공용 셰이더 경로가 선행 조건)·GPU 와이프. `QPixmap` → `QImage` 직접 그리기는 틱이 약 41ms로 예산(41.7ms)에 걸쳐 확실한 실시간이 안 돼 사용자 결정으로 하지 않음. 근거 스크립트
    (`yc_paint_fmt_exp.py`·`yc_sock_exp.py`·`yc_pipe_read_exp.py`·`yc_microbench.py`)와 하니스(`profile_4k_playback.py`)는 내부(비공개) 저장소의 `docs/superpowers/records/2026-10-29-prores-pipe-design/`, GL 스트리밍 스파이크·게이트 스크립트(`yc_gl_stream_spike.py`·`yc_app_playback_time.py`·`yc_app_pixel_check.py`·`diag_tick_split.py`)는 `records/2026-11-02-gl-stream-design/`.
  - 빌드 앱 `yesoncheck/smoke_test.py`의 'ProRes 파이프 열기' 단계(`prores_pipe_open` — 번들 ffmpeg로 소형 ProRes mov를 만들어 `open_any_capture`로 열고 읽기·탐색, `YESONCHECK_MOVIE_SOURCE`가 auto가 아니면 실패): 빌드 앱의
    `_MEIPASS` ffmpeg와 Windows CREATE_NO_WINDOW 파이프가 실제로 실행되는 유일한 자리. 4K 실물 재생·탐색·와이프·주석은 CI가 못 보므로 눈 확인 몫 — 내부(비공개) 저장소의
    `docs/superpowers/records/2026-10-29-prores-pipe-design/eye-check.md`(전체 프레임 캐시는 `docs/superpowers/records/2026-11-02-gl-stream-design/eye-check.md`의 ②). 시험은 아래 '테스트 전략'.
- `yesoncheck/frame_cache_budget.py` (57줄): 파이프 캡처의 전체 프레임 캐시 예산 — 순수 판단 `full_cache_decision(frame_bytes, count, ram_total, ram_available, committed)` → `CacheDecision(full, reason, total_bytes)`(예산 검사가 사용 가능 메모리
  검사보다 먼저, 둘 다 다른 캡처가 잡은 committed를 뺌), 상수 `FULL_CACHE_RAM_FRACTION`(0.20)·`FULL_CACHE_HEADROOM_BYTES`(2GiB), 기록용 `gb`(십진 GB 소수 한 자리), `memory_snapshot`(psutil `virtual_memory()`의 total·available — 예외는 그대로). psutil은 `requirements-build.txt`에
  직접 고정(7.2.2 — lock에는 이미 간접 의존으로 있음). Qt·캡처 상태 없음 — 쓰는 곳은 위 `movie_pipe_source`의 '전체 프레임 캐시'
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
- `yesoncheck/bookmarks.py` (72줄): 북마크 `~/.yeson_bookmarks.json` — 더하기·지우기·고치기(`replace` — old 자리에 new, 그사이 다른 창이 old를 지웠으면 끝에, new가 이미 있으면 old만 지움)마다 파일을 다시 읽어 고침
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
- `yesoncheck/default_app.py` (470줄): Mac 동영상(.mov·.mp4) 기본 앱 — LaunchServices C API를 ctypes로(`LSCopyDefaultRoleHandlerForContentType`·
  `LSSetDefaultRoleHandlerForContentType`(`kLSRolesAll`)·`LSRegisterURL`·`LSCopyApplicationURLsForBundleIdentifier`, PyObjC 없음).
  `set_default`는 정한 뒤 두 종류를 역할 All과 Viewer(더블클릭 — `VERIFIED_ROLES`)로 다시 읽어 확인(OSStatus·다시 읽은 값을 모두 담은
  `DefaultAppError` — 조용한 성공 없음), `other_copies`는 같은 앱 ID의 다른 사본(알리기만, 지우지 않음), `should_ask`(순수 — 같은 두 역할),
  처음 켤 때 한 번 묻기(`asks_on_start`·`ask_at_start` — 다른 창이 열려 있으면 묻지 않음)
  와 Help 메뉴(`set_default_from_menu`), 답은 `prefs.json`에(`record_asked` — 파일 읽기·쓰기는 `mac_prefs`) — 모듈 설명에 확인한 것(2026-10-21, macOS 26.2)과
  몬터레이에서 남은 것
- `yesoncheck/file_associations.py` (194줄): Windows 동영상 연결 프로그램 — `association_entries(exe)`(순수, HKCU의 12개 값: ProgID
  `YesonCheck.Video`·`.mov`/`.mp4`의 `OpenWithProgids`·`Applications\<exe>\SupportedTypes`·`Capabilities`·`RegisteredApplications`),
  `ensure_registered`(읽어서 없거나 다른 것만 쓰고, 쓴 것이 있으면 `SHChangeNotify`), `register_at_start`(빌드 Windows 앱이 켤 때 이 계정에
  등록), `open_default_apps_settings`(Help → "동영상 기본 앱 설정 열기…" — `ms-settings:defaultapps?registeredAppUser=YesonCheck`).
  `winreg`·`shell32`는 쓸 때 불러와 Mac에서도 모듈이 불림 — 설치 파일 `installer/yesoncheck.iss [Registry]`와 같은 내용(BUILD.md 8-2)
- `yesoncheck/error_window.py` (75줄): `default_app`·`file_associations`·`mac_app_events`·`player_base`(GL 뷰포트 폴백)·`gl_video_item`(GL 텍스처 스트리밍 실패)·`sidebar_bookmarks`(관리 창의 가상 함수)가 함께 쓰는 오류 알림 — `report_from_handler(prefix, context)`: PyQt5 가상 함수(eventFilter·done 등)의 except 블록용 — 트레이스백은 바로 기록, 오류 창은 Qt 루프에서, 알리다 또 실패하면 원래 stderr(`_last_resort`) — 예외를 내보내지 않음(`mac_app_events._report_error`와 같은 모양). `show_error(prefix, text)`는 기록(stderr)에
  남기고 `show_window`: 앱의 예외 창(`sys.excepthook.dialog` = `app._ErrorDialog.show_text` — 기록 파일 경로를 붙이고 한 번에 하나만), 없으면(소스 실행)
  `QMessageBox.critical`; `show_unexpected`는 예외 처리 중에 트레이스백째(기록에는 전부, 창에는 `with_details` — 무엇이 실패했는지는 그대로, 트레이스백은 끝
  `DETAILS_LIMIT`(3000) 글자). 잡히지 않은 예외(`_ErrorDialog.show_error`)는 트레이스백만이라 끝 3000자
- `yesoncheck/review_sync.py` (97줄): OCR 검토 창 ↔ 웹 보고서 실시간 동기화 서버(`ReviewSyncServer`) — 창마다 127.0.0.1의 빈 포트와
  무작위 토큰(`ws://127.0.0.1:포트/?token=…`), 토큰이 맞지 않는 연결은 닫고 기록. 보고서는 그 주소(`generate_web_report`의
  `ws_url`)로만 접속하고, 주소가 없으면(듣기 실패) 접속하지 않고 "실시간 동기화 꺼짐"
- `yesoncheck/media_info.py` (227줄): 미디어 정보 창(사이드바 우클릭)의 글 — `external_tools.probe_json`(ffprobe `-show_streams -show_format` 한 번)의 JSON을 `describe`가 (라벨, 값) 줄로:
  코덱은 부르는 이름 + 프로파일 + (codec_name · 태그) + 긴 이름(`Apple ProRes 4444 (prores · ap4h) — Apple ProRes (iCodec Pro)`, `FRIENDLY` 표), 픽셀 형식의 뜻(`pixel_format_text`: `yuv444p12le` → 4:4:4 · 12비트 · 알파 없음 —
  묶음 rgb는 8·16비트 × 채널만 풀고 rgb0은 8비트, rgb555·실수 형식 등 채널 비트가 고르지 않은 것과 모르는 모양은 이름만 — 검토에서 185비트로 보이던 것), 색(공간/원색/전달, 범위 tv·pc), 해상도(화소 비율), 프레임 속도(분수면 `23.976 fps (24000/1001)`, 가변이면 평균), 프레임 수(없으면 '알 수 없음' — MKV·WebM·TS), **길이는 영상 트랙 길이, 없으면 컨테이너**(예전 창은 cv2의 `(n−1)/fps`라 한 프레임만큼 짧았음),
  비트레이트(영상 트랙, 없으면 컨테이너 전체라고 적음), 주사·인코더·만든 때(있을 때만), 음성 트랙(없으면 "없음"), 컨테이너, 파일 크기(십진 GB/MB + 바이트), 경로. 없는 값은 "알 수 없음", 영상 트랙(attached_pic 제외)이 없으면 ValueError.
  창(`player_playback.show_video_info`)은 `format_html`의 HTML(굵은 라벨 — 예전엔 `**`가 글자로 보였음)·'자세히'에 ffprobe JSON·마우스로 골라 복사 가능, 읽지 못하면 기록에 `[미디어 정보] 실패: <경로>` + 트레이스백, 창은 평문(종류·사유·파일, 자세히에 트레이스백, 경고 아이콘) — Qt 없음
- `yesoncheck/windows_display.py` (70줄): (Windows) 화면 그리기 설정 CPU·GPU — 값·`prefs.json` 저장·이 PC의 GL을 쓸 수 있는지(`gl_problem`) — Qt 없음 (최근 변경 사항 2026-11-05)
- `yesoncheck/qt_messages.py` (49줄): Qt(C++) 메시지(qWarning 등)를 `[Qt 경고] …` 한 줄씩 sys.stderr로 — 빌드 앱은 `setup_app_logging`이 건다(2026-11-09). 그 전에는 파이썬 stdout·stderr만 기록 파일로 가서 Qt 경고(소리 백엔드 DirectShow·WMF의 '열지 못함' 등)가 콘솔 없는 Windows 앱에서 사라졌음. 처리기는 Qt 콜백이라 예외를 내지 않음(쓰다 실패하면 원래 stderr에 한 번)
- `yesoncheck/media_player_log.py` (124줄): 소리 재생기(QMediaPlayer) 진단 기록 — `player_base.mediaPlayer`가 만들 때 `attach`: 한 줄 `[소리] 출력 장치: 기본 <장치> · 모두 n개 [...] · 재생기 <쓸 수 있음…> · 재생 가능성 mov <…> · mp4 <…> · QT_MULTIMEDIA_PREFERRED_PLUGINS=<값>`(Windows는 끝에 ` · 백엔드 DirectShow(dsengine.dll)|Media Foundation(wmfengine.dll) · 플러그인 [...]` — `windows_backends`가 GetModuleHandleW로 실제로 불러온 백엔드 DLL을 봄: K-Lite가 깔린 PC는 환경 변수가 안 먹어도 DirectShow로 소리가 나므로 소리만으로는 가를 수 없음; 알아내지 못하면 트레이스백 + '알 수 없음', 재생기는 그대로), 그 뒤 파일마다 `[소리] 상태: <여는 중·열림·열 수 없음…> — <파일>`·`[소리] 소리 트랙: 있음|없음`·`[소리] 재생기 오류: <종류>: <errorString>`(2026-11-09 — Windows 11에서 소리가 안 난다는 보고, 그때까지 재생기 오류·상태를 아무도 받지 않았음). 신호는 재생기의 자식 QObject가 받음(순환 참조 없음)
- `yesoncheck/frame_utils.py` (21줄): 영화 산업 표준 프레임 계산 (feet.frames 형식)
- `yesoncheck/playback_clock.py` (35줄): 재생 틱의 시각표 `PlaybackClock` — k번째 틱 = 시작 + k/fps, 틱마다 다음 시각까지 남은 ms(최소 1)를 돌려줌, 프레임 `BEHIND_LIMIT_FRAMES`(2)장 넘게 밀리면 시각표를 지금으로 옮김(밀린 프레임을 몰아 보이지 않게). 프레임을 건너뛰게 하지 않음 — Qt 없음. `play_video`가 Play마다 만들고 `next_frame_playback`이 틱 끝에 `self.timer.start(…)`로 걺
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
- 관리 창(`BookmarkDialog` — Bookmarks 단추·P 키/ㅔ)의 경로는 DJV처럼 그 자리에서 고침: 항목은 `ItemIsEditable`(고치기 전 경로는 `Qt.UserRole`), 편집 트리거는
  **`SelectedClicked`뿐**(고른 항목 다시 클릭; 우클릭 → 경로 수정도 `editItem`). `EditKeyPressed`는 켜지 않음(Mac에서 Enter가 편집기를 열어 '목록에서 Enter = 폴더 열기'
  습관이 깨짐 — Enter는 예전처럼 창의 기본 단추 '폴더 열기'), `DoubleClicked`도 끔(더블클릭 = 폴더 열기). Qt는 SelectedClicked 편집을 더블클릭 간격만큼 미뤘다가 더블클릭이
  오면 취소하는데 그 취소가 `doubleClicked` 신호 **뒤**라, 더블클릭 열기는 `QTimer.singleShot(0)`로 미룸(열기의 0.5초 대기 중 편집 타이머가 터져 닫히는 창에 편집기가 열리지 않게).
  편집기 commit → `itemChanged` → `_bookmark_item_edited`: 친 글을 `typed_path`(공백·`~`·끝 구분자 정리)로 → 파일을 다시 읽고(`_refresh_bookmarks`) `bookmarks.replace`로
  **바로 저장**(자리 유지·다른 창의 것 보존) → '폴더 열기'·다음에 열 때 고친 경로. 빈 글은 되돌림, 이미 있는 경로(`_same_folder` — 끝 구분자만 다른 것도)는 알림 + 되돌림,
  읽기·쓰기 실패는 기록 + 창 + 되돌림(파일은 덮지 않음), 지금 없는 폴더는 저장하고 경고. 되돌리기·정리는 `_set_bookmark_item`(blockSignals — itemChanged 재진입 없음).
  **편집기 포커스 규칙 `_BookmarkPathDelegate`**: `FocusOut`의 사유가 `ActiveWindowFocusReason`·`PopupFocusReason`이면 commit하지 않음 — Qt 기본 델리게이트는 앱이
  비활성(Cmd+Tab → Finder에서 경로 복사)되기만 해도 반쯤 친 글을 commit해 파일에 써 버림(검토에서 재현). 창 안의 다른 곳 클릭·Enter는 저장, Esc는 취소(Qt 기본).
  **편집기가 열린 채 단추·메뉴·창 닫기**: `commit_bookmark_edit`가 먼저 commit하고 받아들여졌는지 돌려줌(`indexWidget`으로 열린 편집기를 찾아 보호 메서드
  `commitData`·`closeEditor` — Python에서 만든 QListWidget이라 부를 수 있음; Mac은 QPushButton이 클릭으로 포커스를 가져가지 않아 편집기가 저절로 닫히지 않음).
  거부된 편집(이미 있는 경로·경로 형식·파일 실패)이면 '폴더 열기'·'삭제'·우클릭 메뉴는 옛 경로로 가지 않고 멈춤; 글을 고치지 않은 편집기(느린 더블클릭)는 끝에 구분자가 붙어
  저장된 경로(끌어다 놓은 폴더)처럼 정리한 글이 저장된 글과 달라도 거부가 아님(편집기 글 == 항목 글이면 받아들임 — 2차 검토에서 잡은 '첫 클릭 무시'). 읽기 전에
  `QApplication.inputMethod().commit()`(한글 조합 중인 글자 — Mac 실기 확인 몫). **단추 셋은 `Qt.TabFocus`**(Mac 기본과 같게): 포커스를 가져가는 스타일(Windows·Fusion)에서는
  누르는 순간 FocusOut commit이 먼저 돌아(거부 → 편집기 없음) clicked가 옛 경로를 열었음. 창 닫기(닫기 단추 → `reject`, X, Esc)는 `BookmarkDialog.done`이 commit 뒤 닫고,
  다른 창의 업데이트가 닫을 때(`close_for_update` → 창의 `_closing_for_update`)는 반쪽 글을 저장하거나 모달을 띄우지 않고 편집을 버림(`revert_bookmark_edit` —
  모달에 막힌 창은 닫히지 않아 업데이트가 90초 뒤 멈춤). `typed_path`는 감싼 따옴표(Windows '경로로 복사')도 벗기고, 처음부터 적지 않은 경로(`os.path.isabs` 아님)는 알림 + 되돌림.
  가상 함수(`eventFilter`·`done`) **본문**의 예외는 `_report_unexpected` → `error_window.report_from_handler`(기록 + Qt 루프에서 오류 창, 알리다 실패해도 내보내지 않음 — qFatal 회피);
  `itemChanged` 슬롯(`_bookmark_item_edited`)의 예외는 다른 슬롯처럼 `sys.excepthook`(빌드 앱은 예외 창, 소스 실행은 abort)이지 이 가드가 아님.
  우클릭 메뉴 `bookmark_context_menu`(경로 복사·경로 수정·폴더 열기·삭제)는 QMenu를 돌려주고 `_show_bookmark_context_menu`가 띄운 뒤 `deleteLater`(시험은 항목을 바로 trigger).

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
- QGraphicsView를 사용한 비디오 프레임 렌더링 — Mac(cocoa)은 GL 뷰포트 기본(풀스크린 FPS)이고 그때 영상 아이템은 프레임을 GL 텍스처로 직접 올리는 `VideoFrameItem`(4K 재생 — 위 '주요 파일' 참고). Mac 네이티브 프레임(ProRes)은 IOSurface를 텍스처로 묶고(`set_sides` — 와이프는 GL scissor) B 키 글자·주석은 프레임 위 아이템으로
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
- ProRes류 CFR mov는 ffmpeg 파이프 프레임 소스(`movie_pipe_source`)로 재생 — 4K ProRes 4444의 디코드는 cv2 22fps → 파이프 50.7fps이고, 앱 안의 4K 재생은 이 Mac에서 아래 GL 텍스처 스트리밍과 함께 334장 13.60~14.54초 — 24fps(13.9초) 경계(배치 부하 아래 실측; idle 재측정 14.02~14.04초로 경계 확정, 하니스 틱 55.6ms는 설계 게이트 35ms 미달; 예전 QPixmap 경로 17.6~19.0초), 1080p는 실시간, Windows(raster) 4K ≈22fps·M1 Mac mini ≈18fps(2026-11-03 스톱워치 실측 — '알고 둔 한계' ⑦)
  (위 '주요 파일'의 해당 항목: 게이트·토글·전송·실패 처리·알고 둔 한계)
- 플레이어가 연 ProRes A/B는 파일의 모든 프레임을 메모리에 둠(전체 프레임 캐시 — 4K 13.9초 334장 ≈8.3GB, 예산은 창(프로세스)마다 물리 RAM의 20%를 A/B가 나눔 + 다른 캡처 몫을 뺀 사용 가능 메모리에 여유 2GiB):
  읽는 동안은 링 8장만 두고(첫 재생 속도 보존), 멈춘 뒤 0.3초부터 따로 띄운 ffmpeg가 쉬는 동안 채움(4K 약 7초) — 그 뒤 되감기·←·슬라이더·반복 재생이 ffmpeg 재시작(~0.5초) 없이 즉시, fps는 그대로. 예산이 모자라면 링 8장(기록 한 줄), 킬 스위치 `YESONCHECK_FRAME_CACHE=ring`
- Mac GL 뷰포트는 프레임을 GL 텍스처로 직접 올림(`VideoFrameItem` — `QPixmap.fromImage`와 Qt 내부 텍스처 변환 ~48ms/4K 프레임을 건너뜀; 킬 스위치 `YESONCHECK_VIDEO_ITEM=pixmap`, 위 '주요 파일'의 `video_widget.py` 항목)
- Mac(Intel·Apple Silicon)의 ProRes(HDR 제외)는 VideoToolbox가 IOSurface로 디코드하고 GL이 그 표면을 텍스처로 묶어 그림(복사·변환·업로드 0 — M1 기본형 4K 334장 13.9~14.1초, 와이프는 된 만큼 14.4fps; Intel 이 Mac 1080p·4K 단일·Play Selected·4K 와이프 25fps(타이머 상한)); 예비 전환 Settings → 재생 디코더 (Mac)(이 Mac의 prefs.json — 바로 적용), 진단 `YESONCHECK_MAC_NATIVE=off`(`auto`·`on`·`off`, 위 '주요 파일'의 'Mac 네이티브 재생')

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

`tests/`에 시험 파일 118개 (수집 2,958개 — `pytest --collect-only -q tests`). `python -m pytest tests -q`로 돌리며(약 20분), 이 Mac의 소스 실행(`p310_tf` — Mac lock대로 PyObjC 포함)에서 2,912개가 통과(전체 실행에서 아래 플레이크 둘이 실패할 수 있음 — 따로 돌려 확인)하고 46개는 건너뜀 —
다른 OS 전용 시험, CI의 설치 파일 단계에서만 도는 시험이 건너뜀. PyObjC가 있어야 도는 네이티브 시험(`test_mac_native_source` 모듈과 진짜 네이티브 디코드 하나)은 Mac lock을 설치한 환경(이 Mac의 `p310_tf`·두 Mac CI job)에서 돌고 Windows CI에서만 건너뜀 (2026-11-09 기준; 부하 시험 `test_movie_pipe_transport::test_reader_keeps_up_while_main_thread_holds_gil`은 이 Mac이 바쁠 때 실패할 수 있음 — 따로 돌리면 통과; `test_fast_startup`의 종료 플레이크 1건(`test_app_exits_cleanly_while_shared_config_load_runs`, 자식 종료 코드 −11)은 러너 상태에 따라 간헐 실패 — main에서도 같은 빈도, 따로 돌리면 통과). Qt는 화면 없이(`QT_QPA_PLATFORM=offscreen`), ffmpeg는 저장소의
정적 빌드(`vendor/ffmpeg/`)를 씀 (`tests/conftest.py`). 시험을 건너뛰거나 지워서 통과시키지 말 것.

시험 구성 (파일 이름 기준):
- **업데이트**: `test_updates`·`test_update_install`·`test_update_flow`·`test_update_ui`·`test_update_helper_mac`·`test_update_helper_windows`·`test_update_e2e`
- **새 창·기본 앱·창 사이 연결**: `test_new_window`·`test_mac_app_events`·`test_default_app`·`test_file_associations`·`test_launch_args`·`test_instances`·
  `test_instance_link`·`test_error_window`·`test_app_logging`
- **경로·공유 설정·작품**: `test_paths`·`test_paths_windows`·`test_mac_mounts`·`test_shared_config`·`test_path_map_setup`·`test_path_map_setup_dialog`·
  `test_path_map_auto_ui`·`test_stored_paths`·`test_work_paths_ui`·`test_work_season_job`
- **사이드바·썸네일·북마크**: `test_sidebar_refresh`·`test_video_list`·`test_thumbnails`·`test_bookmarks`·`test_sidebar_all_tab`·`test_sidebar_counts`(개수 줄 — 글 규칙, 탭을 따름, 목록 변화·비우기, All 목록 다시 만들기 전에도 원본에서 셈)·`test_open_with`(명령 — QuickTime 앱 ID·Mac `open -a`·Windows 인자 그대로·명령 줄 한도, 등록한 앱 목록 — 다른 키 보존·다른 창이 더한 앱 보존·나쁜 값은 덮지 않고 UserFileError·앱 아닌 것 거부, Mac `open` 실패·멈춤, Windows 앱 폴더 cwd·빌드 앱의 환경 정리(`_MEIPASS` 아래 PATH 조각·변수)·DLL 검색 경로를 띄우기 전 값으로 되돌리기(띄우기 실패해도)·풀지 못하면 띄우지 않음·띄운 뒤 되돌리기 실패는 `DllDirectoryRestoreError` — 가짜 popen·DLL 검색 경로, 진짜 kernel32는 Windows에서만)·`test_sidebar_open_with`(메뉴 모양 Mac/Windows·Mov/Seq/All, 넘기는 파일 — 목록 순서·고른 것 밖에서 연 줄·시퀀스 첫 프레임(대소문자를 가리는 NFS의 `.TGA` — `os.stat`을 가리게 바꿔서, 첫 프레임이 없어지면 알림)·All 섞인 선택의 정확한 차례, DLL 되돌리기 실패 창, 등록·취소·없어진 앱·지우기, 띄우기 실패 창·없는 파일·20개 넘으면 물음·깨진 설정 파일 — 진짜 앱은 띄우지 않음)
- **워커·OCR·내보내기**: `test_workers_split`·`test_workers_transnetv2_guard`·`test_ocr_worker_lifetime`·`test_animatic2_availability`·`test_transnetv2_detect`·
  `test_runtime`·`test_export`·`test_unsaved_ocr_flag`·`test_review_sync`
- **창 모양**: `test_stylesheet_freeze`(테마 시트를 해시로 고정)·`test_overlay_text_size`(B 키 오버레이 글자가 프레임 높이에 비례 — 1080p 1.5배·4K 2배 픽셀)·`test_playback_fps_label`(재생 FPS 라벨의 실제 fps — 진행한 프레임 세기·재생 중에만·첫 틱 제외·죽은 캡처·NaN·넉넉한 창에서 다 보임)·`test_scrollbar_style`·`test_slider_click`·`test_window_resize`·`test_high_dpi`·`test_force_focus`·`test_middle_panel_toggle`·`test_gl_viewport`(Mac GL 뷰포트 — 선택 규칙·GL 적용 시 보존 설정·테마 배경)·`test_overlay_slider_sync`(화살표 프레임 이동의 오버레이 슬라이더 동기화·대체 탐색 경로 한 칸 어긋남)·`test_windows_display`(Windows 화면 그리기 메뉴·GL 확인·[측정]의 끊김)·`test_playback_clock`·`test_playback_timer`(재생 속도 — 시각표 계산, 진짜 타이머로 빠르지 않음·모든 프레임 차례로·늦어도 건너뛰지 않음·반복 재생)·`test_drag_release_seek`(긴 영상 멈춤 회귀 — 놓을 때 읽는 장수를 read 수로 고정, 캐시에 맞는 드래그는 read·set 0)
- **ffmpeg 파이프 재생(ProRes)**: 실제 ffprobe·ffmpeg로 클립 공장(`tests/prores_clips.py` — numpy 프레임을 `prores_ks`에 파이프, 글꼴 의존인 drawtext 금지; 번호 클립·유채색 클립·경계 클립 voff·held·neg·rot·audio_first·truncated·vfr_h264)의 클립을 읽음 (mock 없음 — 오류 창 호출만 바꿔치기)
  - `test_pipe_spike`: 플랫폼 가정을 고정하는 스파이크 — 클립 공장 자가 검증, 파이프(`-fps_mode passthrough`) 대 cv2의 프레임 정렬과 바이트 기준(4:4:4 동일·4:2:2 ≤5), `-ss` 착지(K=0·K=2), 재시작 시간(시간은 print만)
  - `test_movie_pipe_gate`: 게이트 ①~⑥ — 좋은 probe의 필드 하나만 바꾼 사본으로 조건별 경계, 경계 클립의 판정, ffprobe의 time_base 분모 0("1/0")은 예외 없이 음성
  - `test_movie_pipe_capture`: 캡처 코어 — 순차 읽기의 cv2 의미(EOF·`get`·`set`)·cv2와 바이트 대조·도중 실패의 자체 완결(예외 없이 죽음 + 기록 1회 + 오류 창 1회 — 기록·원래 stderr 쓰기나 알릴 글 만들기가 실패해도 read는 예외 없음)·`release`/GC 뒤 프로세스 종료
  - `test_movie_pipe_seek`: 지연 set과 이동 경로(그대로·링 버퍼·앞으로 버리기·`-ss` 재시작+트랙 오프셋·뒤로 재시작 미리 채우기 — 목표 8장 앞 착지와 이어지는 ← 7번 재시작 없음·0에서 자름, 앞으로 재시작은 미리 채우지 않음) — 정답은 프레임에 그린 번호, 어느 경로를 탔는지는 시간이 아니라 세션(프로세스) 수·pid·세션 시작 번호로 실증. 링 모드(conftest의 `ring`)로 돌고, 두 장 클립 경계만 전체 모드 갈래도
  - `test_movie_pipe_store`: 보관본 `_FrameStore` 단위 — 링 모드는 최근 N장 FIFO·복사본은 보관 배열과 독립·링은 재시작에서 비우고 전체는 남김·전체는 용량 안에서 내보내지 않음·같은 번호를 다시 넣으면 교체+순서 갱신·비우기 (ffmpeg 없이 작은 배열)
  - `test_movie_pipe_full_cache`: 전체 프레임 캐시 — 판정은 생성자가 아니라 첫 read·한 바퀴 뒤 채움을 기다리면(`wait_fill`) 모든 번호가 재시작 없이·EOF 뒤 되감기·스트림 우선(되감아 재생해도 보관 구간 끝에서 재시작 없음)·채움 전의 전체 모드는 링 모드와 같음(본 구간이어도 링 밖이면 재시작)·채운 뒤엔 본 적 없는 구간도 보관본·opt-in 안 함/`open_any_capture`/킬 스위치는 링이고 기록 없음·기록 한 줄·
    두 번째 캡처가 남은 예산을 넘으면 링·장부 반환(release·죽음·GC)·죽음이 두 저장소를 비움·주 세션 재시작은 링만 비우고 전체 저장소를 지킴·뒤로 재시작 미리 채우기는 전체 모드에서도 링에만·트랙 시작 오프셋(voff) 파일의 전체 모드(채움 전 밖으로는 재시작 한 번, 채운 뒤 어디든 번호 정확)·판정 실패와 사유 글 만들기 실패(판정·탐색 재시작 둘 다)도 read 예외 없이 죽음(B — 판정 실패 사유 끝의 탈출구 안내가 기록·오류 창에)·
    **쉬는 시간 채움기**: 촘촘히 읽는 동안은 채움 세션도 띄우지 않고 멈추면 끝까지 채움(일부러 남긴 시간 기반 시험 하나)·채우는 도중 read가 오면 다음 장부터 멈춤·쉬는 때는 프로세스 전체 기준(A를 read하는 동안 B는 안 채움 — A/B)·채움기는 링을 쓰지 않음(링은 1.5.1 모양)·release/GC/죽음이 채움 세션(프로세스·소켓·스레드)을 끝내고 닫힌 캡처에 넣지 않음·stop 뒤에는 채움 ffmpeg를 띄우지 않음·채움 ffmpeg를 죽이면 기록 한 번·채운 장은 그대로·장부 몫이 채운 만큼으로 줆·캡처는 그대로 읽힘·오류 창 없음·링 모드의 `wait_fill`은 곧바로 참.
    예산은 `memory_snapshot`을 바꿔 고정(이 기계 메모리에 안 흔들림), 채움 전 동작은 쉬는 때 기준을 늘려 채움기를 붙잡고(`hold_fill`), 채우는 도중은 채움기의 `_keep` 앞 문(`fill_gate`)으로 정해진 장에 세우고, 'read 중'은 read 본체를 문에서 멈춘 진짜 `read()`(`read_in_progress`)로 만들어 봄 — 시간 단언 없음
  - `test_frame_cache_budget`: 예산 순수 함수 — 예산 안/밖·다른 캡처 몫이 예산을 줄임·사용 가능 메모리 부족·사용 가능 메모리 검사도 다른 캡처 몫을 뺌·예산 검사가 먼저·`gb` 십진 한 자리·`memory_snapshot`이 psutil 그대로·토글 값과 나쁜 값의 ValueError·`app.launch`의 시작 검증·conftest의 `ring` 고정
  - `test_movie_pipe_transport`: 전송 계층 — 프레임당 recv 1회 남짓(`recv_calls ≤ 프레임 수 + 1 + 2%`)·GIL 시험: 메인 스레드가 GIL을 쥐는 50ms 창과 놓는 50ms 창을 번갈아 읽기 스레드 공급을 재 **busy 창 평균 ≥ 0.5장(GIL을 쥔 동안 10fps — 제품 하한)** 단언과 idle 공급 > 0 안전망, busy/idle 비율은 출력만 (실측 busy 창 평균: 현재 코드 이 Mac 1.95~3.05·Apple Silicon CI 2.45, 옛 stdout 파이프 0.05~0.60 — 창 사이에 받아 둔 장이 섞여 이 하한만으로는 파이프 회귀를 늘 가르지 못하고, 그 회귀는 프레임당 recv 단언이 결정적으로 잡음; 비율은 러너 속도에 따라 0.44~1.06이라 기준으로 맞지 않음)·release가 막힌 recv를 깨움(shutdown+close)·Windows 경로(TCP 리스너의 accept·EOF·정리·접속 실패)를 `sys.platform` 바꿔치기로
  - `test_display_single_draw`: 재생 틱 한 번에 `updateFrame` 정확히 한 번(주석을 구운 마지막 그림)·`redraw=False`에서도 편집 대상·목록·상태 라벨 갱신은 그대로·다른 호출처는 여전히 그림·드래그 + OCR 검토 창 분기는 와이프가 켜져 있을 때만 다시 그림 — 사용자 승인 예외(중복 그리기 제거)의 보증. 주석은 전부 사각형(도형): 텍스트 주석의 굽기(`render_text_patch`)는 Windows offscreen에서 글리프가 비어 쓰지 않음
  - `test_movie_pipe_integration`: `maybe_pipe_capture`의 모드(auto·pipe·cv2)·예외 경계, `open_any_capture`와 `_open_movie_capture`의 삽입 분기, `app.launch`의 모드 검증 — **게이트 음성 파일은 어떤 모드에서도 `FFmpegPipeCapture`를 만들지 않고 `cv2.VideoCapture`가 열림**(만들면 실패하는 센티널로 바꿔 증명 = cv2 경로 무변경 단언)
  - `test_pipe_player`: 실제 `VideoPlayer`(offscreen)에서 열기·화살표/휠·슬라이더·A/B 와이프·주석 내보내기·재생 도중 ffmpeg 사망(앱 생존·오류 창 1회·재오픈)과 끝난 뒤 프로세스·스레드 잔존 없음·전체 프레임 캐시(A가 `full`로 열려 한 바퀴 뒤 멈추면 쉬는 동안 채움기가 다 채우고 — 그 뒤 처음으로·건너뛰기 탐색·링 밖 ←·
    반복 재생이 끝을 넘어 처음으로 돌아가 이어지는 것까지 주 세션 1개 그대로(채움 세션 하나는 따로), 주석 내보내기 워커는 링, 열기 순서 — 새 캡처 열기 → 옛 캡처 놓기 → 첫 read 판정이라 예산 1.5개분에서 A를 바꿔도 새 A가 전체)
  - `test_smoke_pipe_step`: 실행 시험(`smoke_test.py`)의 'ProRes 파이프 열기' 단계 단위 시험 — 성공·게이트가 cv2를 주면 실패·모드가 auto가 아니면 실패 (번들 ffmpeg는 CI의 빌드 앱 smoke가 봄)
- **GL 텍스처 스트리밍(Mac GL 뷰포트)**: CI는 GL을 못 그리므로(offscreen) 규칙·계약·가드를 봄
  - `test_gl_bindings`: `getProcAddress` 묶기 — 함수 이름마다 주소·못 찾은 함수의 이름을 든 실패·ES/core profile 거부·텍스처 한도를 `glGetIntegerv`로 읽음(0이면 거부)·`check_error`·`glOrtho` double
  - `test_gl_video_item`: 토글 값·선택 규칙, raster 아이템은 평범한 픽스맵 아이템(`set_frame` 거부), `set_frame` 검증·자리표시자 크기·비우기·픽스맵 → 배열, paint 가드(GL 엔진 아님·텍스처 한도 초과 → 기록·창 1회, 엔진 없음 → 기록 1줄·창 없음, `_fail` 자체가 예외를 안 냄·`str(exc)` 실패·창 실패는 `_last_resort`), 가짜 GL 함수로 호출 순서(native 진입 오류 확인 포함)·물리 픽셀 뷰포트와 매핑 모서리·소수 dpr(1.5·1.25)의 qRound 반올림·정렬 복원(실패해도)·필터가 `transformationMode`를 따름·컨텍스트가 죽으면 다시 준비·업로드, 위젯 연결(강제 GL·cocoa 기본(확인 통과/실패)·킬 스위치·raster에 `gl` 토글은 ValueError·`app.launch` 검증·`updateFrame` 분기와 해상도 변경·raster `updateFrame`은 여전히 `setPixmap`)
- **Mac 네이티브 재생**: 진짜 VideoToolbox·AVFoundation은 PyObjC가 있는 곳에서만(Mac lock을 설치한 환경 — 이 Mac의 `~/coding/p310_tf`·두 Mac CI job, Intel job 포함) 돌고, 나머지는 PyObjC 없이(가짜 손잡이·가짜 GL/CGL·가짜 캡처) 세 플랫폼 모두에서. **conftest 격리**: `tests/conftest.py`가 `YESONCHECK_MAC_NATIVE=off`를 고정(기존 시험의 작은 ProRes 클립이 Mac에서 네이티브로 열리지 않게 — `YESONCHECK_FRAME_CACHE=ring` 선례; 네이티브를 겨누는 시험만 `on`을 명시하거나 `native_wanted`를 바꿔치기, auto의 뜻을 보는 시험은 `monkeypatch.delenv`)하고, autouse 픽스처 `_isolated_prefs_and_decoder_cache`가 시험마다 HOME·USERPROFILE을 새 빈 폴더로·디코더 캐시를 앞뒤로 기본(videotoolbox)으로 되돌림 (개발자의 진짜 prefs.json·시험 순서에 기대지 않게 — 없으면 ffmpeg를 담은 prefs가 다른 파일의 게이트 시험을 깨고, 깨진 prefs는 모달 경고에서 끝없이 기다림(Task 2 검토에서 60초에 강제 종료)). CI는 GL을 못 그리므로 실제 화면(RECT 묶기·레티나 좌표·글자 모양)은 M1·Intel 눈 확인
  - `test_mac_native_gate`: 토글 값과 나쁜 값·`native_wanted`(auto = darwin이고 캐시가 videotoolbox — Intel Mac 포함, Windows·Linux(ARM 포함)는 아님, `on`은 macOS 밖이면 ValueError, `off`)·우선순위(환경 변수 > prefs > 기본)·`effective_decoder`의 출처 글·`set_preferred_decoder`의 나쁜 값·`app.launch`/`load_playback_decoder`(키 없음·값·깨진 파일·나쁜 값 → 창 1회 + 그 세션 ffmpeg `SOURCE_FALLBACK`, 기록 줄)·conftest의 off 고정·Qt/PyObjC 없이 import, 게이트 ①~⑦·⑨ — 실제 ffprobe로 읽은 공장 클립(4444·알파·4:2:2·태그 없음·1080p)은 통과, HDR(전달 smpte2084·arib-std-b67 — 전달이 원색보다 먼저, 원색 bt2020)·h264·VFR은 사유, 지운 상수(4K·4:4:4·태그)가 없음, 크기·크로마·행렬과 상관없이 HDR만 음성, 사유 글의 조건 번호
  - `test_frame_handles`: 손잡이 전파(슬라이스·reshape는 물려받고 copy·astype·ufunc·축소는 아님)·일반 뷰도 keepalive를 살림·참조 계수만으로 풀림(순환 없음)·읽기 전용 유지·`whole_surface_handle`이 조각·뒤집힌 뷰·다른 strides·행 패딩으로 밀린 같은 배치를 거름
  - `test_mac_native_source`(`importorskip("AVFoundation")` — PyObjC가 없는 환경(Windows CI)은 이유를 출력하고 모듈째 건너뜀): 진짜 AVAssetReader로 공장 320×180 클립 — 번호(그린 번호가 정답)·색(ffmpeg 파이프 bgr24와 ±4 — `prores_clips.pipe_frames`, 유채색 4:4:4·알파)·표면 전체 손잡이·탐색 규칙과 재시작 수(`restart_count`)·←는 8번에 한 번 재시작·재시작 연타·cancel은 읽기 스레드만·번호 빈틈은 죽음·23.976fps 1만 장 번호 정확·EOF 불변식·짧은 파일은 EOF가 아니라 실패·멈춘 리더는 창 1회와 함께 죽음·기록 줄·열기 실패는 `NativeCaptureError`·release/GC 뒤 읽기 스레드 정지·**샘플 버퍼 누수 없음**(메타데이터 등록 확인, 300장 동안 서로 다른 IOSurface ≤ 32, 샘플 참조 수 1)
  - `test_hw_decode_probe`: `hw=` — 가짜 `ctypes.CDLL`로 FourCC → bool 배선(`c_bool`·`c_uint32`·한 번만 엶)·프레임워크/함수 없음 → None + 사유 한 번·예상 못 한 예외는 올림·래퍼 우선·기록 줄 `hw=yes|no|?`·macOS에서는 진짜 프레임워크가 예/아니오
  - `test_gl_surface`: CGL 상수·시그니처·인자 전달·CGLError ≠ 0 → `GLBindingError`(코드·IOSurface·크기)·프레임워크/함수 없음·진짜 프레임워크 열기. `test_gl_video_item`의 'IOSurface 그리기' 묶음: 가짜 GL·CGL에 기록 — RECT 묶기와 그리기·혼합 면(네이티브 + RGB, 양쪽 방향)·둘 다 네이티브·B 없음/크기 다름 → 검정·"xy" 상자 둘·`ratio` 모양 검사·`wipe_scissor` 상자 표·손잡이가 바뀔 때만 다시 묶음·RGB 면은 배열이 바뀔 때만 올림·필터가 `transformationMode`를 따름·컨텍스트가 죽거나 바뀌면 다시 묶음·묶인 동안 표면이 살고 컨텍스트와 함께 놓임·와이프 없으면 B를 쥐지 않음·묶기 실패는 크게 한 번·실패해도 GL 상태 복원·조각 뷰 거부·예전 RGB 길 그대로
  - `test_native_player_paths`(+ 픽스처 `tests/native_fakes.py` — `SpyNativeArray`가 파이썬 쪽 픽셀 접근(인덱싱·ufunc·numpy 함수·tobytes·`.data` …)을 모두 기록, 네이티브 프레임을 받은 `cv2.cvtColor`도 셈, `FakeNativeCapture`, 플레이어 픽스처): 재생 틱·와이프 틱·탐색에서 **파이썬 픽셀 접근 0·cvtColor 0**·`optimize_for_4k` 건너뜀·`frame_cache`에 안 넣음·`set_sides` 인자(축·ratio·혼합 A/B)·픽스맵 길은 `_pixmap_backing`·`[측정]` 줄(네이티브·cv2 캡처, 프레임 수를 크게 알리는 캡처)
  - `test_native_overlay_item`: B 키 아이템 — B를 켤 때만·굽지 않음(프레임 그대로)·`_minimal_preview_seek`에서도 새 번호·RGB 프레임이면 숨김·픽스맵 길에도 보임·A RGB + B 네이티브면 A에 한 번만 구움·기하가 `overlay_metrics`를 따름(상자 왼쪽·위 = 구운 상자, Qt 꼬리까지 상자 안)·프레임 크기에 비례·굵기 → Bold·좁은 프레임에서 줄임·Qt 글자가 넓으면 더 줄임
  - `test_annotation_overlay`: 주석 층 — 종류별 기하가 굽는 길과 같음(장면을 QImage에 그려 같은 주석을 구운 프레임과 대조 — Windows offscreen은 글자 그림 대조를 건너뛰고 기하만)·획 폭 = cv2가 칠하는 폭(굵기 1..최대)·화살표 촉·글자 크기 규칙·빈 글자/모르는 종류는 안 그림·프레임 밖은 잘림·아이템 재사용과 값 갱신·**굽기 결과는 나누기 전과 같음**·네이티브 프레임은 굽지 않고 층 갱신·쌓임(B 글자 위·편집 미리보기 아래)·RGB면 비움·A RGB + B 네이티브면 한 번만 구움·편집하면 픽셀 접근 없이 층이 따라감
  - `test_native_open_path`: 열기 분기 — 양성은 네이티브(파이프를 부르면 실패하는 대역)·`pipe` 모드도 네이티브 우선·`open_file`까지 이어서·`NativeCaptureError`는 트레이스백 + 기록 줄 + 창 1회(끝 줄 탈출구) 뒤 같은 probe로 파이프·PyObjC 없음도 창(크래시 아님)·네이티브 실패 뒤 파이프도 실패하면 창 둘·예상 못 한 예외는 올림·음성은 사유 한 줄 뒤 파이프·`cv2` 모드는 토글도 probe도 안 봄·`native_wanted()` 거짓이면 예전 줄 그대로이고 **새 프로세스에서 `mac_native_source`가 import되지 않음**·네이티브 분기의 ffprobe 실패는 파이프와 같은 규칙·`maybe_pipe_capture(…, probe=)`
  - `test_build_lock`: PyObjC 직접 고정 줄은 모두 `sys_platform == "darwin"` 마커, Mac 두 lock(arm64·x86_64)에 여섯 개가 12.2.2로 고정·Windows lock에는 없음, VideoToolbox 래퍼는 고정하지 않음
  - `test_mac_prefs`(2026-11-04): `prefs_path`가 지금 HOME을 따름·없으면 `{}`·`update_pref`가 파일을 만들고 다른 키를 지킴·깨진 파일은 덮지 않고 `UserFileError`·`default_app`이 `mac_prefs`를 씀
  - `test_decoder_swap`(`tests/native_fakes` 리그로 바꿔 끼움을 객체 동일성으로, 게이트용 ffprobe는 바꿔치기): 같은 프레임·재생 중이면 이어 재생·OCR/주석/소리/줌 상태 보존·옛 디코더의 드래그 캐시 비움·h264·시퀀스는 그대로·열기 실패는 옛 캡처 유지 + False·ffprobe 실패는 창 1회 + 캡처 유지·와이프 B(함께 바꿈, 와이프 꺼진 B의 자리, **A/B 어긋남 보존**, 아직 안 읽은 B, A만 바뀌고 B 실패)·게이트 밖 ProRes(HDR·VFR)는 다시 열지 않음·`cv2` 모드는 아무것도 안 함·바꾼 쪽마다 기록 줄
  - `test_decoder_menu`(Mac 전용 시험은 Windows CI에서 skip — 메뉴 부재는 가짜 플랫폼 시험이 모든 OS에서): GPU 서브메뉴 뒤·라디오·Mac 밖에는 메뉴 없음·시작 체크·환경 변수/`cv2`면 비활성 + 툴팁·읽기 실패 세션은 ffmpeg 체크 + 출처 툴팁·고르면 저장(다른 키 유지) + 기록 + swap → reset 차례·픽스맵 아이템은 reset 없음·바꿔 끼우는 동안의 모달이 걸쇠를 다시 걸지 않음·swap 예외에도 메뉴 동기화·같은 값은 아무것도 안 함·유효 디코더가 그대로면 다시 열지 않음·prefs 쓰기 실패는 창 1회 + 체크 되돌림(캐시·캡처·깨진 파일 그대로)·swap False면 창을 더 띄우지 않음·모르는 이름 ValueError·macOS 밖 RuntimeError
  - `test_native_paint_fallback`(가짜 GL — CGL 컨텍스트 NULL로 진짜 `paint` 안에서 IOSurface 묶기를 실패시킴): 네이티브 면 실패 → paint 안에서는 걸쇠만, Qt 루프에서 캐시 ffmpeg(`SOURCE_GL_FALLBACK`)·prefs.json 안 씀·창 1회(첫 줄 `NATIVE_FALLBACK_LINE`)·기록 줄·swap 한 번(걸쇠가 걸린 채)·다음 paint는 RGB 업로드·RGB 면 실패는 예전 그대로·macOS 밖은 아무것도·메뉴가 실행 중 전환을 비춤(다음 창은 다시 시도)·**네이티브 면이 남으면 걸쇠 유지**(고리 막기)·swap 예외에도 걸쇠 판단·메뉴·환경 변수가 덮으면 바꾸지 않음·멈춘 창에서 ffmpeg를 고르면 다시 바꿔 끼움·다시 누르면 다시 시도·VideoToolbox를 고르면 걸쇠를 풂·콜백은 Qt 루프에서 걸쇠마다 한 번·콜백 예외·예약 실패는 `_last_resort`·위젯이 신호로 다시 냄·플레이어가 그 신호에 한 번 연결
  - `test_prores_clips_factory`: 클립 공장(`tests/prores_clips.py`)의 새 인자(크기·색 태그·알파·합법 범위 유채색)를 실제 ffprobe·cv2·ffmpeg로 다시 읽어 확인. 그리고 `test_movie_pipe_gate`에 probe의 새 필드(색 태그·pix_fmt·codec_tag — 파이프 게이트는 보지 않음), `test_check_frozen_imports`에 네이티브 디코드 확인(macOS가 아니면 건너뜀 — Windows·Linux, Intel Mac도 디코드(`hw=no` 결과 줄)·결과 줄·틀린 프레임 종류마다 실패·게이트 음성·번들 ffmpeg 없음·PyObjC가 있으면 이 기계의 번들 ffmpeg로 진짜 디코드)
- **그 밖**: `test_smoke`·`test_fast_startup`·`test_files`·`test_user_files`·`test_media_info`(ffprobe JSON → 줄, 픽셀 형식 뜻, 실제 ffprobe로 시험 영상, 창의 HTML·자세히·실패 평문)·`test_frame_annotations_merge`·`test_annotation_burn_color`(도형 주석이 고른 색 그대로 — RGB 순서)·`test_annotation_click`·`test_external_tools`·`test_build_info`·
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
10. 북마크 생성 및 탐색 — 관리 창에서 경로를 클릭해 고친 뒤 '폴더 열기'가 고친 폴더를 여는지, 우클릭 경로 복사, P 키
11. 프레임 탐색 및 재생
12. OCR 리뷰 대화상자와 메인 윈도우 간 실시간 동기화
13. 4K ProRes 재생(ffmpeg 파이프) — 캐시 없는 파일의 첫 재생 fps·소리·탐색·와이프·주석·h264 무회귀·킬 스위치: 내부(비공개) 저장소의 `docs/superpowers/records/2026-10-29-prores-pipe-design/eye-check.md`;
    전체 프레임 캐시(한 바퀴 뒤 스크럽·←·반복 재생 즉시·메모리·기록 줄·A/B 4K 둘·킬 스위치 `YESONCHECK_FRAME_CACHE=ring`): 같은 저장소의 `docs/superpowers/records/2026-11-02-gl-stream-design/eye-check.md` ②
14. Mac GL 텍스처 스트리밍 — idle 재측정(334장·틱)·fps 체감·1080p·h264·풀스크린·줌/팬·와이프·ROI·주석·오버레이·테마·킬 스위치 둘·기록 줄: 내부(비공개) 저장소의 `docs/superpowers/records/2026-11-02-gl-stream-design/eye-check.md` ①
15. Apple Silicon 네이티브 재생(M1 필수 — CI는 디코드만 보고 그리기는 못 봄) — 4K 334장 창·전체화면·와이프 시간(기록의 `[측정]` 줄)·←→·휠·슬라이더·되감기·반복·B 키 글자·주석 그리기/편집/내보내기·ROI·색·혼합 A/B(h264)·썸네일·`VTDecoderXPCService` 메모리(누수 재발 없음)·`-11821` 재확인·킬 스위치 `YESONCHECK_MAC_NATIVE=off`·기록 줄 `hw=`·구운 그림과 다른 점(쌓임 순서·와이프에서 안 잘리는 글자/주석·글꼴)을 그대로 둘지: 내부(비공개) 저장소의 `docs/superpowers/records/2026-11-03-mac-native-playback/eye-check.md`
16. Mac 전체 ProRes 네이티브·Settings → 재생 디코더 (Mac)(2026-11-04 — M1 3회차와 **Monterey + RX 580 Intel Mac** 한 대 이상): 1080p 4:2:2 파일 재생·↑↓ 전환·스크럽·Play Selected, 재생 중 메뉴 전환(재생·와이프·주석 유지), 영상 영역이 빈 채·오류 창 없음, 기록 줄 `[재생] 디코더: …`·`[재생] 네이티브(VideoToolbox): … hw=…`·`[표시] GL …`·`[측정]` — 내부(비공개) 저장소의 2026-11-04 눈 확인 기록

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
- **Mac 네이티브 재생 — 알고 둔 한계(2026-11-04)**: ① Mac 재생 색이 1.6.1 이하의 Mac 화면(파이프)과 다름 — 4:2:2 색 가장자리 1픽셀(보간 대 복사)·태그 없는 HD(709 대 601) — 의도된 변화(위 '색'; QuickTime Player 화면과도 다름) ② Intel Mac 와이프(표면 둘 — 외장 GPU의 IOSurface 전송·소프트웨어 VideoToolbox 리더 둘)는 실시간 보장 없음(이 Mac은 4K 둘 다 네이티브 25fps, 다른 GPU·드라이버는 모름 — Monterey + RX 580 확인 대기) ③ 메뉴로 바꾼 디코더는 그 창만 바로 — 이미 열린 다른 창(프로세스)은 다음에 켤 때부터(툴팁에 적음) ④ prefs.json 쓰기 실패면 창 1회 + 체크 되돌림, 재시도는 없음(다시 고르면 다시 시도) ⑤ (GL 실패 창 글) `YESONCHECK_MAC_NATIVE=on` 아래서도 네이티브 면 실패 창의 첫 줄이 '이 창은 ffmpeg 방식으로 바꿉니다'라고 말함 — 아이템은 게이트를 읽지 않고, 실제로는 바꾸지 않으며 기록 줄 `… 디코더를 바꾸지 않음(우선: …)`이 맞음 ⑥ stderr 머리 `[표시] GL 텍스처 스트리밍 실패 — 영상 영역을 비워 둡니다 …`는 폴백 직후 ffmpeg 그림으로 다시 그려도 그 글 그대로(그 뒤 stdout 줄이 바꾼 것을 말함) ⑦ 바꿔 끼우지 못해 네이티브 면에 걸쇠가 남은 창은 메뉴에서 ffmpeg를 다시 고를 때까지 영상 영역이 빔(저절로 풀지 않음 — GL이 전반적으로 깨진 Mac의 창 폭주 방지) ⑧ 진짜 `CGLTexImageIOSurface2D` 실패는 이 Mac에서 만들 수 없어 가짜 GL로만 증명 ⑨ 재생 중 ffmpeg로 바꾸면 GUI가 파이프를 여는 동안 멈춤(4K 1.4초, 와이프 3.4초 — ffprobe·열기가 GUI 스레드) ⑩ (측정 하니스) 앱 창이 화면에 보이지 않으면(화면 잠김에서 확인 — 창이 완전히 가려진 경우도 같을 것으로 추정, 미측정; 터미널에서 띄운 측정 창) macOS App Nap이 약 25~30초 뒤 타이머를 늦춰 재생이 4~7fps로 떨어짐 — 네이티브·파이프 공통이고 main(950ce3d)에서도 같음; 측정 스크립트는 `NSProcessInfo.beginActivityWithOptions`로 끄고 잼(앱에서 막을지는 미결정)

## 파일 구성

### 설정 파일
- 북마크: `~/.yeson_bookmarks.json` (+ 잠금 파일 `~/.yeson_bookmarks.json.lock` — 지우지 않고 둠, `user_files.FileLock`)
- 오버레이 위치·크기: `~/.yeson_overlay_settings.json`, 주석 내보내기 폴더: `~/.yeson_annotation_export.json` (원자적 쓰기)
- 주석: 영상 옆 `.yesoncheck/<이름>_annotations.json` — 지운 항목의 id는 `deleted_ids`에 (위 '여러 창과 업데이트')
- 창 기록: Mac `~/Library/Caches/YesonCheck/instances/<pid>.json`, Windows `%LOCALAPPDATA%\YesonCheck\instances\<pid>.json`
  (`YESONCHECK_INSTANCES_DIR`로 바꿀 수 있음 — 시험용)
- 다른 앱으로 열기에 등록한 앱(2026-11-06): Mac은 같은 `prefs.json`, Windows는 `%LOCALAPPDATA%\YesonCheck\prefs.json`의 `"open_with_apps": [앱 경로, …]`(등록한 차례) — 사이드바 우클릭 → 다른 앱으로 열기 → 앱 등록…·앱 지우기가 `open_with`로 씀. 이 PC에만 — NAS 공유 설정에 넣지 않음(PC마다 앱 위치가 다름). 글자 목록이 아니면 메뉴에 '설정 파일을 읽지 못했습니다'(덮지 않음)
- 재생 디코더(Mac, 2026-11-04): 같은 `prefs.json`의 `"playback_decoder": "videotoolbox" | "ffmpeg"`(없으면 videotoolbox) — Settings → 재생 디코더 (Mac)가 `mac_prefs.update_pref`로 씀, `app.load_playback_decoder`가 켤 때 한 번 읽음(다른 창은 다음 실행부터). 이 Mac에만 — NAS 공유 설정에 넣지 않음. 손으로 나쁜 값을 넣으면 켤 때 창 1회 뒤 그 세션은 ffmpeg
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
  PIL처럼 지연 import하는 모듈은 import만으로는 안 잡히므로 실제로 실행해야 함 — 시퀀스 TGA·EXR 한 장 디코딩(`exercise_sequence_decode`)이 그 예 (`tests/test_check_frozen_imports.py`).
  macOS 빌드마다(`sys.platform == "darwin"` — Intel·Apple Silicon, 칩 무관) 네이티브 재생 경로도 실제로 돌림(`exercise_native_decode`): 번들 ffmpeg(`vendor/ffmpeg/<platform.machine()>` — 없거나 앱 코드가 다른 ffprobe를 고르면 실패, PATH의 다른 ffmpeg로 대신하지 않음)로 임시 폴더에 4K ProRes 4444 bt709 6장(testsrc2) → probe → 네이티브 게이트 → `NativeVTCapture`로 3장(4K BGRX uint8·표면 전체 손잡이·번호 0·1·2·한 색 아님 — `native_frame_problem`) → 결과 줄 `네이티브 디코드: VideoToolbox 3장 3840×2160 32BGRA (hw=…)`(CI Intel job `hw=no`·Apple Silicon job `hw=yes`); Windows는 `네이티브 디코드 건너뜀 (macOS 아님)`(`NATIVE_SKIPPED`). 클립이 4K인 것은 게이트 조건이 아니라 가장 무거운 실사용 디코드(큰 IOSurface)를 확인하려는 것.
  import 모으기(`source_imports`)는 `from yesoncheck import X`의 X도 모듈로 셈 — 함수 안 `from yesoncheck import mac_native_source` 같은 지연 import가 `yesoncheck`만 남겨 Intel·Windows 검사가 그 모듈을 앱과 대조하지 않던 구멍을 막음
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
- **`재생: 24 FPS · 실제 23.8` 라벨**(2026-11-03부터): 앞은 영상의 원래 fps(`cap_a.get(CAP_PROP_FPS)`), 뒤 '실제'는 재생 중일 때만 — `update_playback_fps`(1초 타이머)가 지난 틱 뒤로
  재생 틱 `next_frame_playback`이 **진행한** 프레임 수(`playback_fps_counter` — 그리기를 건너뛰는 OCR 검토 창이나 탐색 그리기와 무관)를 걸린 시간(`time.monotonic`)으로 나눈 값(`playback_fps_measured`;
  재생 중이 아니거나 재생을 시작한 뒤 첫 틱이면 None — 부분 구간). 실제가 원래 fps에 한참 못 미치면 리얼타임이 아님 — 4K 재생 확인은 이 값으로(예전에는 원래 fps만 다시 써서 느려도 24로 보였음).
  1초 표본이라 ±1 정도 흔들림 — 23.x 한 번은 결론이 아님. 더 정확한 측정은 처음부터 끝까지 재생한 시간이나 캡처 `read()` 처리량으로
- **`[측정]` 줄**(2026-11-04부터, Play마다 한 줄 — 모든 캡처): `[측정] 333장 13.88초 (24.0fps) 최대간격 46ms 끊김 0번 네이티브=yes 와이프=off 표시=gl — <파일>` — 처음부터 끝까지 재생한 시간이라 4K 실시간 판정은 이 줄로(라벨의 '실제'는 1초 표본). 어느 열기 경로인지는 `[재생]` 줄: `네이티브(VideoToolbox): …`(Mac의 ProRes — HDR 제외)·`ffmpeg 파이프: …`·`cv2: …`, 네이티브 음성이면 그 앞에 `네이티브(VideoToolbox): 아님 — <사유>: <이름>`. Mac은 켤 때 `[재생] 디코더: <디코더> (<출처>)` 한 줄, 메뉴로 바꾸면 `[재생] 디코더 설정: <이름> (Setting 메뉴)`와 바꾼 쪽마다 `[재생] 디코더 전환: <A|B> 캡처 바꿔 끼움 — <이름> (<번호>번)`, 네이티브 그리기 폴백은 `[표시] GL 텍스처 스트리밍 실패 — 이 창을 ffmpeg 방식으로 바꿉니다`. **선택 재생의 전환**(2026-11-06): 둘째 차례부터 `[측정] 전환 <초>초 (열기 <초>초) — <앞> → <다음>`(`sidebar_playlist.switch_line`) — 앞 차례의 [측정] 줄이 기억한 마지막 틱 시각(`_last_measure_end`, `_print_measurement`가 둠)부터 다음 파일의 `play_video`를 건 직후까지(끝을 아는 틱 하나 + `open_file` + 처음으로 이동 — 실시간이면 1/fps 남짓), 괄호는 그중 `open_file`. 앞 차례를 끝까지 재생하지 않았거나(줄이 없음) 첫 차례면 줄 없음(선택 재생 밖에서 본 영상의 낡은 시각을 쓰지 않음). **영상 열기의 단계별 시간**(2026-11-07): 열 때마다 `[측정] 열기 <총>초 — ffprobe · ffmpeg 시작 · 첫 프레임 · 멈추기 · 옛 캡처 놓기 · 소리 · 첫 화면 · 주석 · 그 밖 — <파일>`(`player_playback.open_timing_line` — 파이프 캡처는 `maybe_pipe_capture`가 ffprobe, `FFmpegPipeCapture`가 ffmpeg 시작·첫 프레임을 `open_steps`에 적어 둠; 그 밖의 캡처는 '캡처 열기' 하나; '멈추기'는 선택 재생이 아니면 `stop_video` → 옛 캡처 처음으로; '첫 화면'은 첫 read(파이프면 프레임 캐시 판정)·그리기; '주석'은 주석 파일 읽기·OCR 상태 비우기). 선택 재생 전환 약 1초 중 '열기'가 무엇에 드는지 재고 '다음 파일 미리 열기'를 설계하려고 넣음
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

### 2026-11-09 (소리 진단 기록 — Windows 11에서 소리가 안 남)
- **보고**(사용자): Windows 11에서 소리가 나오지 않음, Windows 10은 정상. 원인 미확인 — 기록에 아무것도 없었음: 빌드 앱은 Qt(C++) 경고를 기록 파일로 보내지 않았고(소리 백엔드가 실패를 알리는 길), QMediaPlayer의 오류·상태 신호도 받지 않았음
- **넣은 것**(고치기 전에 증거부터): `qt_messages`(Qt 경고 → 기록)·`media_player_log`(출력 장치·재생 가능성·상태·오류 → `[소리]` 줄). 동작은 그대로
- **후보(미확인)**: ① Qt 5의 Windows 기본 소리 백엔드는 DirectShow라 mov를 열려면 따로 설치한 필터(LAV·K-Lite 등)가 필요할 수 있음 — Windows 10 PC에만 있으면 맞음 ② Windows 11의 출력 장치·설정 ③ 볼륨·음소거. Windows 11 기록의 `[Qt 경고]`·`[소리]` 줄로 가림
- 시험 `tests/test_audio_log.py`(Qt 메시지 줄 모양·sys.stderr로·빌드 앱 기록 파일에 남음·쓰기 실패에도 예외 없음, 출력 장치 줄·상태/오류/소리 트랙 줄·창의 재생기에 붙음)

### 2026-11-09 (ffmpeg 파이프 — Windows만 조각 스레드로 첫 프레임 앞당기기)
- **왜**: Windows 시험 빌드(a652652)의 `[측정] 열기` 9번에서 '첫 프레임'(ffmpeg가 첫 4K 프레임을 넘겨주기까지)이 평균 0.74초(0.44~1.33)로 전환 평균 1.10초의 약 70% — ffprobe 0.12·주석 0.09·소리 0.04·첫 화면 0.03은 작음
- **고침**: Windows에서만 `_pipe_command`에 `-thread_type slice`(입력 옵션) — 기본 프레임 스레드는 여러 프레임을 함께 디코드해 첫 장이 늦음. 열기·탐색 재시작·채움기·주석 내보내기가 같은 명령이라 모두 해당. **Mac은 그대로**(사용자 요청 '맥 버전은 그대로 유지 — 1.8.0의 Mac은 아주 좋아'): Mac 재생은 대부분 VideoToolbox이지만 ffmpeg를 고른 창·HDR ProRes·주석 내보내기는 이 파이프를 쓰므로 명령을 플랫폼으로 가름. main(1.8.0)과 견준 Mac의 차이는 열 때마다 남는 `[측정] 열기` 기록 줄뿐
- **실측**(이 Intel Mac, 4K ProRes 4444 334장, OS 캐시에 올린 파일 — 한 프로세스 안에서): 첫 프레임 0.56·0.56·0.56초 → 0.18·0.17·0.16초, 48장 1.73초 → 1.05초, 334장 6.94·6.78초 → 6.40·6.46초(`-threads 1`은 첫 프레임 0.41초·9.3fps라 안 씀). 픽셀: 실파일 334장과 `-ss` 5초 20장의 bgr24 framemd5가 기본과 같음, `test_movie_pipe_capture`의 cv2 바이트 대조 통과
- **Windows 실측**(사용자 PC, GPU 화면 그리기, 같은 4K 10개 선택 재생 — 빌드마다 한 번): 전환 평균 1.10초(0.79~1.64) → **0.61초(0.54~0.76)**, '첫 프레임' 0.74 → 0.23초. 파일 안 '끊김'(틱 간격 > 1.5장분 = 62.5ms)은 31 → 94번으로 늘었지만 **파일마다 가장 긴 간격은 75~98ms**(기본 58~193ms) — 눈에 띄는 멈춤이 없어 사용자 판정 '더 안정적'(아래 미리 열기와 견줌). 끊김 수만으로 판정하지 말 것 — 62.5ms를 조금 넘는 틱도 셈; 사람이 멈춤으로 보는 것은 최대간격·200ms 넘는 틱
- **다음 차례 미리 열기는 해 보고 되돌림**(e6d15d0·9f04479 → 되돌림): 한 차례를 재생하는 동안 다음 차례의 캡처(ffprobe → ffmpeg → 첫 프레임)를 뒤 스레드로 열어 두고 넘어갈 때 그대로 씀 — 전환은 0.11~0.24초가 됐으나 미리 여는 0.7~1.4초 동안 재생이 멈춤: 10개 중 미리 열기가 겹친 9개 파일에서 최대간격 120~837ms, 파일마다 합쳐 4.9~5.6초 늦음, 미리 열지 않은 마지막 파일만 끊김 0(50ms). 미리 여는 ffmpeg를 Windows BELOW_NORMAL로 낮추고 넘어갈 때 되돌려도(9f04479) 그대로(끊김 117번·최대 837ms) — CPU 차례가 아니라 같은 코어·캐시·메모리 대역·네트워크를 함께 써서로 보임. 사용자 결정: '넘어갈 때 딜레이는 있어도 FPS가 안정적인 게 낫다 — slice 판이 더 안정적' → 미리 열기를 빼고 slice 판(ef7ac2e)으로. 다시 한다면: 미리 열기가 재생과 겹치지 않는 때(재생이 멈춘 동안 등)만, 또는 ffmpeg를 CPU 1~2개로 묶기(psutil cpu_affinity — 같은 세션이 다음 재생이 되므로 넘어갈 때 풀어야 함) — 둘 다 미시험
- 시험 `tests/test_pipe_command.py`(Windows: 첫 열기·재시작 명령 둘 다 `-i` 앞에 slice; Mac: 예전 명령 글자 그대로), `test_movie_pipe_capture`의 고정 명령은 Windows에서만 옵션을 기대

### 2026-11-07 (영상 열기의 단계별 시간 기록)
- **왜**(사용자 결정 — 미리 열기 전에 재기): Windows 선택 재생의 전환 0.80~1.37초 중 `open_file`이 평균 0.93초 — 그 안의 ffprobe·ffmpeg 시작·NAS 첫 4K 프레임·소리 열기·주석 읽기 중 무엇이 큰지 몰라 '다음 파일 미리 열기'를 어디까지 할지 정할 수 없었음
- **기록**: 열 때마다 `[측정] 열기 …` 한 줄(위 '디버깅 팁'). 열기 흐름은 그대로(시각만 찍음). 이 Mac의 작은 ProRes 시험 클립 예: `[측정] 열기 0.18초 — ffprobe 0.05 · ffmpeg 시작 0.01 · 첫 프레임 0.04 · 멈추기 0.00 · 옛 캡처 놓기 0.00 · 소리 0.05 · 첫 화면 0.02 · 주석 0.00 · 그 밖 0.00`
- 시험 `tests/test_open_timing.py`(줄 모양·'그 밖' 음수 없음·파이프는 ffprobe·ffmpeg 시작·첫 프레임으로 나뉨·cv2는 '캡처 열기' 하나·못 열면 줄 없음)

### 2026-11-06 (반복 재생 — 프레임 캐시가 앞부분만 찬 채 처음으로 돌아가면 도중에 멈춤)
- **증상**(사용자 보고 — Windows 4K, GPU 화면 그리기): 파일 하나를 반복 재생하면 2·3바퀴째 도중에 멈춤(기록의 최대간격 0.75·0.84초). `YESONCHECK_FRAME_CACHE=ring`이면 0.1초 안팎이라 전체 프레임 캐시 쪽으로 좁힘
- **원인**: 쉬는 동안 채우는 전체 저장소가 앞부분만 찬 채 반복 재생이 처음으로 돌아오면 읽기 규칙 ②가 보관본을 내주는 동안 ffmpeg 스트림은 파일 끝에 서 있다가, 보관본이 끝나는 번호에서야 ④ 재시작(4K ~0.5초 + 첫 프레임) — 재생 도중의 멈춤
- **고침**: 전체 저장소에서 내주기 시작할 때 스트림을 보관본 끝(`_store_frontier`)으로 미리 옮겨 둠(`_restart(…, park=True)` — 내주는 자리 `pos`는 그대로, 링은 비우지 않음) → 끝에 닿을 때 ①로 이어짐. 스트림이 이미 그 구간 안이면 옮기지 않음 (`movie_pipe_source.py` 항목의 '전체 프레임 캐시')
- **별도 리뷰에서 고친 것**: 멈춘 동안 보관본이 늘면 보관본 읽기마다 다시 옮기던 것(→ 천천히 누름마다 ffmpeg), 스트림이 이미 보관본 안인데 옮기던 것, 옮길 때 링을 비워 보던 자리로 돌아가면 재시작이 생기던 것, 저장소를 실제로 읽지 않던 시험(`test_full_store_never_moves_the_stream`), 옮기기 실패의 기록 머리를 '탐색'이 아니라 '미리 옮기기'로
- **실측**: 이 Mac 파이프 모드 4K 반복 2~4바퀴 14.93~15.20초 → 13.97~14.12초(각 1회, 부하 아래). Windows 시험 빌드(사용자 PC): 반복 2~4바퀴 13.88~13.97초·최대간격 74~146ms, 사용자 확인 "파일 하나 루프 재생은 딜레이 없이 재생"
- 시험 `tests/test_movie_pipe_full_cache.py`: 앞부분만 찬 저장소로 돌아가면 스트림을 그 끝에 옮겨 둠·옮긴 스트림을 다시 옮기지 않음·링에서 내주면 옮기지 않음·저장소가 끝까지 차면 옮기지 않음·멈춘 동안 저장소가 늘어도 다시 옮기지 않음·스트림이 이미 저장소 안이면 옮기지 않음·옮겨 둬도 링이 남아 링 자리로 오가면 재시작 없음, 기존 둘(채움기 실패·전체 모드 재시작)은 옮겨 두는 세션 하나를 더 셈

### 2026-11-06 (사이드바 — 목록 아래 개수 줄, 우클릭 '다른 앱으로 열기')
- **개수 줄**(사용자 요청): 목록 바로 아래 한 줄에 지금 보는 탭의 개수 — Mov `12개`, Seq `시퀀스 3개`, All `15개 — mov 10 · mp4 2 · tga 2 · exr 1`(사용자 결정: 탭 이름은 그대로, 목록 아래 한 줄만). 원본 Mov·Seq 목록에서 셈(`sidebar_all._update_sidebar_count`, 글 `sidebar_counts`). 이어서 **종류마다, 그 안에 버전·테이크 괄호**(사용자 요청 '450개로 나오잖아 — TK1, HD 따로' → 'OSRO, OSAN도 따로' → 'TK1·TK2, v001·v002, v01·v02도'; 모양은 사용자 결정 — `sidebar_counts` 항목): `450개 — 기본 225 (TK1 225) · HD 225 (TK1 225)`
- **다른 앱으로 열기**(사용자 요청): Mov·Seq·All 우클릭 메뉴 맨 아래 'QuickTime Player로 열기'(Mac — 하위 메뉴가 아닌 맨 위 항목: 내 안을 사용자가 승인)와 '다른 앱으로 열기 ▸'(등록한 앱 여러 개 — 사용자 결정, 앱 등록…·앱 지우기 ▸). 시퀀스는 첫 프레임 파일을 넘김(사용자 결정), QuickTime에는 영상만. Windows에는 QuickTime 항목 없음(Windows판 QuickTime은 2016년에 지원 끝). 등록한 앱은 이 PC의 prefs.json `open_with_apps`
- **DJV에 파일이 안 들어감**(사용자 확인 — QuickTime은 잘 열림): Mac의 등록한 앱을 `open -a`(문서 열기 이벤트)에서 `open -n -a <앱> --args <파일>`(명령 줄 인자)로 바꿈. 이어서 **둘을 골라 열면 하나만**(DJV가 인자 중 마지막 하나만 엶) → 등록한 앱은 파일마다 따로 띄움 (`open_with` 항목)
- Windows 빌드 앱은 바깥 앱을 띄울 때 PyInstaller의 환경(`QT_PLUGIN_PATH`·`QML2_IMPORT_PATH`·PATH의 `_MEIPASS`)과 DLL 검색 경로를 걸러서 띄움(`open_with` 항목) — 실기(Windows 빌드 앱 + 다른 Qt 앱)는 미확인
- 내 결정(사용자에게 알림): 고른 것이 20개를 넘으면 먼저 물음, 지금 없는 파일이 있으면 띄우지 않고 오류 창, 개수 꼬리 `(n개)`는 둘 이상일 때만, 등록한 뒤 바로 열지는 않음. `mac_prefs.read_prefs`·`update_pref`의 `path=None`은 PR #25와 같은 글자(합칠 때 겹치지 않게) + 새 `edit_prefs`
- 확인하지 않은 것: QuickTime Player가 이미지 시퀀스를 열지 못한다는 것(그래서 시퀀스만이면 항목을 끔 — 결과는 같음), 한 장을 받아 시퀀스로 알아보는 뷰어가 어느 것인지(README는 '앱마다 다름'), Mac 파일 창(`QFileDialog.getOpenFileName` + `앱 (*.app)`)이 .app 번들을 고르게 해 주는지(눈 확인 몫)
- **Seq 목록 위아래 화살표**(사용자 보고 — 화살표로 옮겨도 그림이 바뀌지 않고 눌러야 바뀜): `player_base.eventFilter`에 Seq 목록 갈래 — 고른 시퀀스를 A로(`load_selected_seq_item` → `on_seq_item_clicked`, 선택 재생 중에는 무시). 예전 시험 `test_up_down_open_the_selected_item_only_on_the_mov_list`가 'Seq는 누를 때만'을 일부러 못 박았던 것을 사용자 요청으로 바꿈 (All 목록은 이미 화살표로 열었음). 선택 재생(Enter·\)은 여전히 Mov·All 전용
- 코드 리뷰(별도 리뷰어)에서 고친 것: `.TGA` 시퀀스의 첫 프레임(누를 때 `first_frame_path`), Windows 환경 정리를 `_MEIPASS` 아래 전부로, DLL 검색 경로를 띄우기 전 값으로·띄운 뒤 되돌리기 실패를 따로 알림, Windows 앱 폴더 cwd, Mov 메뉴도 연 줄을 고른 상태로, 개수 줄이 모르는 탭을 All로 치지 않음, All 섞인 선택의 차례를 시험이 정확히 봄. 그대로 둔 것: 같은 이름의 앱 둘은 툴팁(경로)으로만 구분, 깨진 설정 파일은 우클릭마다 기록에 트레이스백, 등록한 앱 stat은 GUI 스레드, Windows prefs 경로가 PR #25의 `windows_display.prefs_path`와 두 곳(합친 뒤 하나로)
- 시험 `tests/test_sidebar_counts.py`·`tests/test_open_with.py`·`tests/test_sidebar_open_with.py`, `tests/test_sidebar_seq_tab.py`의 화살표 시험 셋, `tests/test_sequence_export_dialog.py`의 Seq 메뉴 글자(맨 아래 무리)

### 2026-11-06 (선택 재생 — 더 짧은 다음 파일로 넘어갈 때 끝까지 갔다 되돌아오던 탐색, 전환 시간 기록)
- **증상**(사용자 보고, Windows 4K 시험 빌드): 파일 하나 반복은 딜레이가 없는데 선택 재생은 파일이 바뀔 때 딜레이. 파일 안은 23.9~24.0fps(`[측정]`). 기록에서 **다음 파일이 앞 파일보다 짧을 때만**(10개 중 넘어감 4번) 열자마자 `정확한 이동: 목표프레임=<끝>` → `마지막 프레임 이동` → `실제 마지막 프레임 발견` → `프레임 이동: 0`
- **원인**: 선택 재생 중에는 `_stop_playback_for_open`이 `stop_video`(슬라이더를 0으로)를 부르지 않아 슬라이더가 앞 파일의 끝에 남은 채 `open_file`이 `positionScroll.setMaximum`을 줄임 → Qt가 값을 새 끝으로 끌어내리며 `valueChanged` → `on_slider_value_changed`가 사용자가 끈 것처럼 `_precise_seek(끝)` → `_seek_to_last_frame`(끝 프레임 읽기) → 다음 `display_first_frame`·`seek_to_frame(1)`이 처음으로. 파이프 4K에서 ffmpeg 재시작 두 번(이 Mac에서 4K 재시작 한 번 0.45~0.63초 — Windows는 안 잼). 선택 재생이 아닌 열기는 `stop_video`가 먼저 슬라이더를 0으로 둬서 없음
- **고침**: `open_file`(A)이 최대값을 바꾸는 동안 신호를 막고 값을 0으로(다른 곳의 `blockSignals` + `setValue`와 같은 방법; 값을 남기면 `update_position_info`가 '오른쪽 끝'으로 보고 Current를 전체 장수로 적음). 손으로 옮긴 슬라이더는 그대로 탐색
- **전환 기록**: 위 '디버깅 팁'의 `[측정] 전환` 줄 — 다음 Windows 시험부터 넘어갈 때의 시간을 숫자로
- **남은 같은 종류(이 수정의 범위 밖)**: 모든 전환의 기본 비용(ffprobe·ffmpeg 시작·NAS에서 첫 4K 프레임 — 이 Mac 파이프 4K 0.69~0.76초, 11-05), 선택 재생이 아닌 열기(사이드바 클릭·↑↓)의 `stop_video` → 옛 캡처 `seek_to_frame(1)`(파이프면 놓을 캡처에 ffmpeg를 한 번 더 띄움 — `movie_pipe_source.py` 항목 '알고 둔 한계' ⑧). 후보: 다음 파일 미리 열기
- 시험 `tests/test_playlist_switch.py`(짧은 파일로 넘어가도 끝으로 탐색하지 않음·Current 1·손으로 옮기면 탐색, 전환 줄 — 넘어감마다 한 줄·첫 차례와 밖에서 본 영상의 낡은 시각은 안 씀)
### 2026-11-05 (Windows 화면 그리기 메뉴 — CPU·GPU, [측정] 줄의 흔들림)
- **왜**: Windows 4K는 타이머를 고친 뒤에도 끊김이 있었고 `YESONCHECK_VIEWPORT=gl`이면 끊김 없음(사용자 확인 — 스튜디오 PC 한 대, 파일 하나 루프; GL에 `YESONCHECK_FRAME_CACHE=ring`을 더해도 차이 없음). PC마다 그래픽 카드가 달라 끄는 길이 필요하고 와이프·주석·고DPI를 확인하기 전이라 **기본은 CPU, Settings → 화면 그리기 (Windows)에서 GPU**(사용자 결정 — 확인 뒤 기본값을 바꿈)
- 새 모듈 `windows_display`(값·저장·`gl_problem` — Qt 없음, %LOCALAPPDATA%\\YesonCheck\\prefs.json의 `display_renderer`), `gl_bindings.context_info`, `app.load_display_renderer`, `player_base._add_display_menu`·`set_display_renderer`. 뷰포트는 창을 만들 때 정하므로 **다음에 여는 창부터 적용**. 환경 변수 `YESONCHECK_VIEWPORT`가 메뉴보다 우선(메뉴 비활성). GPU를 골라도 ES(ANGLE)·소프트웨어 GL·2.0 미만·확인 실패면 CPU로 돌리고 창으로 알림 — 강제(환경 변수)는 확인 없음(기존 규칙). 메뉴는 `videoWidget`보다 먼저 만들어져 '지금 이 창' 줄은 열 때 맞춤(aboutToShow — 만들 때 찾으면 Windows에서 창이 안 열림). GL 그리기 실패 창도 이 메뉴를 안내
- **[측정] 줄**: `… (24.0fps) 최대간격 46ms 끊김 0번 네이티브=…` — 끊김은 틱 간격이 프레임 시간의 1.5배를 넘은 횟수(`_MeasureRun` — 첫 틱과 번호가 건너뛴 틱(재생 중 탐색)은 세지 않음, 처리가 늘 1.5배를 넘으면 거의 모든 틱이 세짐). 평균만으로는 일정한지 알 수 없었음
- **알고 둔 위험**: GPU를 고른 PC에서 드라이버가 GL 확인이나 그리기 중에 프로세스를 죽이면 켤 때마다 같은 곳에서 죽어 메뉴로 되돌릴 수 없음(탈출은 prefs.json·`YESONCHECK_VIEWPORT=raster` — README). 기본값을 GPU로 바꾸기 전에 자동 복구(시작 표시를 남겨 비정상 종료 뒤 CPU로) 넣을 것
- **아직 확인 못 한 것(Windows 실기)**: 메뉴 자체·와이프·주석·전체화면·고DPI 125/150%·다른 그래픽 카드. 이 Mac에서는 `sys.platform`·플랫폼 이름을 바꿔 규칙만 시험. 시험 `tests/test_windows_display.py`

### 2026-11-05 (재생 속도 — 24fps가 25fps로 돌던 타이머)
- **증상**(사용자 보고 — 정보 줄 `실제 25`): `int(1000/fps)` = 41ms를 Qt 기본 타이머(Coarse — 5% 안에서 간격을 바꿈)가 40ms로 돌려 이 Mac에서 23.976·24fps → 25.00fps, 30fps → 31.25fps(약 +4%). 25·50fps는 정확. 소리는 정상 속도라 약 14초마다 400ms 넘게 벌어져 소리 위치를 옮겼음
- **고침**: 정밀 타이머 + 틱마다 시각표(`playback_clock`)로 다음 시각까지 남은 시간을 걺(24fps면 41·42ms가 번갈아). 프레임 읽기·번호는 그대로이고 건너뛰지 않음. 프레임 2장 넘게 밀리면 시각표를 지금으로 옮김 — 탐색·창 끌기 뒤에 밀린 프레임을 몰아 보이지 않게(검토에서 고침), 처리가 늘 늦는 기계는 쉬지 않고 바로 다음 틱. 소리 보정 값(`_calculate_audio_offset`)은 속도와 무관한 고정값이라 그대로. OCR 검토 창 미리보기는 16ms 간격에 소리 위치로 맞추는 다른 방식이라 무관
- **실측**(이 Intel Mac, load 7~11, 8초 1080p 시험 영상): 23.976·24 → 24.0, 25 → 25.0, 30 → 30.0, 50 → 50.0, 60 ProRes → 59.7, 60 h264 → 45.3(처리 한계 — 타이머로 안 풀림); 4K ProRes 4444 334장 13.88초 ×2(전 13.37~13.42초, 영상 길이 13.92초). 1분 영상을 40초 재생하는 동안 소리 위치 조정 4번(차이 489~660ms) → 0번
- **Windows(스튜디오 PC 사용자 확인 2026-11-05)**: 수정 전 1080p도 21fps — Qt 기본 타이머는 Windows 일반 타이머라 약 15.6ms 단위로 돌아 41ms → 46.875ms = 21.33fps로 설명됨. 수정 뒤 1080p 24fps. 4K는 나아졌지만 일정하지 않고, 파일 하나보다 Play Selected(여러 파일)에서 더 흔들림(수치·원인 미확인 — 처음 읽는 파일의 NAS 대역을 먼저 볼 것: 4K 4444는 초당 약 132MB). '알고 둔 한계' ⑦의 'Windows 4K ≈22fps — 기계 전체 CPU 총량이 한계'는 타이머에 막힌 값을 잘못 읽은 판단이었음
- **이 날 이전 실측을 읽을 때**: 334장 시간 등은 4% 빠른 타이머 아래 잰 값 — 예를 들어 '13.9초 안이면 실시간'의 바닥은 13.65초가 아니라 이제 13.88초. 시험 `tests/test_playback_clock.py`·`tests/test_playback_timer.py`

### 2026-11-05 (긴 영상 — 슬라이더를 놓을 때 앱이 분 단위로 멈춤)
- **증상**(사용자 보고 — Windows·Intel·Apple Silicon, 1.6.1에서도 같음): 25분 h264(36781장)에서 핸들을 좌우로 빠르게 끈 뒤 놓으면 앱이 멈췄다가 풀림. 짧은 영상에서는 보이지 않음. 화살표는 원인이 아니고 멈춘 동안 쌓인 입력
- **원인**: 드래그가 프레임 캐시에 맞으면 그림만 바꾸고 캡처는 옮기지 않아(그래서 즉시 반응함) 캡처가 먼 곳에 남는데, 놓을 때 `sync_audio_on_release`가 5장 넘는 차이를 보면 `_seek_sequential` — 0번부터 목표까지 GUI 스레드에서 한 장씩 읽음. 멈춤이 목표 번호에 비례(실파일 30000번 119초)
- **고침**: 놓을 때 `_precise_seek`(직접 이동)로 → 0.08초(실파일 전체를 순차로 읽은 프레임과 대조 — 직접 이동 37곳·끝 근처 80곳 일치). 같은 종류가 끝 근처(`_seek_conservative`의 앞으로 갈래가 현재 위치부터 목표까지 읽음 — 일부러 36778번에 놓으면 92초, 이 파일은 슬라이더 픽셀 간격상 마우스로 닿지 않고 몇천 장 클립에서 닿음)에도 있어 `_read_near_end`(목표 10장 앞부터, 이미 가까우면 옮기지 않음)로 → 0.13초. 그 길이 이제 와이프의 B도 같은 한도로 맞추고(놓을 때 예전 순차 읽기가 하던 일) 오류를 삼키지 않음(소스 실행은 슬롯 예외로 abort — 중간 구간과 같아짐, 빌드 앱은 예외 창)
- **드래그 쪽**(사용자 요구 — 지금처럼 즉시 반응): 캐시에 맞는 드래그는 read·set 0을 시험이 고정, `on_slider_moved`·`_quick_preview_seek`는 바꾸지 않음. 바뀐 곳은 빈도 제한에 걸린 움직임이 끝 근처 값에 닿을 때뿐(`_seek_conservative`를 탐 — A는 읽는 장수가 줄고, 와이프면 B를 최대 11장 읽음)
- 알고 둔 차이: 가변 프레임 h264는 놓을 때 N번째로 디코드한 프레임이 아니라 `set`이 닿은 프레임(공장 VFR 클립 120곳 중 28곳 한 칸, 틈이 큰 클립은 더 — 드래그 미리보기·휠·←와 같아짐). 목표 프레임만 못 읽으면 다음 프레임을 보임(`_seek_direct`의 기존 재시도 — 다른 탐색과 같음)
- **남은 같은 종류(이 수정의 범위 밖)**: 보고한 프레임 수가 실제로 읽히는 수보다 많은 파일(소리가 영상보다 긴 mkv는 1초 꼬리부터, mp4·mov는 15초 꼬리부터 — 240장 클립 측정, 이번 파일은 36781장 전부 읽힘)은 읽히지 않는 구간에 닿으면 `_precise_seek` → `_seek_direct` 실패 → `_seek_sequential`로 0번부터(드래그 움직임마다, 기록 `순차적 프레임 읽기 사용`), 오른쪽 끝은 끝 6곳을 모두 못 읽으면 `_find_actual_last_frame`이 최대 10000장(기록 `빠른 검색 실패, 순차적 검색 시작`). 시험 `tests/test_drag_release_seek.py`

### 2026-11-05 (Mac 전체 ProRes 재생 네이티브 + Settings 메뉴 디코더 전환)
- **왜**: 바로 아래 항목의 4K 4444 경로가 M1(2회차)과 Intel에서 파이프를 재생·파일 전환·스크럽 모두에서 앞섬 → 사용자 결정 "모든 파일을 이 방식으로, 재생 관련만"(그때 근거로 든 'QuickTime과 같은 필터·색'은 위 '색'에서 정정). h264·HEVC 네이티브는 취소
- 게이트(`mac_native_gate`): ⑥½ 4K·⑧ 4:4:4·⑨의 색 태그 조건과 상수를 지우고 **HDR만** 거름(①~⑥·⑦은 그대로), 플랫폼 조건 `is_apple_silicon` → `sys.platform == "darwin"`(함수도 지움). 결과: Mac의 HDR이 아닌 ProRes CFR 파일은 전부 네이티브
- 설정: `mac_prefs.py`(prefs.json 읽기·한 키 고치기 — `default_app`에서 떼어 냄)의 `playback_decoder`, `app.load_playback_decoder`가 켤 때 한 번 읽어 게이트 캐시(`set_preferred_decoder`·`preferred_decoder`·`effective_decoder` — 출처 넷 + `SOURCE_GL_FALLBACK`); 깨진 파일·나쁜 값은 창 1회 뒤 그 세션 ffmpeg. 우선순위 환경 변수 > prefs > 기본
- 메뉴 **Settings → 재생 디코더 (Mac)**(`player_base` — Mac에서만, `set_playback_decoder`·`_sync_decoder_menu`·`_swap_captures_and_settle_latch`): 저장 → 캐시 → 캡처 바꿔 끼움(`player_playback.swap_movie_captures_for_decoder` — `open_file` 없이 같은 프레임, OCR·주석·소리·줌·와이프 B 오프셋 보존) → 걸쇠 풀기 → 메뉴
- 큰 소리 폴백: 네이티브 면 GL 그리기 첫 실패 → 창 1회 + 이 창만 ffmpeg(`VideoFrameItem.has_native_side`·`set_failure_callback`·`latched`·`reset_failure`, `video_widget.streamPaintFailed`, `player_base._on_stream_paint_failed`), 네이티브 면이 남으면 걸쇠 유지(고리 막기)
- 의존성·빌드: PyObjC 12.2.2를 Mac 두 lock에(마커 `sys_platform == "darwin"` — x86_64 lock에 6종 추가, Windows lock 0), `check_frozen_imports`가 macOS 빌드마다 VideoToolbox 디코드(Intel `hw=no`), 개발 venv `p310_tf`에 PyObjC(옛 `p310_native`는 역할 없음)
- 무회귀: 시험 108개 파일 2,753개(이 Mac 2,708 passed·45 skipped — 전체 실행 2,706 + 플레이크 둘을 따로 돌려 통과, 부하 시험 1개는 단독 3/3), `ci/screenshot_check.py` PNG 9/9 바이트 동일(트리는 8장면에서 새 메뉴 항목 3개만 — Mac은 offscreen 메뉴바가 창 안 위젯; Windows는 메뉴를 만들지 않음), CI 41849085625 세 job 성공(Intel pytest 2,706 passed·`네이티브 디코드 … (hw=no)`, Apple Silicon `hw=yes`, Windows 2,569 passed·`건너뜀 (macOS 아님)`). Windows 동작·화면 무변경
- 실측(Intel 이 Mac): 위 'Mac 네이티브 재생'의 '실측'. 알고 둔 한계는 '알려진 문제 및 제한사항'. 눈 확인(M1 3회차·Monterey + RX 580)은 사용자 몫

### 2026-11-04 (Apple Silicon 4K ProRes — VideoToolbox 네이티브 재생)
- (2026-11-05에 Mac 전체 ProRes로 넓힘 — 위 항목. 아래 범위·의존성 글은 이 날 기준)
- **왜**: M1 Mac mini(기본형, 16GB)에서 1.6.1의 4K ProRes 4444 334장이 18.2~18.7초(≈18fps) — 같은 M1의 QuickTime은 13.5초. M1 기본형에는 ProRes 엔진이 없어 QuickTime도 소프트웨어 디코드이고, 차이는 디코드 뒤의 CPU 일(파이프는 한 장 25MB를 CPU가 여러 번 옮김). 그래서 Apple Silicon에서만 4K ProRes 4:4:4를 VideoToolbox(AVAssetReader)가 IOSurface 32BGRA로 디코드하고 GL이 그 표면을 `CGLTexImageIOSurface2D`로 텍스처에 그대로 묶어 그림 — CPU 픽셀 일 0
- 새 모듈 `mac_native_gate.py`(토글·게이트)·`mac_native_source.py`(`NativeVTCapture`)·`frame_handles.py`(손잡이 든 배열)·`gl_surface.py`(CGL)·`annotation_overlay.py`(주석 층)·`overlay_text_layout.py`(B 키 규칙 — `player_playback`에서 옮김). 바뀐 곳: `VideoFrameItem.set_sides`(RECT 텍스처·GL scissor 와이프)·`gl_bindings`의 `glScissor`, `video_widget.updateFrame`의 네이티브 분기·B 키 아이템·주석 층, `player_playback._native_or_pipe_capture`·네이티브 가드(`process_frame` 등)·`[측정]` 줄, `prepare_frame_for_display`의 네이티브 그대로, `app.launch`의 `native_wanted()` 검증, `probe_movie`의 색 태그 필드·`probe_for_open`·`maybe_pipe_capture(…, probe=)`, `annotation_burn`을 굽는 길·층이 함께 쓰는 함수로 나눔(굽는 결과 그대로)
- 범위: Apple Silicon(`auto`)의 4K(너비 ≥ 3840 또는 높이 ≥ 2160) ProRes 4:4:4·색 태그 709/601·HDR 아님만 — 1080p ProRes·4:2:2·태그 없는 파일·h264는 예전 길(사용자 결정 "4k 사이즈만"). **Intel Mac·Windows는 바뀐 것 없음**(기록만 다름 — 재생 한 바퀴마다 `[측정]` 줄 하나, Ruling 3): 열기 분기가 `native_wanted()` 거짓이면 예전 줄 그대로이고 `mac_native_source`를 import하지 않음, 기존 시험의 단언은 그대로 통과(기존 파일 셋 — `test_check_frozen_imports`·`test_gl_video_item`·`test_movie_pipe_gate` — 에는 시험만 더함, 클립 공장 `prores_clips.py`는 인자를 더함), `ci/screenshot_check.py` 9장면 PNG 바이트 동일, Intel GL `yc_app_pixel_check` 동일, Intel·Windows 빌드에 PyObjC 없음
- 실측(M1 Mac mini 2020 기본형 16GB, 10GbE NAS, 4K 4444 334장 — 스파이크 빌드): 창 13.93초·전체화면 14.13초(≈24fps), 와이프(둘 다 네이티브) 23.06초 14.4fps — 소프트웨어 VideoToolbox 리더 둘이 각 16fps라 디코드 한계, 사용자 결정으로 와이프는 된 만큼(ProRes 엔진이 있는 Mac은 미측정). 색은 ffmpeg 파이프 대비 실파일 최대 1·평균 0.03(4:4:4). 이 브랜치 빌드의 M1 2회차 측정은 대기
- 스파이크·1회차에서 찾아 고친 것: `VTDecoderXPCService` 83GB(PyObjC 12.2.2 메타데이터의 `copyNextSampleBuffer` +1 누락 — `registerMetaDataForSelector` 한 번), ←가 매번 재시작(뒤로 재시작 미리 채우기 8장). 구현 중 찾은 것: GUI 스레드의 cancelReading이 SIGSEGV(읽기 스레드만 cancel). 1회차의 재생 중 `-11821`은 이 Mac에서 재현되지 않아 B 방식 그대로 — 2회차에서 확인
- 끄는 길 `YESONCHECK_MAC_NATIVE=off`(그 밖의 값·macOS 밖의 `on`은 시작 때 ValueError). 기록 `[재생] 네이티브(VideoToolbox): …` 줄이 있으면 새 경로, 열기 실패는 창 1회 뒤 파이프로 계속, 도중 실패는 파이프와 같은 B 방식
- 의존성: PyObjC 12.2.2(core·AVFoundation·Quartz — Cocoa·CoreAudio·CoreMedia가 딸려 옴)를 arm64 lock에만. `check_frozen_imports`가 arm64에서 4K 4444를 VideoToolbox로 실제로 디코드(CI 세 job 통과 — Apple Silicon 러너 `hw=yes`)
- 알고 둔 차이(구운 그림과): B 키 글꼴(Qt 글꼴 — 크기는 맞춤), 와이프 선·ROI가 B 키 상자 아래, 와이프에서 A의 글자·주석이 선에서 잘리지 않음, 주석은 안티앨리어싱. 시험 파일 11개 + 픽스처 `tests/native_fakes.py`('테스트 전략'). 눈 확인(M1)은 사용자 몫 — 내부 `records/2026-11-03-mac-native-playback/eye-check.md`

### 2026-11-03 (도형 주석 색 — 빨강이 파랑으로 굽히던 버그)
- `annotation_burn.burn_annotations_on_frame`은 RGB 프레임(표시 경로의 `frame_a`, 내보내기 워커는 BGR → RGB로 바꿔 넘김)에 그리는데 도형(사각형·타원·선·화살표) 색을 `hex_to_bgr`로 넘겨 R·B가 뒤바뀌었음 — 화면과 '주석 포함 영상보내기' 결과 둘 다 (글자 패치는 RGB라 정상, 편집 중 미리보기는 Qt가 그려 정상).
  BGRX 프레임 경로 설계(내부 저장소 `specs/2026-11-03-bgrx-frame-path-design.md`)의 builder check가 실행으로 찾음. 도형 색을 RGB 순서로 바꾸고 `hex_to_bgr`은 지움(다른 사용처 없음). 함수의 약속: **RGB 3채널 프레임, 색도 RGB**.
  시험 `tests/test_annotation_burn_color.py` 7개(도형 4종·노랑·글자와 도형의 채널 순서 일치·입력 불변). `ci/screenshot_check.py`의 '주석 모드' 장면은 주석을 하나도 굽지 않아(모드만 켬) PNG가 바뀌지 않음 — 굽힌 주석 장면은 BGRX 설계 §8-3에서 더함.

### 2026-11-03 (미디어 정보 창 — 코덱 세부 정보)
- 사이드바 우클릭 → 미디어 정보가 `prores` 한 단어만 보여 주던 것을 ffprobe 한 번(`-show_streams -show_format`)으로 코덱 프로파일·태그(`Apple ProRes 4444 (prores · ap4h)`), 픽셀 형식의 뜻(4:4:4 · 12비트 · 알파), 색 공간·범위,
  해상도(화소 비율), 프레임 속도(분수·가변은 평균), 프레임 수, 길이(영상 트랙 — 예전 cv2 값보다 한 프레임 김), 비트레이트, 주사·인코더·만든 때, 음성 트랙, 컨테이너, 파일 크기까지 — 새 모듈 `media_info.py`(순수), `external_tools.probe_json`.
  창은 HTML(예전엔 `**`가 글자로 보였음) + '자세히'에 ffprobe JSON + 글 복사 가능. cv2는 이 창에서 더 쓰지 않음. 시험 `test_media_info` 22개
- `get_video_codec`(codec_name만)은 smoke_test가 아직 씀 — 그대로

### 2026-11-03 (B 키 오버레이 글자 — 해상도와 상관없이 같은 크기)
- `overlay_text`(프레임에 굽는 "File: …, Frame: n/N")가 scale 0.7·굵기 2·여백 10/20/5의 **프레임 픽셀 고정**이라 4K에서 반 크기로 보였음(사용자 보고). 이제 글자·굵기·여백을 프레임 높이에 비례
  (`overlay_metrics(너비, 높이)`: `k = OVERLAY_TEXT_SCALE(1.5) × max(너비/1920, 높이/1080)` — 16:9 창에 맞춰 볼 때 어느 비율이든 같은 크기): 1080p는 예전의 1.5배, 4K는 그 2배 픽셀이라 창에 맞춰 줄이면 같은 크기.
  굵기는 √(k/1.5)만큼 더(4K 8px — 줄여 볼 때 획 가장자리가 섞여 가늘어 보인다는 사용자 보고). 글자 꼬리(g·p·_)까지 상자 안에, 너비를 넘치면 들어갈 만큼 줄임(예전엔 0.5로 한 번만 줄여 300px 프레임에선 넘쳤음).
  1:1 줌으로 보면 4K 글자는 2배(창에 맞출 때 기준). 시험 `test_overlay_text_size` 11개(1080p 1.5배·4K 2배 픽셀·굵기 표·너비/높이 큰 쪽·여백·꼬리·720p·600/300px 넘침)

### 2026-11-03 (재생 FPS 라벨 — 실제로 그린 fps)
- `재생: 24 FPS`가 원래 fps만 보여 줘 4K가 느리게 돌아도 24로 보이던 것을 `재생: 24 FPS · 실제 23.8`로 — `update_playback_fps`가 틱마다 `playback_fps_counter`(재생 틱 `next_frame_playback`이 진행한
  프레임마다 올림 — 전에는 `update_frame`이 올리고 읽는 곳이 없었음)를 걸린 시간으로 나눔(`playback_fps_measured`). 재생 중이 아니거나 재생 시작 뒤 첫 틱이면 원래 fps만. 라벨의 `keep_text`·`fit_text`를
  긴 글로 넓힘(창 크기 시험 무수정 통과). 검토 반영: 첫 틱 부분 구간·OCR 검토 창의 그리기 건너뛰기·탐색 그리기가 값을 흔들지 않게 진행한 프레임을 셈, NaN fps 가드. 시험 `test_playback_fps_label` 11개

### 2026-11-02 (북마크 관리 창 — 경로를 그 자리에서 고치기·우클릭 메뉴·P 키)
- 관리 창의 경로를 DJV처럼 클릭해 고침(고른 항목 다시 클릭·우클릭 → 경로 수정; 더블클릭·Enter는 폴더 열기 그대로). 고친 경로는 commit 즉시 `bookmarks.replace`로 파일에(자리 유지, 다른 창의 것 보존)
  → '폴더 열기'·다음에 열 때 모두 고친 경로. 편집기가 열린 채 단추·메뉴·창 닫기는 먼저 commit(Mac은 단추가 포커스를 안 가져감), 거부된 편집이면 옛 경로로 열거나 지우지 않음.
  다른 앱으로 갔다 와도 편집기는 그대로(Qt 기본은 앱 비활성에 반쯤 친 글을 commit — 검토에서 잡음). 우클릭 메뉴: 경로 복사·경로 수정·폴더 열기·삭제. P/ㅔ 키 = Bookmarks 단추
- 실패는 조용히 넘기지 않음: 빈 글·이미 있는 경로(끝 구분자만 달라도)·읽기/쓰기 실패는 되돌림(+알림·기록), 지금 없는 폴더는 저장하고 경고. 친 글은 공백·`~`·끝 구분자를 정리.
  시험 36개 추가(`tests/test_bookmarks.py` — 실제 QLineEdit 편집기·QFocusEvent·setActiveWindow·QTest 키/마우스(더블클릭은 누름·뗌·더블클릭·뗌 + createEditor 감시)·업데이트 닫기) + `test_error_window` 2개

### 2026-11-02 ② (ProRes 파이프 재생 — 전체 프레임 캐시)
- 4K ProRes 파이프 재생에서 링(8장) 밖으로의 되감기·←·슬라이더·반복 재생은 매번 ffmpeg 재시작(0.45~0.63초)이었음. 플레이어가 연 A/B는 이제 **파일의 모든 프레임을 메모리에 둠**(쉬는 동안 채움 — 아래 '설계 변경') — 채운 뒤의 탐색은 보관본 복사(4K ~3ms)라 재시작 0.
  **fps 목적이 아님**(공급은 이미 충분, 4K 병목은 표시 경로) — 스크럽 체감. 아직 채우지 않은 구간은 예전과 같음
- 링을 번호 → 배열 보관본 `_FrameStore`로 일반화(링 모드 = 1.5.1 링과 같은 보관 집합·재시작 지점 — 단 뒤로 재시작은 목표 8장 앞 착지(아래 마지막 항목), 전체 모드 = 파일 장수·재시작을 건너 남음), 스트림 위치 `_stream_pos`를 따로 둠, 읽기 규칙은 **스트림 우선**(① 스트림 위치 ② 보관본 ③ 앞으로 버리기 ④ 재시작),
  보관은 세션 배열 그대로·호출자에게 복사본
- 예산: 새 모듈 `frame_cache_budget.py` — ① 파일 ≤ 물리 RAM의 20% − 다른 캡처 몫(A/B 장부 공유, 창(프로세스)마다) ② 파일 + 여유 2GiB ≤ 사용 가능 메모리 − 다른 캡처 몫(psutil, `requirements-build.txt`에 고정 — ②의 뺄셈은 최종 검토에서 고침: 둘 다 첫 프레임에서 판정해 앞 캡처가 아직 차지 않음). 판정은 첫 read에서(새 파일 열기 순서 때문), 모자라면 링 8장, 판정은 기록에 한 줄 `[파이프] 프레임 캐시: …`.
  메모리: 4K 13.9초 334장 ≈8.3GB, A/B ≈16.6GB, 1080p ≈2.1GB — 닫으면 바로 돌아옴
- opt-in: `maybe_pipe_capture(path, full_cache=False)` — 플레이어의 `_open_movie_capture`만 `True`(기존 코드 변경은 이 한 줄과 `app.launch`의 토글 검증 한 줄), 주석 내보내기 워커·smoke는 링
- 킬 스위치 `YESONCHECK_FRAME_CACHE=ring`(그 밖의 값은 시작 때 ValueError). 시험은 conftest가 `ring`으로 고정하고 전체 모드 시험이 `auto`를 명시 — 기존 탐색·플레이어 시험의 단언은 그대로 통과(보관본 이름만 바뀜 — 지금은 링 `_ring`·전체 저장소 `_full`)
- 실패: 판정 실패(psutil 오류 등), 판정·탐색 재시작 실패의 사유 글 만들기 실패도 read 예외가 아니라 죽음(B — 기록 1회·오류 창 1회). 죽음·release·GC가 보관본을 비우고 장부를 돌려줌('알고 둔 한계' ④ 해소)
- 시험 파일 3개 추가(`test_frame_cache_budget`·`test_movie_pipe_store`·`test_movie_pipe_full_cache`) + `test_pipe_player`·`test_movie_pipe_seek`에 전체 모드 갈래. 눈 확인(실파일 4K 한 바퀴 뒤 스크럽·메모리·A/B 둘)은 사용자 몫 — 내부 `records/2026-11-02-gl-stream-design/eye-check.md` ②
- **뒤로 재시작 미리 채우기**(사용자 보고 — 4K에서 ←만 느림): 뒤로 가는 재시작은 목표 `KEEP_BEHIND`(8)장 앞에서 띄워 그 장들을 보관 → 링 밖의 ←가 매번 재시작(~0.5초)이던 것이 8번에 한 번(약 0.6초). 앞으로 점프는 그대로(목표에서 바로).
  기존 시험 단언은 무수정 통과, 새 시험 4개(`test_movie_pipe_seek`의 미리 채움·앞으로는 미리 채우지 않음·0에서 자름, `test_movie_pipe_full_cache`의 전체 모드 미리 채우기 — 아래 설계 변경 뒤로는 링에만)
- **설계 변경: 쉬는 시간 채우기**(스펙 §6.5 방식 B, 사용자 결정): 재생 중 내준 프레임을 모두 붙잡던 처음 판은 4K 첫 재생이 16.0~16.2초(링만 13.7~14.6초 — 보관 자체가 장당 GUI ~8ms, 미리 페이지 확보 버퍼 풀도 효과 없음).
  이제 읽는 동안은 전체 모드도 링만, read가 0.3초(`IDLE_FILL_DELAY_S`) 동안 없을 때만 채움기 `_Filler`가 따로 띄운 ffmpeg로 처음부터 전체 저장소 `_full`을 채움(4K 약 7초 — 배치 없을 때; read가 오면 다음 장부터 멈춤, ffmpeg는 소켓에서 저절로 멈춤).
  채움기 실패는 기록 한 번(오류 창 없음 — 스펙 §7-19)이고 캡처는 그대로, release·죽음·GC가 채움 세션을 끝냄. 기존 전체 모드 시험은 '읽은 것은 남는다'는 전제를 '채운 뒤에는 남는다'(`wait_fill`)로 고치고, 채움 전 동작(링과 같음)과 채움기 시험 11개를 더함. 최종 검토(Ruling 11) 뒤: 쉬는 때를 프로세스 전체 read로(A/B에서 한쪽만 재생해도 다른 쪽은 안 채움), 실패 시 장부 몫을 채운 만큼으로, Popen 앞 정지 확인
### 2026-11-02 ① (4K 표시 — GL 텍스처 직접 스트리밍, Mac)
- 31차 끝에 4K ProRes 4444가 이 Mac에서 약 20fps였고 병목은 디코드가 아니라 표시 경로(4K `QPixmap`의 GL paint 48ms/프레임)였음. Mac GL 뷰포트에서 영상 아이템을 `VideoFrameItem(stream=True)`(새 `gl_video_item.py`)로 바꿔 RGB 배열을
  paint 안에서 동기 `glTexSubImage2D(GL_RGB)`로 텍스처에 올리고 고정 기능 사각형으로 그림. GL 함수는 새 `gl_bindings.py`(`getProcAddress` + ctypes — 새 의존성 없음)
- `video_widget`은 뷰포트 결정을 영상 아이템 생성 앞으로 옮기고 `updateFrame`의 마지막 분기만 가름. raster(Windows·offscreen·cocoa 폴백)는 글자 그대로 — `ci/screenshot_check.py` 9장면 PNG 바이트 동일
- 실측(이 Mac, 전부 ML 배치 부하 아래 load1 4.9~18.9): 4K 4444 334장 **13.60~14.54초**(5회; `end` 기준 14.0초 이내 3회) 대 예전 QPixmap 경로 17.57~18.13초(0.78배) — 24fps(13.9초) 경계. 하니스 틱 53~61ms 대 72~88ms —
  **설계 게이트 ≤ 35ms는 부하 아래 미달, idle은 미측정**(함께 도는 4K 디코드와 틱마다의 라벨·슬라이더 갱신은 idle에서도 남아 idle에서도 넘을 수 있음) — **idle 재측정(틱·334장)이 머지 전 필수 눈 확인 항목**. 실제 화면 대조 24쌍 최대 차 2(평균 ≤ 0.011)
- 토글 `YESONCHECK_VIDEO_ITEM=auto|gl|pixmap`(`pixmap`은 킬 스위치, 나쁜 값은 시작 때 ValueError). 기록 `[표시] GL 텍스처 스트리밍(VideoFrameItem)` 줄이 있으면 새 경로
- 지켜야 할 것: paint 밖으로 예외를 내보내지 않음(PyQt5 qFatal — 첫 실패만 기록 + 창 1회 + 빈 그림), 스트림 모드의 `pixmap()`은 크기 자리표시자(내용은 `frame()`), GL 화면 검증에 `grab()`·`grabFramebuffer()` 금지(흰 그림 — `screencapture -R`),
  좌표 규칙(`combinedTransform` = 물리, `device().width()` = 논리, 물리 뷰포트 크기는 Qt처럼 qRound — `int(x + 0.5)`, 파이썬 `round` 금지), 고정 기능 GL 전용(ES·core profile 거부), 텍스처 한도 초과는 축소 없이 큰 실패
- Windows는 기본 raster 그대로(바뀐 것 없음 — 4K는 느릴 것이라 추정했으나 2026-11-03 스튜디오 PC 실측 ≈22fps), `YESONCHECK_VIEWPORT=gl`이면 이 아이템도 켜짐(미확인). 시험 파일 2개(`test_gl_bindings`·`test_gl_video_item`). 눈 확인(이 Mac — idle 재측정 포함)은 사용자 몫

### 2026-10-29 (4K ProRes 재생 — ffmpeg 파이프 프레임 소스)
- 4K ProRes 4444 mov가 실시간 재생이 안 되던 원인은 cv2 내장 FFmpeg의 단일 스레드 픽셀 변환으로 보임(cv2 22fps, 번들 ffmpeg 50.7fps). ProRes류 CFR mov를 번들 ffmpeg(rawvideo bgr24)로 디코드하는
  새 모듈 `movie_pipe_source.py`(`FFmpegPipeCapture`)를 `ImageSequenceCapture` 선례의 덕타이핑 캡처로 열기 경로에 꽂음: 게이트 ①~⑥을 전부 통과한 파일만(opt-in), 나머지는 기존 cv2 그대로
- **기존 재생·탐색 코드는 수정하지 않음**: 바뀐 열기 경로는 `_open_movie_capture`의 삽입 분기·`open_any_capture`·`app.launch`의 모드 검증뿐. 도중 실패는 캡처가 스스로 죽은 cv2 캡처의 겉모습 + 기록 1회 + 오류 창 1회로 끝냄(예외는 열 때만)
- 눈 확인 중 4K가 실시간에 못 미치는 것을 발견해 고침: ① **전송을 stdout 파이프에서 소켓으로**(POSIX `socketpair`, Windows TCP 127.0.0.1 — 프레임당 `recv` 1회, GUI가 GIL을 쥐고 있어도 읽기 스레드가 굶지 않음)
  (링 보관본 복사를 읽기 스레드로 옮기는 것도 해 봤으나 틱 ~3ms 절감이 fps를 못 바꾸고 캡처당 메모리만 약 174MB(쌍 7장분) 늘어 되돌림.) 그리고 사용자가 승인한 예외로 ② **`update_frame`의 중복 그리기 제거**(틱당 `updateFrame` 2→1, 픽셀 동일 — 이 브랜치에서 기존 표시 코드를 바꾼 유일한 곳)
- 4K 4444 334장 재생(이 Mac): 22.0초(15.2fps, 처음 구현) → 18.54초(18.0fps, 소켓 전송) → **16.57초(20.2fps)** — 링 복사 이동(되돌림)이 포함된 판에서 잰 값이고, 최종 판 재측정은 내부 눈 확인 항목. 1080p ProRes는 실시간. **4K는 완전한 실시간이 아님** — 남은 병목은 4K `QPixmap`의 GL paint(48ms/프레임),
  Windows(raster) 4K는 더 느릴 것으로 추정했음(이 Mac에서 raster로 재면 틱 전체 131ms ≈ 7.6fps) — 2026-11-03 스튜디오 PC 스톱워치 실측은 ≈22fps(한 바퀴 15.1초; 추정은 과했고 실시간도 아님). 다음 후보: 4K 표시 경로(직접 GL 텍스처 스트리밍·Windows GL 뷰포트) — '주요 파일'의 `movie_pipe_source.py` 항목
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
