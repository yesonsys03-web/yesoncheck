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
  `SidebarRefreshMixin`·`SidebarSequencesMixin`·`SidebarAllMixin`·`SidebarSortMixin`(2026-11-12 — 목록 정렬)·`SidebarOpenWithMixin`·`SidebarThumbnailsMixin` 9개를 상속
- `VideoPlayerBase`(`player_base.py`)는 `PlayerHoverThumbsMixin`(2026-11-10 — 슬라이더 호버 썸네일)·`PlayerOcrMixin`·`PlayerOverlayMixin` 3개와 `QMainWindow`를 상속

그래서 `VideoPlayer.__mro__`는 `VideoPlayer > PlayerUpdateMixin > PlayerAnnotationsMixin > PlayerSidebarMixin > SidebarBookmarksMixin >
SidebarPlaylistMixin > SidebarConfigPathsMixin > SidebarRefreshMixin > SidebarSequencesMixin > SidebarAllMixin > SidebarSortMixin > SidebarOpenWithMixin > SidebarThumbnailsMixin > PlayerPlaybackMixin > VideoPlayerBase >
PlayerHoverThumbsMixin > PlayerOcrMixin > PlayerOverlayMixin > QMainWindow …`. 이 구조에서 지킬 것:
- 같은 이름의 메서드를 두 믹스인에 두지 않음 — 뒤쪽을 `super()`로 이어 부르는 확장(`PlayerUpdateMixin.instance_status`)만 예외, `tests/test_settings_menu.py`가 지킴 (MRO에서 먼저 나오는 쪽이 가림 — `PlayerSidebarMixin`의 `dragEnterEvent`·`dropEvent`는 `QMainWindow`의 가상 함수를 가림).
  부모 믹스인 모듈(`sidebar_*`·`player_hover_thumbs`·`player_ocr`·`player_overlay`)은 상속받는 쪽(`player_sidebar`·`player_base`)을 모듈 수준에서 import하지 않음 (순환).
  상태(`self.…`)는 `VideoPlayerBase.__init__`이 만들고 믹스인은 `self.`로 부름.
- 시험이 모듈 전역을 바꿔치기할 때는 **그 이름을 읽는 코드가 있는 모듈**에서 바꿈 — 다른 모듈에 다시 내보낸 이름을 바꾸면 말없이 닿지 않음.
  예: `sidebar_thumbnails.ThumbnailWorker`·`shared_config_load.gather_shared_config`·`sidebar_config_paths.PathMapSetupDialog`·`ocr_worker.paddleocr_base_dir`.
- 옛 import 경로는 다시 내보내기로 남아 있음: `yesoncheck.workers`(워커 전부), `player_base`(`EXIT_WAIT_S`·`release_worker`·`wait_for_released_workers`),
  `player_sidebar`(`SidebarScan`·`ThumbnailContext`·`gather_shared_config` 등).

**주요 파일**:
- `yesoncheck/app.py` (480줄): 애플리케이션 부트스트랩 및 CLI 진입점 — 빌드 앱은 `setup_app_logging`이 stdout·stderr를
  창(프로세스)마다 기록 파일 `yesoncheck_<날짜>_<pid>.log`로(Mac `~/Library/Logs/YesonCheck`, Windows
  `%LOCALAPPDATA%\YesonCheck\logs` — update.log와 같은 폴더, 30일 지난 것은 켤 때 지움) 보내고 예외 창(`sys.excepthook`)을
  설치. 업데이트 중(다른 창이 넘긴 업데이트 — 도우미가 `--update-result`로 켠 앱은 빼고)에 켜면 창을 만들지 않고
  "업데이트 중입니다 — 끝난 뒤 다시 열어 주세요" 창만(8초 뒤 저절로 닫힘) 보이고 끝남. 받은 파일·Dock 클릭은
  `mac_app_events`가 받아 첫 파일은 이 창의 A(`open_startup_file` — 있는지 보지 않고 `open_file`로, 열지 못하면 그 오류 창), 나머지와
  켜진 뒤의 것은 새 창(`new_window`)으로 보내고, 창을 보인 뒤 Mac 빌드 앱은 처음 한 번 동영상 기본 앱을 묻고(`default_app`) Windows 빌드
  앱은 이 계정에 연결 프로그램을 등록(`file_associations`) —
  시작 순서는 아래 '여러 창과 업데이트'의 '새 창·동영상 열기·기본 앱'. 스플래시 전에 `movie_pipe_source.movie_source_mode()`·`frame_cache_mode()`를 한 번씩 불러
  `YESONCHECK_MOVIE_SOURCE`·`YESONCHECK_FRAME_CACHE`의 나쁜 값을 시작 때 ValueError로 멈춤 (같은 자리에서 `gl_video_item.video_item_mode`가 `YESONCHECK_VIDEO_ITEM`도, `mac_native_gate.native_wanted()`가 `YESONCHECK_MAC_NATIVE`도 — 값과 함께 macOS가 아닌데 `on`이면 여기서 ValueError, 열 때마다 늦게 실패하지 않게). 그 바로 앞에서 Mac이면 `load_playback_decoder()`가 재생 디코더 설정(`prefs.json`의 `playback_decoder` — `mac_prefs`)을 **한 번** 읽어 `mac_native_gate`의 캐시에 두고 기록 한 줄 `[재생] 디코더: <videotoolbox|ffmpeg> (<출처>)`(출처 넷 — 환경 변수 `YESONCHECK_MAC_NATIVE=on|off`·`prefs.json`·`기본값`·`prefs.json 읽기 실패 — 이 세션만 ffmpeg`); 깨진 파일·나쁜 값(`UserFileError`·`ValueError`)은 기본값으로 치지 않고 트레이스백 + 창 1회(`재생 디코더 설정` — 끝 줄 `PLAYBACK_DECODER_FALLBACK_NOTE` `이 세션은 예전 방식(ffmpeg)으로 재생합니다 — Settings → 재생 디코더 (Mac)에서 바꿀 수 있습니다`) 뒤 **그 세션만 ffmpeg**(`SOURCE_FALLBACK` — 설정을 읽지 못한 채 새 경로를 켜지 않음; 파일은 건드리지 않음). 같은 자리(창을 만들기 전, 모든 플랫폼)에서 `load_slider_thumbnails()`(2026-11-10)가 `prefs.json`의 `slider_thumbnails`를 한 번 읽어 `hover_strip`의 캐시에 두고 기록 `[슬라이더 썸네일] 설정: 켬|끔`; 깨진 파일·불리언이 아닌 값(`UserFileError`·`ValueError`)은 기본(켬)으로 치지 않고 트레이스백 + 경고 창 1회(제목 `hover_strip.SETTINGS_TITLE` `슬라이더 썸네일 설정` — 끝 글은 둘: 나쁜 값(`ValueError`)이면 `이 세션은 슬라이더 썸네일을 끕니다 — Settings → 슬라이더 썸네일에서 다시 켤 수 있습니다`(메뉴가 고른 값으로 고쳐 씀), 깨진 JSON(`UserFileError`)이면 `이 세션은 슬라이더 썸네일을 끕니다.` + 줄 바꿈 + `설정 파일을 고치거나 지운 뒤 다시 켜면 켜집니다 — Settings → 슬라이더 썸네일은 파일을 덮지 않습니다`(메뉴도 그 파일을 덮지 않아 '다시 켤 수 있음'이 거짓 — 최종 리뷰)) 뒤 **이 세션은 끔**(읽지 못한 채 ffmpeg를 돌리지 않음; 파일은 그대로)
- `yesoncheck/main_window.py` (12줄): 믹스인 구성 (`VideoPlayer`)
- `yesoncheck/player_base.py` (2,002줄): 핵심 UI 및 윈도우 관리 — `VideoPlayerBase`(UI 만들기·메뉴·테마 전환·창 닫기·작업 정지·창 사이 연결). Help → 사용법(F1)의 `show_help`는 여기 하나뿐(2026-11-11 — 사용법 매뉴얼을 브라우저로, 아래 `manual_open.py`; `helpButton`·`fullscreenButton`은 만들기만 하고 레이아웃에 넣지 않아 화면에 없음 — 'Full Screen과 Help 버튼은 UI에서 제거'; 그 전에는 `player_playback`에 같은 이름이 하나 더 있어 MRO에서 앞선 그쪽만 불리고 이쪽 글은 한 번도 보이지 않았음). 창을 만들 때 `videoWidget`에 네이티브 프레임용 공급자 둘을 등록(`set_overlay_provider(_overlay_text_for_native)`·`set_annotation_provider(_annotations_for_native)` — 아래 `video_widget.py`). 슬라이더 호버 썸네일(2026-11-10)은 부모 `PlayerHoverThumbsMixin`(아래 `player_hover_thumbs.py`)의 몫이고 여기서는 부르기만 함: `create_overlay_controls()` 뒤 `_init_hover_thumbs()`, Settings 메뉴의 `_add_display_menu` 바로 뒤 `_add_hover_thumbs_menu`, `_release_resources_on_close` 맨 앞(`_sidebar_scan_closed` 바로 뒤) `_hover_thumbs_destroy()`(= close + 필터 `detach` + 팝업 `sip.delete` 즉시). 메인 슬라이더의 툴팁 `'Position'`은 지움(호버 창이 그 자리를 대신 — 기능을 꺼도 되살리지 않음).
  **Settings → 재생 디코더 (Mac)**(2026-11-04 — `sys.platform == "darwin"`일 때만 만듦, Windows 메뉴는 글자 하나 안 바뀜): Settings의 첫 항목으로(2026-11-12 전에는 GPU Acceleration 서브메뉴 바로 뒤 — 그 메뉴를 뺌) 체크 항목 `VideoToolbox (기본)`·`ffmpeg (예전 방식)`(`DECODER_MENU_TEXT`·`DECODER_ACTION_TEXTS`, `decoder_actions` 이름 → QAction·`decoder_action_group` — Mac 밖에서는 빈 채). `_sync_decoder_menu()`가 체크·활성·툴팁을 `mac_native_gate.effective_decoder()`에 맞춤(만들 때·고른 뒤·폴백 뒤): `YESONCHECK_MOVIE_SOURCE=cv2`면 두 항목 비활성 + `DECODER_CV2_TIP`(환경 변수보다 먼저), 출처가 `환경 변수`로 시작하면(`DECODER_ENV_SOURCE_PREFIX`) 비활성 + `<출처>이|가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다`(on이·off가), 그 밖은 활성 + `DECODER_TIP`(이 창은 바로, 이미 열린 다른 창은 다음에 켤 때부터)이고 prefs.json·기본값이 아닌 출처(`SOURCE_FALLBACK`·`SOURCE_GL_FALLBACK`)는 체크된 항목의 툴팁이 그 글. `set_playback_decoder(name)`(macOS 밖 RuntimeError, 모르는 이름은 쓰기 전에 ValueError): 같은 값이 prefs.json·기본값에서 왔으면 체크만 맞춤(체크된 항목을 다시 누르면 Qt가 끔) → ① `mac_prefs.update_pref("playback_decoder", name)` — 실패(`UserFileError`·`OSError`·잠금 `TimeoutError`)면 트레이스백 + 창 1회(`재생 디코더 설정`) + 체크 되돌림, 캐시·캡처 그대로(재시도 없음) ② `set_preferred_decoder(name, source=SOURCE_PREFS)` ③ 기록 `[재생] 디코더 설정: <이름> (Setting 메뉴)` — 유효 디코더가 들어올 때와 같으면(환경 변수가 덮음·폴백 세션에서 ffmpeg 저장) `[재생] 유효 디코더가 그대로(…) — 캡처를 다시 열지 않음`과 메뉴만 ④⑤⑥ `_swap_captures_and_settle_latch(log)`: `swap_movie_captures_for_decoder()`(False면 그 함수가 이미 창을 띄웠으므로 기록 한 줄만) → 바꿔 끼운 **뒤** 스트림 아이템의 걸쇠를 `reset_failure()`로 풂(Ruling 9 — 바꿔 끼우는 동안 뜬 모달의 이벤트 루프가 옛 프레임을 그려도 걸쇠가 걸린 채라 다시 실패하지 않음; 반대 순서면 다시 걸림) — 단 `_latched_on_native_under_ffmpeg()`(걸림 `latched` + `has_native_side()` + 유효 ffmpeg)면 풀지 않고 `KEEP_LATCH_LOG` → `finally`로 `_sync_decoder_menu()`(예외는 그대로 올림 — 두 항목이 함께 체크된 채 남지 않게). **재시도 트리거**(Ruling 11 + 최종 리뷰 F1): 걸쇠가 걸린 창(`_latched_under_ffmpeg` — 네이티브 면이든 RGB 그림이든, 유효 ffmpeg)에서는 유효 디코더가 그대로인 두 길(저장할 것 없는 다시 누름, ③의 '그대로')에서도 `DECODER_RETRY_LOG` (`[재생] 이 창은 그리기가 멈춰 있어(걸쇠) ffmpeg로 캡처를 다시 바꿔 끼우고 걸쇠를 정리함`) 뒤 헬퍼를 다시 부름(네이티브 면이 남으면 헬퍼가 걸쇠를 유지 — 아래 한계 ⑦, RGB면 풀어 다시 그림) — 창 글이 권하는 'ffmpeg (예전 방식)'이 아무 일도 안 하면 빈 영역이 남음. `videoWidget.streamPaintFailed` → `_on_stream_paint_failed`(아래 `video_widget.py`의 '큰 소리 폴백'). 시험 `tests/test_decoder_menu.py`·`tests/test_native_paint_fallback.py`
  OCR 묶음은 `player_ocr`, 오버레이 묶음은 `player_overlay`로 나눠 부모로 붙였고, 스타일시트 문자열은 `main_window_styles`, 붙잡아 둔 워커 정리는
  `worker_lifecycle`로 옮김 (`worker_lifecycle`의 이름은 여기서 다시 내보냄)
- `yesoncheck/player_ocr.py` (1,845줄): `PlayerOcrMixin` — ROI·분석 방식 UI 상태, 분석 시작(OCR·애니매틱·애니매틱2)과 진행·완료 콜백, 검토 창 수명,
  결과 저장·불러오기, 구간 내보내기 (`VideoPlayerBase`의 부모)
- `yesoncheck/player_overlay.py` (753줄): `PlayerOverlayMixin` — 영상 위 오버레이 컨트롤(V 키)의 위젯·위치·크기·설정 파일(`~/.yeson_overlay_settings.json`)
  (`VideoPlayerBase`의 부모)
- `yesoncheck/player_hover_thumbs.py` (361줄): `PlayerHoverThumbsMixin` — **슬라이더 호버 썸네일**(2026-11-10, DJV식 미리보기 — 시간 슬라이더 위 커서 자리의 프레임 그림 + 번호가 커서 위에 뜸)을 플레이어에 잇는 얇은 층 (`VideoPlayerBase`의 맨 앞 부모, 이름은 모두 `_hover_`). 디코드·위젯 그리기·설정 파일 읽기는 하지 않고 재생 캡처에서는 `get`(위치·장수·크기)만 — 호버용 그림을 재생 캡처로 꺼내면 본화면이 튀고 파이프 스트림·링이 깨지므로 따로 만든 '띠'(아래 셋)에서만 꺼냄. `_init_hover_thumbs`(`create_overlay_controls` 뒤 — 필터가 `slider.window()`에도 걸려야 해서)가 커서 위 창 하나(parent는 `slider_preview.popup_parent(self)` — 플랫폼 분기, 아래 `slider_preview.py`; **창을 닫으면**(`_release_resources_on_close` → `_hover_thumbs_destroy`) 띠를 버리고 두 필터를 떼고(`detach`) 창을 `setParent(None)` + `sip.delete`로 바로 지움 — Windows는 parent가 없어 이 길이 유일한 정리, `deleteLater`는 exec 없이 끝나는 프로세스에서 돌지 않음; 파일을 바꿀 때는 숨기기만, 지운 뒤 `_hover_thumbs_open`은 아무것도 안 함)·두 슬라이더(`positionScroll`·`overlaySlider`)의 필터(parent + `_hover_filters`로 쥠)·쉬는 때 타이머를 만듦.
  **수명**: `open_file`(A 영상 — 슬라이더 범위를 정한 직후)이 `_hover_thumbs_open(경로, 장수, 폭, 높이)` — 옛 띠를 버리고 새 계획만 둠(워커는 아직): 기능 끔·시퀀스면 아무것도, 장수·크기를 모르면(0) 기록만, 크기 상한(4GB)을 넘으면 **계획만**(번호 + 빈 상자 — 저장소·타이머 없음), stat 실패는 트레이스백 + 띠 없음. `_release_side('A')`·job 불러오기(`player_playback._load_job_list`가 `cap_a`를 `_release_side` 없이 놓는 자리에 한 줄)·기능 끄기가 `_hover_thumbs_close`(틱 정지 → 워커 `stop` → `release_worker` → 계획·저장소 놓기 → 창 숨김 — 숨기기만이라 파일을 바꿀 때는 이것; 여러 번 불러도 됨), 창 닫기(`_release_resources_on_close` 맨 앞)는 `_hover_thumbs_destroy`(= close + 필터 `detach` + 팝업 `sip.delete` 즉시 — 지운 뒤 `_hover_thumbs_open`은 아무것도 안 함). B 열기·와이프·디코더 전환·주석·OCR은 띠를 건드리지 않고, 같은 경로를 A로 다시 열면 다시 만듦. `open_file`은 맨 앞(경로 정리 직후, 새 캡처를 열기 전 — 삽입 한 줄)에 `_hover_thumbs_pause()`도 부름: 도는 워커가 있으면 `paused = True`로 옛 띠 ffmpeg를 바로 정지 — ↑↓·사이드바로 넘길 때 새 캡처 열기(NAS에서 ffprobe·파이프 ffmpeg 시작·첫 디코드)와 옛 띠의 디코드가 다투지 않게; 연 뒤 `_hover_thumbs_open` → close가 kill하고, 못 열었거나 B를 열었으면 다음 쉬는 틱이 되돌림(최종 리뷰).
  **쉬는 때**(`TICK_MS` 50ms 타이머 — 띄울 워커가 있거나 돌 때만): 바쁨 = 재생(`timer.isActive()`)·두 슬라이더의 `isSliderDown()`·**재생 캡처의 `get(CAP_PROP_POS_FRAMES)`가 `IDLE_S` 0.3초 안에 바뀜**(←/→ 연타·휠·클릭도 4K면 한 칸마다 디코드라 쉬는 때가 아님 — 재생·탐색 코드의 길마다 훅을 달지 않고 cv2·파이프·네이티브 어느 캡처에서나 같은 신호, `get`은 디코드 안 함; 0.3초는 전체 프레임 캐시 채움기의 `IDLE_FILL_DELAY_S`와 같음). 기존 표지 `is_dragging`은 **보지 않음**: `on_slider_moved`가 True로 두고 valueChanged만 되돌리는데 드래그 미리보기가 슬라이더 값을 `blockSignals`로 써 두면 놓을 때 valueChanged가 안 와 True로 남을 수 있음(실기 보고 — 드래그를 한 번 놓은 뒤 연 모든 파일에서 띠가 안 생겼음); 드래그는 `isSliderDown`이, 미리보기 디코드는 위치 변화가 덮음. (표지가 풀리지 않던 원인은 같은 날 '와이프 드래그 뒤 B 검게 남음'에서 놓을 때 되돌리게 고침 — 판정은 그래도 이 표지를 안 봄) 워커 없이 `BUSY_LOG_S` 5초 넘게 바쁘면 진단 한 줄 `[슬라이더 썸네일] 쉬는 때를 기다리는 중 <초>초 — 재생 <bool>, 슬라이더 누름 <메인>/<오버레이>, 위치 변화 <초>초 전 — <파일>`(계획마다 한 번). 열린 지 `START_DELAY_S` **1.0초**(처음 0.5초 — 3차 측정 전 Ruling 14로 늘림: 열고 곧바로 Play하는 흐름과도 겹치지 않게, 그 안에 Play하면 워커를 띄우지 않은 채 재생)가 지나고 바쁘지 않으면 그때 워커를 띄움(선택 재생·↑↓ 연타처럼 그 전에 넘어가면 ffmpeg를 아예 안 띄움 — 비용 0), 돌면 틱마다 `worker.paused = busy`만(워커는 값이 바뀔 때만 잠금을 잡고 ffmpeg를 정지·재개 — 같은 값이면 아무것도 안 함). **재생 중 틱은 가장 싼 길**(Ruling 14): 맨 앞에서 `timer.isActive()`면 재생 캡처의 `get`·`isOpened`·슬라이더를 보지 않고 워커가 있으면 `paused = True`만 둔 채 끝 — 그때를 '움직임'으로 적어(`_hover_moved_at`) 재생이 멈춘 뒤 `IDLE_S`를 새로 세고, 재생은 진단 기록의 '오래 바쁨'에 넣지 않음(재생 전부터 세던 바쁨에 재생 시간이 더해 적히지 않게). OCR·씬 감지·내보내기 워커(자기 캡처)는 보지 않음.
  **조회**(호버마다 — 디코드 없음): 두 슬라이더 모두 **메인 값→프레임 식**(`_hover_main_frame` — `v ≥ 최대값 − 1`이면 마지막 장, 아니면 `round(v / 최대값 × (N − 1))`; `on_slider_moved`·`sync_audio_on_release`와 같음). 오버레이 클릭은 `on_overlay_slider_released`가 `min(v, N − 1)`로 간 뒤 `sync_audio_on_release`가 메인 규칙을 다시 걸어 실제 착지가 메인 식이 되므로(v = N − 2 → 마지막 장 — 구현 중 프로브로 확인, 스펙 §5.4 정정) 오버레이 값은 그 프레임 자리의 메인 값(`round(프레임 / (N − 1) × 최대값)`)으로 바꿔 메인 식에 넣음 — 값→프레임 식이 코드에 네 벌(기존 셋 + 이것)이고 둘의 일치는 클릭 착지 대조 시험이 지킴. 번호 = 프레임 + 1(Current 라벨과 같음), 그림 = 가장 가까운 샘플 — 아직 없으면 지금 워커의 **키프레임 거친 띠**(`coarse_strip` — 2026-11-11, 아래 `hover_strip_builder.py`)에서 가장 가까운 키프레임(`nearest`)이 차 있으면 그것, 그것도 없으면 빈 상자(긴 파일은 정확한 띠가 앞에서부터 차므로 앞부분은 정확한 그림·뒷부분은 거친 그림이 섞여 보임 — 의도; 거친 띠는 참조를 한 번 읽어 씀 — 워커가 그사이 버려도 그 조회는 쥔 참조로 끝남). **낡은 계획 가드** `_hover_live_plan`: 조회마다 계획이 없거나 `cap_a`가 없음·닫힘·`filename_a ≠ _hover_path`면 None(창 없음) — A를 놓는 길이 모두 `_release_side`를 거치지는 않고 띠가 끝나면 틱도 멈춰 있으므로(죽은 캡처는 틱도 닫음).
  **끝 신호**(`done`·`failed`·`coarse_done`)는 GUI 대기열 연결 — 슬롯은 `sender()`가 지금 워커일 때만 받음(옛 워커가 놓이기 전에 넣은 신호가 다음 파일 뒤에 와도 버림). 완성이면 기록 한 줄 + 틱 정지(워커 객체는 닫을 때 놓음). 거친 띠 완성(`coarse_done`)은 기록 한 줄만 — 틱은 그대로(정확한 띠가 아직), 거친 띠의 실패는 워커가 창 없이 기록만 해 여기로 `failed`가 오지 않음. **실패**: 기록(stderr)은 매번, 오류 창(`error_window.show_error` — 끝 줄 `Settings → 슬라이더 썸네일을 끄면 만들지 않습니다`)은 **파일마다 한 번**(`_hover_failed_for` — 이 창이 떠 있는 동안 실패한 파일 모두의 set이라 실패하는 두 파일을 오가도 다시 안 뜸), 다시 시도 없음, 이미 채운 장은 그대로 보임; 워커 생성자의 `ToolNotFoundError`(ffmpeg 없음)도 같은 길(50ms마다 다시 시도하지 않음).
  **Settings → 슬라이더 썸네일**(`MENU_TEXT`): `create_menu_bar`가 `_add_display_menu` 바로 뒤에서 `_add_hover_thumbs_menu` — 체크 항목 하나·툴팁 `HOVER_TIP`(`setToolTipsVisible`), Mac·Windows 모두(Mac은 화면 그리기 메뉴가 없어 '재생 디코더 (Mac)' 뒤). 체크는 파일이 아니라 이 프로세스의 캐시(`hover_strip.enabled()`)를 따름. `set_slider_thumbnails(bool)`: 파일이 이미 그 값이면 쓰지 않음(창마다 프로세스라 다른 창이 먼저 저장했어도 이 창은 아래에서 따름), 파일 값이 불리언이 아니면 트레이스백 뒤 고른 값으로 고침(시작 경고가 약속한 '다시 켤 수 있음' — 명시적 선택이라 지어낸 값이 아님), 저장 실패(`UserFileError`·`OSError`·잠금 `TimeoutError`)는 트레이스백 + 창(`hover_strip.SETTINGS_TITLE` `슬라이더 썸네일 설정` — 시작 경고 창과 같은 상수) + 체크 되돌림(캐시·띠 그대로), 성공이면 캐시 + 기록 `[슬라이더 썸네일] 설정: 켬|끔 (Settings 메뉴)` + 이 창에 바로(끔 → `_hover_thumbs_close`, 켬 → 지금 A가 열린 영상이면 그 계획을 다시 엶 — 워커는 쉬는 때 틱이). 이미 열린 다른 창은 다음에 켤 때부터.
  **기록 줄**(stdout, 기능이 꺼져 있으면 없음): `[슬라이더 썸네일] 띠 만들기 시작: <장>장(간격 <step>, 전체 <N>장) <w>×<h> — <파일>`·`띠 완성: <채운>/<장>장 <초>초 — <파일>`(초는 띄운 때부터 — 멈춘 시간 포함)·`띠를 만들지 않음: <사유> — <파일>`, 실패는 stderr `띠를 만들지 못했습니다 — <파일>` + 글 전문. 긴 파일(간격 > 1)이면 `띠 만들기 시작` 다음에 워커가 `거친 띠 먼저: 키프레임 <K>장 → <장수>장(간격 <m>, 전체 <N>장) — <파일>`(K는 받을 키프레임 전부, 장수는 1000장 넘으면 m장마다 줄인 거친 띠) 또는 `거친 띠 건너뜀: <사유> — <파일>`, 다 채우면 `거친 띠 완성: <채운>/<장수>장 <초>초 — <파일>`(장수 = 줄인 거친 띠 `coarse_count`, 초는 띄운 때부터), 거친 띠 실패는 stderr `거친 띠를 만들지 못했습니다(정확한 띠는 계속) — <파일>` + 사유 전문(창 없음); 간격 1이면 거친 띠 줄은 없음. 시험 `tests/test_player_hover_thumbs.py`·`tests/test_hover_thumbs_settings.py`
  - `yesoncheck/hover_strip.py` (221줄): 순수 규칙 — Qt·cv2 없음(시험이 Qt 없이 봄). **띠 계획** `plan_for(N, W, H)` → `StripPlan`(`total`·`step`·`count`·`width`·`height`·원본 크기 `source_width`·`source_height`(2026-11-11 — 스레드 규칙용), `source_frame(i) = i × step`, `sample_for(f)` = `round(f / step)`을 `[0, count − 1]`로 자름, `frame_bytes`; 값이 1 미만이면 ValueError): `N ≤ MAX_THUMBS`(500)면 프레임마다, 넘으면 `step = ceil(N / 500)`·`count = ceil(N / step)`(14,400장 → 간격 29·497장). 크기는 **320×320 상자 안**(`thumb_size` — `THUMB_WIDTH` 320은 이름과 달리 '긴 변': 가로 영상(W ≥ H)은 폭 320, 세로 영상은 높이 320, 짧은 변은 비율대로 짝수·최소 2; 실행 중 Ruling 3 — 처음 글의 '폭 320'이면 세로 1080×1920이 320×568·500장 272MB) → 16:9 172,800B/장·500장 86.4MB, 어떤 비율이든 500장 ≤ 153.6MB(정사각형). ffmpeg `scale`에 폭·높이를 **둘 다 명시**(`-2`에 맡기면 ffmpeg가 고른 크기와 이쪽 버퍼 크기가 어긋날 수 있음). **크기 상한** `skip_reason(path)`: `os.stat` 크기 > `MAX_FILE_BYTES`(4×10⁹ — 사용자 결정 '크기 상한', 숫자는 제 결정)면 사유 글 `파일 <x.x>GB > 상한 4.0GB`(`frame_cache_budget.gb`), 아니면 None, OSError는 그대로 올림 — `select`는 디코드한 뒤 버리므로 띄엄띄엄이어도 ffmpeg가 파일 **전체**를 읽고 디코드함(NAS에서 수십 GB짜리 긴 ProRes를 통째로 다시 읽지 않게). **스레드 규칙**(2026-11-11, Ruling 24·25·26) `thread_limits(plan, 디코더, 필터, codec=None)` → `(None, None)`이면 띠 ffmpeg에 스레드 옵션을 넣지 않음(ffmpeg 기본, 이 Mac은 CPU 수만큼), 아니면 부른 쪽의 값(`hover_strip_builder`의 두 상수 — 1코어): ① 원본 화소 ≤ `SINGLE_THREAD_ABOVE_PIXELS`(1280×720)면 어느 코덱이든 없음 ② ≤ `INTER_CODEC_FULL_THREADS_MAX_PIXELS`(1920×1080)이고 코덱(헤더의 `codec_name` — 워커가 긴 파일이면 늘 읽음)이 **허용 목록** `LONG_GOP_FULL_THREADS_CODECS`(`{"h264"}` — 재생 게이트를 잰 코덱만; 프로젝트 원칙 '양성 증거로만 켬', Ruling 26)에 있으면 없음 ③ 그 밖(720p보다 크고 목록 밖 — hevc·vp9·av1은 안 잼, all-intra는 불통과·코덱을 모름 — 짧은 파일은 헤더를 읽지 않음·1080p보다 큼)은 1코어(막는 목록이던 Ruling 25 때는 `ALL_INTRA_CODECS` 밖의 all-intra가 1080p에서 기본 스레드로 갔음). `ALL_INTRA_CODECS`(prores·dnxhd·mjpeg·rawvideo)는 거친 띠 건너뜀(`hover_keyframes`)에만 씀. 까닭은 재생 게이트(이 Mac — 켬이 끔의 범위 안인지): 1080p ProRes 422 HQ 334장(네이티브 재생) 켬·끔 각 9판 — 끔 최대간격 44~62ms·끊김 0/9, 켬 2판이 89·124ms(끊김 2/9 — 그때 ffmpeg는 Play 직후 이미 정지돼 CPU 0)로 **불통과**(Fisher p≈0.47 — 증명은 아니지만 범위 기준·재생 최우선); 720p H.264 721장(cv2) 켬·끔 각 3판 — 켬 45·67·76ms가 끔 44~91ms 안 **통과**; 1080p H.264(KOTH 애니매틱 30초 클립, cv2) 켬·끔 각 3판 — 켬 62·65·48ms가 끔 50~84ms 안 **통과**. 1코어 자체는 4K ProRes 4444의 Play 직전 디코드 버스트 때문에 측정 뒤 넣은 것(Ruling 14). 얻는 것(이 Mac 실측 — 헤드리스 ffmpeg 단독): 긴 720p 애니매틱(FL106) 정확한 띠 67.0초 → 18.8초, 긴 1080p H.264 애니매틱(KOTH 1920×1080 23.976fps 35,693장) 82.2초 → 24.6초(앱 안 idle 값은 아래 `hover_strip_builder.py`의 실측 — 거친 패스가 앞에 붙어 합); 1080p ProRes·4K 명령은 글자 그대로; 문턱은 부를 때마다 모듈 값으로 읽음. **저장소** `HoverStrip`(행 규칙은 부모 `ImageRows`(count·width·height) — 키프레임 거친 띠 `hover_keyframes.KeyframeStrip`도 같은 부모; 2026-11-11에 나눔, 동작 그대로): `(count, h, w, 3)` uint8 배열 하나(연속) + `bytearray` 채움 표시 — 쓰는 쪽 워커 스레드·읽는 쪽 GUI, 잠금 없이 **행을 다 복사한 뒤에 표시**(`put` — 길이가 `frame_bytes`와 다르면 ValueError·표시 없음), `has`·`image(i)`(그 행의 뷰 — 안 채웠으면 LookupError)·`filled_count`·`nbytes`; 같은 행은 한 번만 put(다시 쓰면 GUI가 덮어쓰는 중인 행을 읽을 수 있음 — 워커가 지킴). **설정**: `PREF_KEY` `slider_thumbnails`, `prefs_path()`(Windows `windows_display.prefs_path()`, 그 밖 `mac_prefs.prefs_path()` — 두 경로를 한 함수로 합치는 일은 범위 밖), `read_enabled`(키 없으면 True, 깨진 파일 `UserFileError` 그대로, 불리언 아님 ValueError — 값을 지어내지 않음), `save_enabled`(그 키만 — `mac_prefs.update_pref`, 불리언 아니면 TypeError로 파일 그대로), 프로세스 캐시 `set_enabled`/`enabled`(`windows_display._preferred`와 같은 모양 — 불리언 아니면 TypeError). 상수(`MAX_THUMBS`·`MAX_FILE_BYTES`)는 부를 때마다 모듈 값으로 읽음(시험의 monkeypatch가 닿게 — 기본 인자로 굳히지 않음). `MENU_TEXT` `슬라이더 썸네일`·`LOG_PREFIX` `[슬라이더 썸네일]`·`SETTINGS_TITLE` `슬라이더 썸네일 설정`(설정 창 제목 — 시작 경고(app)·메뉴 저장 실패(믹스인)가 함께 씀; 이 기능의 글 상수는 Qt 없는 이 모듈 한 곳). 시험 `tests/test_hover_strip.py`
  - `yesoncheck/hover_strip_builder.py` (492줄): `HoverStripBuilder(QThread)` — 띠를 만드는 워커 하나와 차례로 띄우는 프로세스들(화면 없음 — 긴 파일이면 헤더 ffprobe → (all-intra·모르는 속도가 아니면) 패킷 ffprobe → 거친 띠 ffmpeg → 정확한 띠 ffmpeg, 아니면 정확한 띠 ffmpeg 하나; 아래 '거친 패스'). 명령 `build_command(ffmpeg, 파일, plan, codec=None)`: `ffmpeg -nostdin -v error [-filter_threads 1] [-threads 1] -i <파일> -map 0:V:0 -fps_mode passthrough -vf [select=not(mod(n\,STEP)),]scale=W:H -f rawvideo -pix_fmt rgb24 pipe:1`(인자 리스트 — 셸 없음; `-map 0:V:0`·`-fps_mode passthrough`는 파이프 소스와 같은 이유, 간격 1이면 `scale`만; **1080p보다 큰 원본·720p보다 크고 허용 목록(h264) 밖 코덱·코덱을 모르는 720p보다 큰 원본은 디코드·축소가 1코어**(Ruling 14 — 나머지(720p 이하, 1080p 이하 h264)는 두 옵션을 넣지 않음: 2026-11-11 `hover_strip.thread_limits`, Ruling 24·25·26): 디코더 스레드 `FFMPEG_THREADS` = 1(`-threads` — 입력 옵션이라 `-i` 바로 앞)과 필터 스레드 `FFMPEG_FILTER_THREADS` = 1(`-filter_threads` — 전역 옵션, `-i` 앞), 둘 다 호출 때 읽고 None이면 그 옵션을 빼 ffmpeg 기본(이 Mac은 CPU 수 16만큼). **`-threads`는 디코더 스레드만 묶음** — `-vf scale`(4K → 320 축소 + rgb24)은 따로 CPU 수만큼 slice 스레드를 써서(번들 ffmpeg 9.0.2 실측 프로세스 스레드: 기본 68개, `-threads 2`만 54개, `-filter_threads 1 -threads 2` 24개, 둘 다 1이면 22개 — 나머지는 ffmpeg 자신의 구성 요소 스레드(미확인)) 필터 쪽 손잡이가 `-filter_threads`; Play 직전 여러 코어로 4K 장을 한꺼번에 디코드·축소하는 버스트를 없애려고 1차 측정 뒤 `-threads 2`(Ruling 11), 2차 측정도 게이트 실패라 둘 다 1(Ruling 14) — 대가로 띠 완성이 이 Mac 4K 334장 쉴 때 약 6초 → 약 20초(`-threads 2`, 실측) → 약 38초(1코어, 3차 실측 38.3·38.2초), 아래 '최근 변경 사항' 2026-11-10의 실측). 재생 캡처는 안 건드림(파일을 따로 엶). 전송은 **stdout 파이프**로 충분 — 장당 ≤ 307KB에 쉴 때만 읽어, 파이프 소스가 소켓으로 옮긴 이유(4K 25MB를 64KB씩 읽으며 재생 중 GUI와 GIL 다툼)가 해당 없음; 한 장(`frame_bytes`)씩 `readinto`로 다 채워 `strip.put`, 계획보다 많은 장은 읽어 버림. **멈춤 = psutil 프로세스 정지**: `paused`가 **바뀔 때만** 잠금을 잡고 `psutil.Process(pid).suspend()`/`resume()`(POSIX SIGSTOP·Windows NtSuspendProcess — 같은 값이면 잠금도 psutil도 부르지 않음: 재생 중 틱마다 True를 넣어도 SIGSTOP 반복·워커 스레드와의 잠금 다툼 없음) — 파이프를 안 읽기만 하면 프레임 스레드들이 이미 디코드 중인 장(4K 4444면 8코어로 수백 ms)을 마저 디코드해 재생 첫 틱들과 겹치므로; 정지된 프로세스에도 kill은 먹힘. 정지·재개 실패(`psutil.Error` 전부 — `NoSuchProcess`·`AccessDenied` 등 — 와 `OSError`: Windows에서 끝나 가는 프로세스의 NtSuspendProcess는 psutil이 감싸지 않은 OSError일 수 있음)는 기록 한 줄 뒤 읽기만 멈춤/이어 감(GUI 틱 슬롯·워커 스레드로 올리지 않음). 잠금이 지키는 `_suspendable`(띄운 직후 ~ 읽기 끝)일 때만 신호를 보냄 — 끝난 뒤에는 정지하지 않아 거두기(wait)가 막히거나 다른 프로세스가 물려받은 PID를 건드리지 않음; **꼬리 함정**: 정상 EOF인데 멈춤 표지가 서 있으면(마지막 장을 받는 사이 정지됨) 거두기 전에 재개(`_end_reading`), 띄운 직후 이미 `paused`면 바로 정지(`_attach`). stderr는 데몬 스레드가 끝까지 모음(안 비우면 파이프가 차서 ffmpeg가 멈춤). 끝 신호: `done(채운 장수, 띄운 때부터 초 — 멈춘 시간 포함)`(종료 코드 0이고 장 경계에서 EOF — 계획보다 적게 와도(잘린 파일·VFR) done이고 남은 샘플은 빈 채, 많으면 기록 `넘침 n장`; **stderr에 글이 있어도 done**: 잘린 파일(복사·렌더가 진행 중인 NAS 파일)이면 번들 ffmpeg 9.0.2가 `partial file`·`wrong picture data size`·`Decoding error`를 오류 수준으로 찍고도 종료 코드 0으로 끝나므로(실측: 헤더 48장 번호 클립의 꼬리를 자르면 33장) 그 글은 기록(stderr) `[슬라이더 썸네일] ffmpeg 경고 (종료 코드 0, <n>장 채움) — <파일>` + 전문으로 남기고 창은 없음 — 처음의 'stderr에 글이면 failed'는 그런 파일을 열 때마다 실패 창을 띄웠음(최종 리뷰)), `failed(글 — 파일·명령·종료 코드·stderr 전문·트레이스백)`(못 띄움·한 장 도중 끊김(0바이트 EOF만 정상 끝)·종료 코드 ≠ 0·예상 못 한 예외(읽기·넣기 오류)만 — 이미 넣은 장은 둠). `progress(장수)`는 `BATCH_S` 50ms 또는 10장마다 묶음(잠금 밖). `stop()`(GUI, 여러 번 불러도 됨): 표지 → kill(정지돼 있어도) → 거두기 → 스레드 끝 대기(각 `STOP_WAIT_MS` 2초까지 — 넘으면 기록 뒤 돌아가고 부른 쪽이 `release_worker`로 붙잡아 둠; stdout은 여기서 닫지 않고 워커가 닫음 — 닫으면 readinto 안의 읽기를 기다리거나 정상 중단이 ValueError 트레이스백이 됨). 표지 뒤엔 done·failed를 내지 않지만 트레이스백이 있는 예상 못 한 예외는 stop 뒤라도 기록에 남김(조용히 사라지지 않게). `run`의 예외는 밖으로 내지 않음(QThread.run에서 새면 PyQt5가 프로세스를 끝냄) — 모두 failed 글로. 끝 신호를 직접 연결로 받아 그 안에서 `paused`·`stop`을 부르면 잠금을 다시 잡음 — 플레이어는 대기열 연결. **거친 패스**(2026-11-11 — 한 `run` 안에서 정확한 띠 앞에): 간격 > 1이면 먼저 헤더 ffprobe(`hover_keyframes.probe_header` — 코덱·속도·시작만, 패킷 없이라 파일을 다 읽지 않음; 워커 스레드)로 코덱을 늘 알아내고(`codec` — 거친 띠를 만들든 말든; `run`이 정확한 띠 명령 `command`를 그 코덱으로 다시 정함 — 생성자의 명령은 코덱을 모를 때의 것) all-intra 코덱·모르는/240 넘는 속도면 `거친 띠 건너뜀` 한 줄(실패 아님) 뒤 정확한 띠만, 그 밖이면 패킷 ffprobe(`scan_keyframes` — 파일 전체를 읽음, 버림(D) 패킷 제외)로 키프레임을 읽어 전체의 1/4 이하면(`coarse_wanted`) 거친 띠 저장소를 다 만든 뒤 `coarse_strip`에 **한 번** 대입(잠금 안 — 그 전·버린 뒤·정확한 띠 완성 뒤(`done` 앞)·`stop()` 뒤 None; GUI는 조회마다 그 참조만 읽음)하고 `build_coarse_command`(`build_command` 모양 + `-skip_frame nokey`(디코더 옵션 — `-i` 앞, 디코더 스레드 바로 앞), 스레드 규칙도 같음; **select 없음** — 키프레임 전부(K장)를 받아 i번째 장 중 `i % m == 0`만 행 `i // m`에 넣음(m은 키프레임이 `MAX_COARSE` 1000장을 넘을 때 — 목록도 `frames[::m]`; 리뷰 L-3, 스펙 §3.2의 select와 다름 — 디코드 비용은 같고 파이프 전송만 K장, 장수 검사가 받은 수 == K로 정확해짐))로 채움 → 다 차면 `coarse_done(채운 장수, 띄운 때부터 초)`·`coarse_count`(거친 띠 장수 — 공개 뒤 그대로, 기록용). 간격 1이면 생각하지 않음(ffprobe·기록 줄 없음 — 스펙 §3.1의 '건너뜀 한 줄'은 긴 파일만: 짧은 파일마다 줄이 늘고 기존 시험의 '기록 없음' 단언이 깨지므로). 거친 띠 메모리는 잠깐 최대 1000장 — 16:9 173MB, 정사각 307MB(정확한 띠가 끝나면 놓음). **거친 띠의 실패는 창 없음**: ffprobe 실패·못 찾음·못 띄움, 거친 ffmpeg 종료 코드 ≠ 0·한 장 도중 끊김·**출력 장수 ≠ 목록 K**(j번째 출력 = 목록의 j번째라는 짝을 믿을 수 없음 — 적게 오면 EOF에서, **K를 넘는 장이 오면 그 자리에서 끊어 kill** — EOF까지 디코드하지 않음, 리뷰 L-4)·예상 못 한 예외(트레이스백째) → 거친 띠를 버리고(None) stderr 한 줄 + 사유 전문(명령·종료 코드·stderr — ffprobe 실패도 실패한 명령을 `명령:` 한 줄로 늘 실음: Windows의 `FileNotFoundError` 글에는 경로가 없음) 뒤 정확한 띠를 이어 감(`failed` 없음). 거꾸로 정확한 띠가 실패(`failed`)하면 거친 띠는 그대로 둠(스펙 §3.4는 그 전·버린 뒤·완성 뒤만 None — 이미 채운 장처럼 계속 보이고, 파일을 닫을 때 워커와 함께 놓음). 프로세스 수명은 `_run_pass`(Popen → stderr 비우기 → `_attach` → 읽기 → `_end_reading` → 거두기) 하나로 묶어 ffprobe·거친 ffmpeg에도 `paused`(psutil 정지)·`stop()`(kill)·`_suspendable`·꼬리 함정이 그대로 먹음(지금 프로세스 `_process`를 패스마다 바꿈). **stop 뒤에는 새 프로세스를 띄우지 않음**(리뷰 I-1 — `run`·거친 패스가 띄우기 전에 표지를 봄: start 전 stop이면 0개, 검사와 띄우기 사이에 온 stop이면 `_attach`가 바로 kill), ffprobe 길도 stop을 보면 `_Stopped`로 조용히 빠져나옴(stop이 읽기를 멈춰 받은 반쪽 JSON을 해석해 '예상 못 한 예외'로 거짓 기록하지 않게 — 리뷰 L-2), 트레이스백이 있는 문제는 어느 패스든 정확한 띠와 같은 머리 `멈춘 띠 워커에서 예상 못 한 오류가 났습니다 (stop 뒤라 신호 없음)`로 기록(`_log_after_stop`). `pids`(띄운 차례대로 모든 프로세스)·`coarse_command`·`codec`은 기록·시험용, 생성자의 `ffprobe=`는 시험용(없으면 거친 패스 때 `external_tools.ffprobe_path()`). 실측(이 Mac, 앱 안 idle — 측정 기록 2026-11-11 절, 최종 코드 20ddf7a; Ruling 26은 h264를 바꾸지 않음): FL106(22.6분 H.264 1280×720 32,553장·키프레임 558개) `거친 띠 완성: 558/558장 9.7초`·`띠 완성: 494/494장 28.3초`(load 5.2; 예전 1코어·거친 띠 없음 67.0초), KOTH1410(1080p H.264 35,693장) 거친 띠 12.9초·정확한 띠 37.0초(load 9.4; 헤드리스 근거: 정확한 띠 1코어 82.2초·기본 24.6초, 키프레임 패스 11.7초(1코어)·12.6초(기본 — 파싱 병목이라 스레드 무관)), 4K 334장 `띠 완성 38.9초`(3차 38.3·38.2초와 같음 — 1코어 그대로). 시험 `tests/test_hover_strip_builder.py`
  - `yesoncheck/hover_keyframes.py` (181줄, 2026-11-11): 키프레임 거친 띠의 순수 규칙 — Qt 없음. **헤더** `probe_header(ffprobe, 파일, run=None)` → `StreamHeader(codec, rate_text, rate, start)`(`ffprobe -v error -select_streams V:0 -show_entries stream=codec_name,r_frame_rate,start_time -of json` — 패킷 없이라 파일을 다 읽지 않음; rate는 `0 < r ≤ MAX_FRAME_RATE`(240)일 때의 분수, 아니면 None; start 없으면 0; 영상 트랙 없으면 RuntimeError) → `header_skip_reason`: 코덱이 `ALL_INTRA_CODECS`(prores·dnxhd·mjpeg·rawvideo — `hover_strip`의 상수 하나, 스레드 규칙과 같은 객체)면 `all-intra 코덱 <이름> — …`, rate가 None이면 `가변 프레임 레이트이거나 속도를 알 수 없음 (r_frame_rate …)` — 둘 다 실패가 아니라 건너뜀 사유(리뷰 L-5: 예전에는 패킷 스캔이 파일 전체를 읽은 뒤에야 all-intra를 알았고, VFR은 실패로 기록했음). **키프레임 번호** `scan_keyframes(ffprobe, 파일, header, run=None)` → (정렬한 번호, 버리지 않는 영상 패킷 수): `-show_entries packet=pts_time,flags`(`packets_command` — 파일 전체를 읽음; 캐시에 있으면 FL106 798MB 약 0.5초, NAS 첫 읽기 약 3초) → 둘째 플래그가 **D(버림)인 패킷은 뺌**(편집 목록으로 앞이 잘린 mp4의 `KD_` — `-skip_frame nokey`가 그 장을 내지 않음; 리뷰 L-1, 실측: GOP 12 번호 H.264를 `-ss 1.3 -c copy`로 자르면 K 패킷 중 `KD_` 하나가 출력에 없음) → K 플래그 패킷의 pts를 `round((pts − start) × r)`로 바꿔 정렬하고 `[0, 패킷 수 − 1]`로 자름(`keyframes_from_packets` — B 프레임이면 디코드 순서라 정렬이 필요; 정확도 ±1장이면 충분 — 거친 띠의 어긋남이 GOP/2). 종료 코드 ≠ 0은 RuntimeError(명령·stderr 전문), 키프레임 패킷에 pts가 없으면 지어내지 않고 RuntimeError, 깨진 JSON은 ValueError 그대로, 속도 없는 헤더로 부르면 ValueError(부른 쪽 버그). `run(명령)` → (종료 코드, stdout 바이트, stderr 글) — 워커는 자기 프로세스 수명을 지키는 run을 넘기고 기본은 셸 없는 `subprocess.run`. **판단** `coarse_wanted(전체, 간격, 키프레임 수=None)` → 사유 글|None: 간격 1이면 사유(스캔 전에도), 키프레임 0이면 사유, `K × KEYFRAME_RATIO(4) > 전체`면 사유(all-intra가 아닌 코덱의 촘촘한 GOP), 키프레임 수를 안 주면 간격만 봄. **줄이기** `subsample(frames, 최대)` → `(frames[::m], m)`, `m = ceil(K / 최대)`(`MAX_COARSE` 1000) — 워커가 받은 i번째 장 중 `i % m == 0`만 넣는 규칙과 짝. **저장소** `KeyframeStrip(frames, w, h)`(`hover_strip.ImageRows` + 생성 뒤 바뀌지 않는 튜플 `frames` — 비었거나 정렬이 아니면 ValueError, 같은 번호는 허용) + `nearest(frame)`(bisect — 같은 거리면 앞쪽, 같은 번호가 여럿이면 그 첫 번째). 상수는 부를 때마다 모듈 값으로 읽음. 실측(측정 기록 2026-11-11): FL106의 K 패킷 558개 = `-skip_frame nokey` 출력 558장·순서도 같음(그래도 다르면 워커가 버림). 시험 `tests/test_hover_keyframes.py`
  - `yesoncheck/slider_preview.py` (232줄): 화면 쪽 — 보이기만(어느 프레임인지·띠·디코드는 모름; 값 → (번호 글, 그림|None)은 부른 쪽의 `lookup`). `slider_value_at(slider, x)`: **Qt `QSliderPrivate::pixelPosToRangeValue` 식 그대로**(`initStyleOption` + `subControlRect`의 홈·핸들 → `center = handle.center() − handle.topLeft()`, `pos = x − center.x() − groove.x()`, `span = groove.right() − handle.width() + 1 − groove.x()`, `QStyle.sliderValueFromPosition`) — 이 앱 시트의 핸들 폭 −1(메인)·30(오버레이)을 **보정하지 않음**: 핸들 폭을 0으로 막거나 반을 빼는 '그럴듯한' 식은 900px·N=334에서 900칸 중 162(메인)·333(오버레이)칸이 클릭 착지와 어긋났고 이 식은 0칸(빌더 체크·리뷰 실측 — 호버 번호가 클릭하면 가는 프레임과 같아야 함). 가로 슬라이더 전용. `SliderPreviewPopup`: `Qt.ToolTip | FramelessWindowHint` 최상위 창(`WA_ShowWithoutActivating`·포커스 없음, 인라인 시트만 — 어두운 배경·1px 테두리·흰 22px 굵은 번호; parent가 플레이어 창이면 부모의 테마 시트가 내려오지만 인라인 시트가 이김(배경·테두리·라벨 배경·번호 색·크기·굵기 — 두 테마 시험), 번호의 글꼴 종류만 앱 글꼴(테마 시트의 `font-family` 목록 — 실측 높이 1px 차이). **parent 규칙** `popup_parent(window)`: Qt5 `qtooltip.cpp`와 같은 플랫폼 분기 — Mac·Linux는 창 자신(창과 함께 지워짐 — 종료 때 매달림을 줄임, 가설: 이 Mac 종료 세그폴트 플레이크 18/24 → 7/24), Windows는 그 창이 있는 화면의 desktop screen 위젯(Win32 주석: 위젯을 parent로 쓰면 툴팁이 뜰 때 그 창이 raise됨) — 단 Qt 5의 QWidget은 Desktop 종류 parent를 화면 고르기에만 쓰고 parent를 비우므로 Windows의 팝업은 parent 없는 창(QToolTip의 QTipLabel과 같음 — 실측·시험 고정; 창을 닫을 때 부른 쪽이 지움). 어느 쪽이든 `isWindow()`·`windowType() == Qt.ToolTip` 그대로이고 `place_above`의 `move`는 화면 좌표), 그림 라벨은 계획의 크기로 고정(`set_thumb_size` — 가로↔세로 영상 전환), `show_frame(번호 글, 그림|None)`(None이면 같은 크기의 빈 상자; `(h, w, 3)` uint8 연속이 아니면 **바꾸기 전에** ValueError; 다른 스레드가 쓰는 버퍼의 뷰일 수 있어 QImage를 `.copy()`해 쥠; `adjustSize`로 긴 번호에 맞춤), `place_above(slider, x)`(커서 x에 가로 가운데, 아래 끝은 슬라이더 위 `GAP` 8px — **커서가 있는 화면**(`QGuiApplication.screenAt(커서 자리) or slider.screen()` — 모니터 둘에 앱 창이 걸치면 창이 속한 화면이 커서 쪽이 아닐 수 있음)의 `availableGeometry()` 안으로 밀고 위가 모자라면 슬라이더 아래로). `SliderHoverFilter(slider, lookup, popup, parent)`: `setMouseTracking(True)`(QSlider 기본은 꺼져 있어 버튼 없는 MouseMove가 안 옴 — 드래그 신호는 그대로)·슬라이더와 `slider.window()`에 설치 — Enter·MouseMove → 보이기/갱신(눌려 있으면·lookup이 None이면 숨김; (번호 글, 그림 데이터 주소 `__array_interface__['data'][0]`)가 이 필터가 마지막으로 그린 것과 같고 창이 떠 있으면 `show_frame`(QImage 복사·`adjustSize`)을 건너뛰고 자리만 옮김 — 띠의 `image(i)`는 매번 새 뷰라 객체가 아니라 주소로, 창이 숨어 있었으면 늘 다시 그림(파일을 바꾸면 창을 숨기므로 새 띠가 옛 주소를 물려받아도 옛 그림이 남지 않음)), Leave·MouseButtonPress·Hide·창의 WindowDeactivate → 숨김, 늘 False(클릭·드래그 기본 처리 그대로); 본문 예외는 창을 숨기고 필터마다 **처음 한 번만** `error_window.report_from_handler`(트레이스백 + 오류 창 — PyQt5 가상 함수의 qFatal 회피, 프로젝트 규칙), 그 뒤로는 창 없이 기록(stderr) 한 줄씩(예외 종류·글 — lookup 버그 하나로 마우스가 움직일 때마다 창이 쌓이지 않게, 조용하지도 않게). **부른 쪽이 필터 참조를 쥘 것**(Qt는 설치된 필터를 붙잡아 주지 않음 — parent 없이 변수에도 안 담으면 호버가 오류 없이 죽음), 슬라이더가 창 계층에 들어간 뒤에 만들 것, 창을 지우기 전에 `detach()`(설치한 슬라이더·그때의 창에서 떼고 창 참조를 끊음 — 그 뒤 `eventFilter`는 아무것도 안 하고 False). 시험 `tests/test_slider_preview.py`
- `yesoncheck/main_window_styles.py` (940줄): 어두운·밝은 테마 시트(`DARK_STYLESHEET`·`LIGHT_STYLESHEET`)와 큰 인라인 시트 상수 — 데이터만 있는 잎 모듈
  (한 글자도 바뀌지 않게 `tests/test_stylesheet_freeze.py`가 해시로 지킴)
- `yesoncheck/worker_lifecycle.py` (76줄): 놓아 준 `QThread` 워커를 끝날 때까지 붙잡아 두기 — `release_worker`·`wait_for_released_workers`·`EXIT_WAIT_S`(30초)
- `yesoncheck/player_playback.py` (2,813줄): 비디오 재생, 프레임 탐색 및 FFmpeg 작업 — `_open_movie_capture`는 `os.stat` 확인 뒤·`cv2.VideoCapture` 앞에 `_native_or_pipe_capture`를 끼움: `YESONCHECK_MOVIE_SOURCE=cv2`면 맨 먼저 그대로 파이프 게이트 함수로(그 안에서 probe 없이 `None` — 네이티브 토글도 읽지 않음), `native_wanted()`가 거짓이면(Windows·재생 디코더 ffmpeg·`YESONCHECK_MAC_NATIVE=off`) 예전 파이프 게이트 줄 그대로(`mac_native_source`는 import도 안 함 — 지연 import, `tests/test_native_open_path.py`가 새 프로세스로 고정), 원하면 ffprobe 한 번(`probe_for_open`)으로 네이티브 게이트(아래 'Mac 네이티브 재생') → 양성이면 `open_native_capture`, `NativeCaptureError`(PyObjC 없음 포함)면 트레이스백·기록 줄 `[재생] 네이티브(VideoToolbox): 열지 못해 ffmpeg 파이프로 계속: <이름>`·오류 창 `영상을 열 수 없음(네이티브)` 1회(끝 줄 `NATIVE_ESCAPE_HINT`) 뒤 파이프로, 음성이면 `[재생] 네이티브(VideoToolbox): 아님 — <사유>: <이름>` 뒤 파이프로 — 파이프 게이트는 `maybe_pipe_capture(…, full_cache=True, probe=)`(같은 probe — ffprobe 한 번; 전체 프레임 캐시를 원하는 곳은 여기뿐)(아래 `movie_pipe_source`; 둘 다 음성이면 기존 cv2 줄이 그대로 돎). 네이티브 프레임(`frame_handles.native_surface_of`가 손잡이를 줌)은 `process_frame`·`optimize_for_4k`·드래그 미리보기(`process_frame(…, gpu=False)`)가 변환 없이 그대로 돌려주고 `frame_cache`에 넣지 않음(복사 4K 33MB — 파이썬 쪽 픽셀 접근 0을 `tests/test_native_player_paths.py`가 고정). 재생이 마지막 프레임에 닿거나 read가 끝나면 Play마다 기록 한 줄 `[측정] <N>장 <초>초 (<fps>fps) 네이티브=yes|no 와이프=on|off 표시=gl|pixmap|raster — <파일>`(`measurement_line`·`_measure_tick`·`_print_measurement` — 모든 캡처; N은 Play 뒤 진행한 장 수, 초는 Play 직후부터 마지막 틱의 그리기까지, 도중에 멈추면 줄 없음; 실시간 재생 판정용). `overlay_text`(B 키 — 프레임에 굽는 파일 이름·프레임 번호, 글자는 `overlay_label`)는 `overlay_text_layout.overlay_layout`으로 크기를 프레임에 비례시킴(`overlay_metrics`·`OVERLAY_TEXT_SCALE`, 2026-11-03 — 2026-11-04에 네이티브 아이템 길과 함께 쓰려고 `overlay_text_layout.py`로 옮김, `overlay_metrics`는 옛 import 경로로 다시 내보냄). `update_frame`은 그린 직후 `refresh_frame_annotations_display(redraw=False)`를 불러 같은 프레임을 두 번 그리지 않음 (틱당 `updateFrame` 2→1, 픽셀 동일 — 이 브랜치에서 기존 표시 코드를 바꾼 유일한 곳, 사용자 승인 예외; 드래그 + OCR 검토 창 분기는 앞 그림이 B를 뺀 그림이라 와이프가 켜져 있을 때만 다시 그림; 같은 패턴인 `_overlay_slider_ui_update`는 무변경; tests/test_display_single_draw.py) — 화살표·휠 프레임 이동 모두 오버레이(V 모드) 슬라이더를 함께 갱신(`_update_ui_fast`도 `update_overlay_controls`를 부름 — tests/test_overlay_slider_sync.py) — 전역 단축키(`keyPressEvent`): V(컨트롤 전체 숨김·오버레이), N/ㅜ(가운데 컨트롤 열 숨김 — `toggle_middle_panel`, V·전체화면 복원 뒤에도 유지), P/ㅔ(북마크 관리 창 — `show_bookmarks`). 사이드바 목록이 포커스를 가질 때는 `player_base.eventFilter`가 같은 키(V·N·P)를 받음
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
  - `yesoncheck/sidebar_take_colors.py` (68줄, 2026-11-12): Mov 항목의 테이크·버전별 글자색 규칙과 개수 줄의 같은 색(`count_line_html`) — `take_number`(개수 줄과 같은 규칙)·`take_color(이름, 테마)`(1번·번호 없음은 None = 테마 기본색, 2번부터 `TAKE_COLORS`의 넷을 돌려 씀 — 시퀀스 하늘색·재생 중 빨강·선택 주황을 피하고 목록 바탕과 명암 대비 4.5:1 이상). 칠하는 일은 `sidebar_all.SidebarAllMixin._apply_take_colors`(새 항목만 — 개수 줄과 같은 미룸; 테마를 바꾸면 전부 다시)·`_paint_mov_item`(선택 재생의 되돌리기도 이것). Qt 없음 ('최근 변경 사항' 2026-11-12)
  - `yesoncheck/sidebar_sort.py` (82줄, 2026-11-12): 목록 정렬의 규칙 — 기준 `MODES`(`name` 이름 — 기본·`kind` 종류·`version` 버전·`time` 시간), `group_key(이름, 기준, mtime=None)`(묶음의 정렬 열쇠 — 종류는 없는 것 먼저·그다음 종류 이름순, 버전은 번호 없는 것 먼저·그다음 번호순(TK2와 v02는 같은 묶음 — 테이크 색과 같음), 시간은 이름을 안 보고 고친 시각이 최근일수록 앞·모르면 `UNKNOWN_TIME`(맨 뒤); 종류·버전을 읽는 규칙은 개수 줄의 `sidebar_counts.kind_and_version`), `ordered(항목들, 기준, stem_of, time_of)`(안정 정렬 — 묶음 안에서는 받은 순서, 이름이면 그대로; 시간에 `time_of`가 없으면 ValueError), `button_text`. Qt 없음 ('최근 변경 사항' 2026-11-12)
  - `yesoncheck/sidebar_sorting.py` (361줄, 2026-11-12): `SidebarSortMixin` — 탭 줄의 All 탭 바로 옆 정렬 단추(`self.sidebar_sort_button` — `_init_sidebar_sort`)와 `set_sidebar_sort(기준)`. **단추 자리**: 탭 위젯의 자식으로 탭 막대 바로 오른쪽에 직접 놓음(`_fit_sidebar_sort_button` — 탭 위젯·탭 막대의 크기·자리가 바뀔 때마다 `_ResizeWatcher`가 부름; 탭 막대는 왼쪽 정렬 `TAB_BAR_LEFT_STYLE` — Mac의 기본 가운데 정렬이면 좁은 사이드바에서 All 탭 오른쪽에 자리가 없음), 글은 남은 폭에 들어가는 가장 긴 것(`sidebar_sort.button_texts` — `정렬: 이름 ▾` → `이름 ▾` → `↕`; 폭은 그 글을 단추에 넣어 잼, 기준은 툴팁 첫 줄에 늘 있음). 모서리 위젯(`setCornerWidget`)으로 두지 않음 — Qt가 줄의 오른쪽 끝에 붙이고(넓은 사이드바에서 All 탭과 떨어짐) 단추 폭이 탭 위젯의 최소·바라는 크기에 끼어 사이드바를 좁히다 걸리거나 창의 처음 크기 계산(`test_window_resize`)이 흔들림. 기준 `self.sidebar_sort_mode`(상태는 `VideoPlayerBase`가 만듦)는 창이 떠 있는 동안 유지(저장하지 않음). **Mov 목록은 항목 객체를 그대로 두고 줄만 옮김**(`_reorder_sidebar_items` — 떼었다 다시 넣음; `clear()`는 항목을 지우고 모델을 초기화해 출처·Seq 목록을 잊으므로 쓰지 않음; 고른 것·현재 항목·아이콘·색 유지, 위젯 신호는 막고 모델 신호는 그대로). **이름 순서를 잃지 않는 법**: 이름이 아닌 기준으로 처음 바꿀 때 줄 번호를 항목의 기본 순위(`SIDEBAR_RANK_ROLE`)로 적고, 묶음 안 순서와 '이름'으로 돌아갈 순서가 그 순위(돌아오면 순위를 지움). 정렬해 둔 동안 — 끝에 붙은 새 항목은 순위를 뒤에 매겨 0ms 뒤 정렬(`rowsInserted` → `_schedule_sidebar_sort`), 목록 다시 읽기는 계획을 기본 순위 순서로 세우고(`_sidebar_items_in_default_order`) 바꿀 것이 있을 때만 목록을 잠깐 그 순서로 되돌렸다가(`_sidebar_default_order`) 순위를 다시 매기고 정렬 — `video_list.plan_refresh`·`_apply_sidebar_plan`은 정렬을 모름. 목록을 쓰는 중(`_sidebar_refresh_holds` — 썸네일 반복·우클릭 메뉴가 줄 번호·항목을 쥠)에는 미룸(`SORT_RETRY_MS` 200ms마다 다시 — 기준을 바꿀 때의 Seq 목록 다시 넣기·All 다시 만들기도 함께, `_sidebar_seq_resort_pending`). Seq 목록은 `_set_seq_items`가 넣을 때, All 목록은 `_rebuild_all_list`가 만들 때 같은 기준으로 정렬. **시간**만 디스크를 읽음(`_read_sidebar_times`·`_sidebar_seq_time` — 고를 때와 새 항목만, '최근 변경 사항'). **이름(기본)에서는 아무것도 하지 않음** — 고르지 않으면 예전과 같음. 단추 시트(`SORT_BUTTON_STYLE`)는 색을 정하지 않음(글자색은 테마 시트 — 시트 없이 두면 밝은 테마에서 기본 스타일이 검게 칠함). 기록 `[정렬] 사이드바: 종류`
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
- `yesoncheck/video_widget.py` (1,217줄): 줌, 팬, ROI 선택 기능이 있는 커스텀 비디오 뷰포트 — 주석 모드 동안 오른쪽 위에 '주석 모드' 배지(마우스 투과), 텍스트 입력 요청은 '텍스트' 도구에서만(도형 도구의 드래그 없는 클릭은 무시).
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
  B 키 기하는 굽는 길과 같은 규칙(`overlay_text_layout.overlay_layout`): 기준선 (margin_x, 높이 − margin_y), 상자의 왼쪽·위는 구운 흰 상자와 같은 픽셀, 아래는 max(pad, cv2 꼬리, Qt 꼬리), 오른쪽은 Qt 글자 끝 + pad(글자에 딱 맞춤). 글꼴(`overlay_font`)은 숫자 폭이 모두 같은 `OVERLAY_FONT_FAMILIES`(Helvetica Neue, 없으면 Arial — 2026-11-09: Mac 시스템 글꼴 SF는 숫자 폭이 달라 재생 중 '/전체'가 프레임마다 떨렸음)의 대문자 높이(`QFontMetricsF.capHeight`)를 cv2 글자 높이에 맞추고 넘치면(자리 잡을 글로 잼) 줄임, cv2 획 3px 이상이면 Bold — 모양은 Hershey와 다름(사용자 결정 "같아 보이면 OK"); 대문자 높이를 잴 수 없는 글꼴이면 ValueError(크기를 지어내지 않음).
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
  - `yesoncheck/overlay_text_layout.py` (82줄): B 키 오버레이("File: <이름>, Frame: n/N")의 크기·자리 규칙 — 굽는 길(`player_playback.overlay_text` — cv2)과 네이티브 아이템 길(`video_widget.set_overlay_text`)이 함께 써서 어긋나지 않게: `overlay_metrics(너비, 높이)`(2026-11-03 규칙 그대로 `player_playback`에서 옮김 — `OVERLAY_TEXT_SCALE`·`OverlayMetrics`)와 `overlay_layout(text, 너비, 높이)` → `OverlayLayout`(배율·굵기·여백·cv2 글자 너비/높이/꼬리·들어갈 너비 — 넘치면 줄임). **좁은 프레임에서 줄이는 배율은 '자리 잡을 글'로**(2026-11-09 — 프레임 번호에 따라 글자 크기가 바뀌지 않게; 흰 상자는 글자에 딱 맞춤): `overlay_reserve_text(text, digit)`가 끝의 'Frame: n/N'에서 n을 N의 자릿수(n이 더 길면 그것)만큼 `digit`으로 바꾸고(파일 이름·전체 장 수는 그대로, 번호가 없으면 text 그대로), `digit`은 그리는 글꼴에서 가장 넓은 숫자(`widest_digit` — Hershey는 숫자 폭이 같아 '0', Mac 시스템 글꼴은 '1' 29.6px 대 '0' 40.1px로 다름). Qt 없음
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
    (그래서 슬라이더 드래그도 미리보기 장마다 이동하고, 아래 '알고 둔 한계' ⑨; 새 파일을 열 때 옛 캡처를 되감던 `seek_to_frame(1)`은 2026-11-12에 없앰 — ⑧).
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
    ⑧ **(2026-11-12 해소 — 영상을 바꿀 때 떠나는 캡처를 되감지 않음, '최근 변경 사항')** 예전에는 새 파일을 열면 옛 캡처를 놓기 직전 `stop_video` → `seek_to_frame(1)`이 옛 캡처에서 돌았음 — 링 모드면 ffmpeg를 한 번 더 띄움(~0.5초, cv2는 ~0.33초 — 뒤로 재시작이지만 목표가 0이라 미리 채울 장이 없어 그대로), 전체 모드면 채움이 끝난 뒤엔 0번이 전체 저장소에 있어 재시작 없음(채우기 전이면 링 모드와 같음)
    ⑨ 4K 슬라이더 드래그는 보관본·앞 24장 밖으로 뛰는 미리보기 장마다 재시작(449~634ms)이라 cv2(329~372ms)보다 무거움 — 전체 모드에서 채움이 끝난 뒤에는 파일 어디든 보관본 복사(~3ms)라 즉시, 채우기 전(멈춘 뒤 0.3초부터 4K 약 7초)·링 모드는 그대로(드래그 중에는 read가 촘촘해 채움기도 쉼).
    뒤로 끄는 미리보기 장이 보관본 밖이면 그 재시작에 미리 채우기 8장(≈0.16초)이 더해짐 — 대신 그 뒤 8장 안의 작은 뒤로 이동은 보관본에서 즉시. 앞으로 끄는 쪽은 미리 채우지 않아 그대로
    ⑩ Windows에서 보안 소프트웨어가 127.0.0.1 루프백 TCP를 막으면 ProRes 열기가 실패함(오류 창 끝 줄에 킬 스위치 안내) — 탈출구는 `YESONCHECK_MOVIE_SOURCE=cv2`(Windows 설정법은 README).
    ⑪ 전체 프레임 캐시: 예산은 첫 read에서 한 번만 봄 — 그 뒤 다른 프로세스(ML 배치 등)가 메모리를 먹어도 보관은 판정한 크기(파일 전체)까지 쉬는 동안 채움기가 계속 채움(되돌리는 길은 파일 닫기·킬 스위치). 채움 ffmpeg는 쉬는 동안 디코드하므로(4K는 8코어를 씀) 멈춰 둔 채 다른 무거운 일을 하면 약 7초 동안 CPU를 나눠 씀(쉬는 때는 이 프로세스의 파이프 read 기준이라 다른 창·다른 앱의 재생은 모름 — 창마다 따로 채움).
    **장부는 프로세스마다 하나이고 창 하나 = 프로세스 하나**(Finder에서 여러 파일을 열면 창이 여럿 — 위 '새 창 · 동영상 열기 · 기본 앱')라 20% 예산은 **창(프로세스)마다**임: 창 셋이 저마다 4K A/B를 열면 각자 20%까지 잡을 수 있고
    서로의 몫을 보지 못함 — 창 사이를 막는 것은 판정 때의 ②(사용 가능 메모리)뿐인데 다른 창이 이미 채운 만큼만 잡히고 아직 채우지 않은 몫은 잡히지 않음(README는 창마다 20%라고 안내). 다음 후보: **채우는 도중의 가드** —
    보관을 늘리기 전에 사용 가능 메모리가 `FULL_CACHE_HEADROOM_BYTES` 아래로 내려가면 그 캡처를 링으로 내려앉힘(위의 '첫 read에서 한 번만 봄'과 창 사이 문제를 함께 누그러뜨림).
    예산 확인(`_LEDGER.committed()`)과 장부 올리기(`add`)가 한 원자 동작이 아님 — 지금은 판정하는 캡처가 플레이어 A/B뿐이고 둘 다 GUI 스레드에서 첫 read를 하므로 겹치지 않지만, 다른 스레드에서 opt-in하는 캡처가 생기면 둘이 함께 통과할 수 있음.
    같은 파일을 A·B로 열면 보관을 따로 둬 둘 다 셈(4K 16.6GB — 채움기도 둘). 플레이어 `frame_cache`(기존 드래그 미리보기 캐시)는 전체 모드에서 중복 메모리(후속 후보). fps는 그대로(4K 병목은 ⑦ — 읽는 동안은 링만이라 첫 재생 속도는 링 모드와 같음)이고 채우기 전의 처음 보는 구간은 예전과 같음(재시작).
  - **다음 후보 — Windows offscreen의 텍스트 주석 굽기**: `render_text_patch`가 글자를 Qt 글꼴로 그리는데 Windows offscreen(CI)에서 글리프가 하나도 안 그려져 구운 그림이 원본과 같았음(글꼴 부재로 추정, 기존 동작 — 이 브랜치와 무관) — 글꼴 가드와 시험이 필요함. 이 브랜치의 `test_display_single_draw`는 도형(사각형) 주석으로 우회. **2026-11-12 CI에서 확인한 것**: Windows의 offscreen 플랫폼은 기본으로 글꼴이 없어 글자 폭을 글자마다 12px 상자로 잼(탭 막대 204px — 글자 수 × 12와 맞음), 환경 변수 `QT_QPA_FONTDIR=C:\Windows\Fonts`를 주면 테마 글꼴이 Segoe UI로 풀리고 폭이 실제 글꼴 값이 됨(같은 탭 막대 153px — `tests/sort_button_probe.py`를 자식 프로세스로 돌린 `test_sidebar_sort`의 측정). 그 변수로 글리프 **그리기**까지 되는지(이 후보의 텍스트 굽기)는 아직 안 봄. 시험 프로세스 전체에 주면 Windows의 크기·픽셀 기대가 모두 바뀌므로 필요한 시험만 자식 프로세스로.
  - **다음 후보 — 4K 표시 경로의 나머지**: Mac의 직접 GL 텍스처 스트리밍은 2026-11-02에 들어감(`video_widget.py` 항목 — PBO는 스파이크에서 이득이 없어 안 씀). idle 재측정(2026-11-02 12:21, 외부 ML 배치 없음 — 내부 records `task4-gate.md`): 하니스 틱 GL 55.6ms(QPixmap 74.5)·334장 GL 14.02~14.04초(QPixmap 18.4~19.0, GUI 바쁜 시간 40.3ms/장 = 타이머 41ms 포화) — **설계 게이트 ≤ 35ms 미달 확정, 24fps는 경계(여유 없음)**; 머지·후속은 사용자 결정. 남은 것: 틱 단축 — BGRA 4바이트 업로드(스파이크 −8ms, `frame_a` 계약 변경 필요)·ffmpeg 디코드 스레드 수 제한 실험·틱마다의 라벨·슬라이더 갱신 비용 측정, Windows 기본 GL(ES2/데스크톱 공용 셰이더 경로가 선행 조건)·GPU 와이프. `QPixmap` → `QImage` 직접 그리기는 틱이 약 41ms로 예산(41.7ms)에 걸쳐 확실한 실시간이 안 돼 사용자 결정으로 하지 않음. 근거 스크립트
    (`yc_paint_fmt_exp.py`·`yc_sock_exp.py`·`yc_pipe_read_exp.py`·`yc_microbench.py`)와 하니스(`profile_4k_playback.py`)는 내부(비공개) 저장소의 `docs/superpowers/records/2026-10-29-prores-pipe-design/`, GL 스트리밍 스파이크·게이트 스크립트(`yc_gl_stream_spike.py`·`yc_app_playback_time.py`·`yc_app_pixel_check.py`·`diag_tick_split.py`)는 `records/2026-11-02-gl-stream-design/`.
  - 빌드 앱 `yesoncheck/smoke_test.py`의 'ProRes 파이프 열기' 단계(`prores_pipe_open` — 번들 ffmpeg로 소형 ProRes mov를 만들어 `open_any_capture`로 열고 읽기·탐색, `YESONCHECK_MOVIE_SOURCE`가 auto가 아니면 실패): 빌드 앱의
    `_MEIPASS` ffmpeg와 Windows CREATE_NO_WINDOW 파이프가 실제로 실행되는 유일한 자리. 4K 실물 재생·탐색·와이프·주석은 CI가 못 보므로 눈 확인 몫 — 내부(비공개) 저장소의
    `docs/superpowers/records/2026-10-29-prores-pipe-design/eye-check.md`(전체 프레임 캐시는 `docs/superpowers/records/2026-11-02-gl-stream-design/eye-check.md`의 ②). 시험은 아래 '테스트 전략'.
- `yesoncheck/frame_cache_budget.py` (57줄): 파이프 캡처의 전체 프레임 캐시 예산 — 순수 판단 `full_cache_decision(frame_bytes, count, ram_total, ram_available, committed)` → `CacheDecision(full, reason, total_bytes)`(예산 검사가 사용 가능 메모리
  검사보다 먼저, 둘 다 다른 캡처가 잡은 committed를 뺌), 상수 `FULL_CACHE_RAM_FRACTION`(0.20)·`FULL_CACHE_HEADROOM_BYTES`(2GiB), 기록용 `gb`(십진 GB 소수 한 자리), `memory_snapshot`(psutil `virtual_memory()`의 total·available — 예외는 그대로). psutil은 `requirements-build.txt`에
  직접 고정(7.2.2 — lock에는 이미 간접 의존으로 있음). Qt·캡처 상태 없음 — 쓰는 곳은 위 `movie_pipe_source`의 '전체 프레임 캐시'
- `yesoncheck/video_list.py` (472줄): 사이드바 영상 목록 규칙 (job·폴더 읽기 — 작품마다 영상을 찾는 폴더가 다름: `scan_job` 설명, BB_Animatic은 `job/<씬>/Quicktime`과 job 바로 아래 `Quicktime`, 정렬, 다시 읽기 계획, 없어진 영상 판정 `check_gone`) — Qt 없음
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
- `yesoncheck/user_files.py` (218줄): 사용자 파일(JSON)을 여러 창이 함께 써도 안전하게 — `write_json_atomic`·`write_text_atomic`(글 파일 — 사용법 매뉴얼; 줄 끝을 바꾸지 않음)(같은 폴더의
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
- 사용법 매뉴얼 (2026-11-11 — Help → 사용법(F1)이 여는 것; 사용자 설명은 README '사용법 매뉴얼'). 사용자 요청 셋: "HTML로 깔끔하게"·"업데이트 릴리즈 내용도 같이"·"툰붐 하모니 매뉴얼처럼 스샷 떠서 기능별로" — 예전 사용법은 QTextBrowser 창 하나에 점 목록만 길게 있었고 2026-10 뒤의 기능(이미지 시퀀스·북마크·호버 썸네일·Settings 항목·여러 창·업데이트 등)이 거의 없었음:
  - `yesoncheck/manual_content.py` (663줄): 글 — 쪽(`Page(key, title, group, lead, blocks)`) 15개(`PAGES`: start·shortcuts·playback·view·compare·sidebar·library·sequences·annotations·ocr·settings·windows·update·prores·trouble)와 목차 묶음 `GROUPS`. 블록은 튜플(`h`·`p`·`fig`·`keys`·`table`·`steps`·`list`·`note`/`tip`/`warn`), 글 안의 표시는 `**굵게**`·`` `코드` ``·`{키}`·`[[쪽/닻|글]]`(모듈 설명). Qt 없음·데이터만. **사실만 적음** — 단추·메뉴 이름은 화면 글자 그대로, 동작은 코드에서 확인한 것만(쓰면서 확인한 것: FPS 칸은 연 영상의 속도를 보이기만 하고 읽는 코드가 없음 → '속도를 바꾼다'고 적지 않음; 와이프에서 ←→·휠은 A만 움직임(`_seek_direct_fast`가 `cap_b`를 안 건드림) → 적음; 검토 창의 다시 실행은 `QKeySequence.Redo`의 첫 키라 Mac ⌘⇧Z·Windows Ctrl+Y(Qt 문서의 플랫폼 표 — Windows 실기 미확인, 단추 툴팁은 Ctrl/Cmd+Shift+Z라고 적혀 있음)). 기능을 더하거나 바꾸면 그 쪽의 글·그림을 함께 고침. 단축키 쪽이 코드가 받는 키를 빠뜨리지 않았는지는 시험이 목록으로 지킴
  - `yesoncheck/release_notes.py` (351줄): 버전별 바뀐 점 `RELEASES`(새 버전이 위 — `Release(version, date, summary, groups)`, 날짜는 배포한 날의 한국 날짜·아직 배포 전인 맨 위 항목만 None) — 매뉴얼의 '업데이트 내역' 쪽과 **배포 노트의 한 출처**: `notes_text(버전)`·`python -m yesoncheck.release_notes X.Y.Z`가 `tools/release.py prepare --notes-file`에 넘길 글을 냄(없는 버전은 LookupError — 지어내지 않음; 절차는 BUILD.md 7-1의 0번). 1.8.1까지는 그때 낸 노트를 옮김(요약 줄이 없던 1.1.0·1.1.1·1.2.0·1.2.1은 요약을 붙이고 '사용법·README 참고' 안내 줄은 뺌). 저장소가 공개라 경로·내부 정보를 넣지 않음(시험이 `/Volumes/` 등을 막음). Qt 없음
  - `yesoncheck/manual_html.py` (484줄): `build(load_image, version_text=None, current_version=None)` → **HTML 한 파일**(CSS·스크립트·그림(base64) 모두 안에 — 바깥 주소를 부르지 않아 인터넷 없이, 파일 하나만 복사해도 열림). 왼쪽 목차(묶음마다)·쪽마다 한 화면(주소 `#쪽`·`#쪽--닻` = 그 요소의 id — `target()`; 스크립트가 꺼져 있어도 그 자리로 감. 글에서 가리킬 때는 `[[쪽/닻|글]]`)·찾기(낱말이 모두 든 쪽만 목차에)·밝게/어둡게(기본은 `prefers-color-scheme`, 단추는 `localStorage`)·그림 누르면 크게·앞/뒤 쪽 링크·인쇄(모든 쪽). 스크립트가 꺼져 있으면 모든 쪽이 이어서 보임. 그림은 PNG 머리에서 크기를 읽어 `IMAGE_SCALE`(2 — 찍은 배율)로 나눈 크기로 보이고, 폭 `NARROW_IMAGE`(430) 이하면 설명을 옆에(`fig beside`) 아니면 아래 두 단(`fig below`) — 클래스 이름을 `side`로 지었다가 목차(`.side` — fixed)와 겹쳐 그림이 목차 자리에 붙었음(헤드리스 크롬 렌더로 잡음). **만들 때 틀리면 ValueError**: 모르는 쪽·닻을 가리키는 링크, 모르는 블록, 겹치는 쪽 이름·닻, `GROUPS`에 없는 묶음, PNG가 아닌 그림, 짝이 안 맞는 `**`·`` ` ``, 빈 키(`{Ctrl+}`); 그림이 없으면 `load_image`의 예외 그대로. **글 안의 표시는 원문에서 토큰으로 나눠 조각마다 escape**(`inline` — 리뷰에서 잡음: escape한 글에 정규식을 걸면 `{<}`가 두 번 escape되고 코드 안의 `**`가 굵게로 바뀌어 태그가 엇갈렸음): 코드 안은 글자 그대로, 굵게 안은 다시 나눔, 끝의 `+`는 더하기 키(`{Ctrl++}`). 그림 `alt`는 표시를 벗긴 평문(`text_only`). 스크립트: 주소를 `--`로 나눠 쪽·절을 고르고(모르는 쪽·깨진 퍼센트 인코딩은 첫 쪽), 지금 주소와 같은 링크를 다시 눌러도 그 자리로 감 — 동작은 헤드리스 크롬 `--dump-dom`에 `scrollY`를 적는 조각을 붙여 확인(스크롤된 화면은 `--screenshot`이 빈 그림을 냄). '업데이트 내역'은 `release_notes`에서(글 안의 `{}`를 키로 바꾸지 않음), `current_version`이 목록에 있으면 그 버전에 `지금 버전` 표시. `image_names()` = 글이 쓰는 그림 이름(spec·시험·smoke가 함께 씀). Qt 없음
  - `yesoncheck/manual_open.py` (79줄): `open_manual()` = `write()`(HTML을 사용자 폴더 `YesonCheck_manual.html`에 — Mac `~/Library/Caches/YesonCheck/manual`, Windows `%LOCALAPPDATA%\YesonCheck\manual`; `user_files.write_text_atomic`(2026-11-11에 더함 — `write_json_atomic`과 같은 길 `_write_atomic`: 같은 폴더의 임시 파일 + 바꿔 끼움, **Windows는 대상이 열려 있으면 0.1초 간격 20번 다시 시도** — 브라우저·백신이 앞서 쓴 매뉴얼을 잠깐 잡고 있을 때(리뷰 I-1); 줄 끝은 글 그대로), 실패하면 임시 파일을 지우고 예외 그대로) → `open_file()`(Mac `/usr/bin/open <파일>`을 `OPEN_TIMEOUT_S` 30초까지 기다려 0이 아니면 명령·출력이 든 RuntimeError, Windows `os.startfile` — OSError 그대로). 앱 묶음 안에는 쓰지 않음(서명한 Mac 앱·Program Files), 열 때마다 새로 써서 업데이트 뒤에도 지금 버전의 글. 그림 폴더 `images_dir()`: 빌드 앱 `sys._MEIPASS/manual_images`(spec의 `manual_datas`), 소스 `yesoncheck/manual_images`. `build()`는 배포한 빌드(`build_info`의 `is_release`)일 때만 `current_version`을 넘김(시험 빌드·소스 실행은 표시 없음). 웹 보고서(`web_info.open_web_report`)처럼 `webbrowser` → 시스템 명령으로 조용히 넘어가는 두 단계는 쓰지 않음(실패 사유가 그대로 올라오게 한 길). 실패는 `player_base.show_help`가 `error_window.show_unexpected`로(기록 머리 `[사용법]`, 창 글 `OPEN_FAILED_TEXT` + 트레이스백), 성공은 기록 한 줄 `[사용법] 매뉴얼을 엶: <경로>`. Qt 없음
  - `yesoncheck/manual_images/` (PNG 22장, 약 3.2MB): 매뉴얼의 화면 그림 — **`tools/make_manual_screenshots.py`가 만듦, 손으로 고치지 않음**. 빌드는 spec이 `manual_html.image_names()`의 그림을 앱의 `manual_images/`에 넣고(하나라도 없으면 SystemExit), 빌드한 앱의 smoke `사용법 매뉴얼` 단계(`smoke_test.manual_written` — 매뉴얼을 smoke 출력 폴더에 써 봄, 브라우저는 안 엶)가 묶음에 다 들어 있는지 확인
  - `tools/make_manual_screenshots.py` (975줄)·`tools/manual_media.py` (208줄): 그림 찍기(개발 도구 — 앱에 안 들어감). `~/coding/p310_tf/bin/python tools/make_manual_screenshots.py [--shot 이름 …]` — 진짜 `VideoPlayer`를 화면 없이(offscreen, `QT_SCALE_FACTOR=2`) 띄워 샷마다 자식 프로세스 하나로 상태를 만들고 `grab()`. **그림에 실제 작품이 들어가지 않게**(사용자 지시 2026-11-11 "예손 작품 이미지가 들어가면 안 돼", 저장소 공개): 격리 환경은 `ci/screenshot_check.py`의 것을 그대로(`child_environment` — HOME·공유 설정·창 기록을 샷마다 임시 폴더로: 북마크·작품 목록·NAS를 읽지 않음), 영상은 `manual_media`가 cv2로 직접 그린 장면 다섯(언덕·얼굴·도시·자동차·나무)의 스케치판(TK1)·채색판(TK2)·이미지 시퀀스·애니매틱(슬레이트 글자 `SEQ 01A_S01 - PANEL 1`은 OCR ROI 설명용), 파일 이름도 지어낸 것(`EP101_SC001_TK1.mov`), 창에 보이는 경로는 링크 `/tmp/MyShow`로 엶(임시 폴더 이름이 그림에 안 보이게 — 이미 있고 링크가 아니면 멈춤). 번호 표지는 위젯 자리에서 계산해 그림(`Callout(번호, 사각형, anchor, 테두리)` — anchor `g`는 왼쪽에 붙인 여백에 표지 + 위젯까지 선, `lo`·`ro`는 바깥) — **번호의 뜻은 `manual_content`의 그림 설명과 짝**. 창 밖에 뜨는 것(우클릭 메뉴·Settings/Help 메뉴·호버 창·북마크 창·미디어 정보 창)은 따로 찍어 창 그림에 얹음(`capture_menu`·`capture_dialog`·`paste`, 커서는 그려 넣음). 알고 둔 것: 화면 없는 화면은 800×600이라 호버 창이 그 안으로 밀려 뜸 → 진짜 화면에서의 자리(커서 위 가운데·슬라이더 위 8px)에 얹음; 주석 칸은 가운데 열 기본 폭(220)에서 오른쪽이 잘려 보여(기존 화면의 모양 — 이 변경과 무관, 고칠 후보) 주석 샷은 스플리터로 300까지 넓히고 창 높이 1260으로 찍음; Settings 메뉴 그림은 이 도구를 돌린 OS(Mac)의 것이라 Windows 전용 항목(화면 그리기·공유 설정 폴더 변경)은 글로만. 화면(단추·메뉴·모양)을 바꾸면 다시 돌려 그림을 새로 넣음. 샷 이름 = 그림 이름(시험이 매뉴얼이 쓰는 그림과 같은지 지킴)
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

**PlayerSidebarMixin** (`player_sidebar.py`, 부모 `SidebarBookmarksMixin`·`SidebarPlaylistMixin`·`SidebarConfigPathsMixin`·`SidebarRefreshMixin`·`SidebarSequencesMixin`·`SidebarAllMixin`·`SidebarSortMixin`·`SidebarOpenWithMixin`·`SidebarThumbnailsMixin`):
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
- 색 변환(BGR → RGB)은 CPU — Settings의 GPU Acceleration(CUDA/OpenCL)·4K 성능 모드는 2026-11-12에 뺌('최근 변경 사항'): 고른 값이 적용된 적이 없었고 OpenCL 변환은 CPU보다 느림
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

`tests/`에 시험 파일 136개 (수집 3,433개 — 2026-11-12 전체 실행의 통과 + 건너뜀 + 실패). `python -m pytest tests -q`로 돌리며(약 20분), 이 Mac의 소스 실행(`p310_tf` — Mac lock대로 PyObjC 포함)에서 3,386개가 통과(2026-11-12 전체 실행 기준 — 수집 3,433개 = 통과 3,386 + 건너뜀 46 + 아래 GIL 부하 시험 하나가 실패; 전체 실행에서 아래 플레이크 둘이 실패할 수 있음 — GIL 부하 시험은 따로 돌리면 대체로 통과, 종료 시험은 따로 돌려도 간헐 실패)하고 46개는 건너뜀 —
다른 OS 전용 시험, CI의 설치 파일 단계에서만 도는 시험이 건너뜀. PyObjC가 있어야 도는 네이티브 시험(`test_mac_native_source` 모듈과 진짜 네이티브 디코드 하나)은 Mac lock을 설치한 환경(이 Mac의 `p310_tf`·두 Mac CI job)에서 돌고 Windows CI에서만 건너뜀 (2026-11-11 기준; 부하 시험 `test_movie_pipe_transport::test_reader_keeps_up_while_main_thread_holds_gil`은 이 Mac이 바쁠 때 실패할 수 있음 — 따로 돌리면 통과; `test_fast_startup`의 종료 플레이크 1건(`test_app_exits_cleanly_while_shared_config_load_runs`, 자식 종료 코드 −11)은 러너 상태에 따라 간헐 실패 — main에서도 같은 빈도, 따로 돌려도 간헐 실패(2026-11-11 이 Mac에서 따로 되풀이: main 5/8·사용법 매뉴얼 브랜치 4/8 실패 — 앱을 띄워 둔 채라 평소보다 잦았음); CI의 Apple Silicon 러너에서 시간 기반 시험 `test_path_map_setup::test_probe_on_wait_is_called_and_can_cancel`이 한 번 실패(2026-11-12 — 0.45초 동안 약 0.1초마다 불리는 콜백이 3번 이상이어야 하는데 2번; 그 작업만 다시 돌림)). **새 worktree에서 돌릴 때**: `vendor/ffmpeg/<arch>/`(받아 두는 파일 — git이 무시)가 따라오지 않아 `test_check_frozen_imports`의 둘과 `test_pipe_spike::test_boundary_clips_have_their_traits`가 실패함 — 메인 체크아웃의 폴더를 링크하거나 `./fetch_ffmpeg.sh`(2026-11-12에 겪음). Qt는 화면 없이(`QT_QPA_PLATFORM=offscreen`), ffmpeg는 저장소의
정적 빌드(`vendor/ffmpeg/`)를 씀 (`tests/conftest.py`). 시험을 건너뛰거나 지워서 통과시키지 말 것.

시험 구성 (파일 이름 기준):
- **업데이트**: `test_updates`·`test_update_install`·`test_update_flow`·`test_update_ui`·`test_update_helper_mac`·`test_update_helper_windows`·`test_update_e2e`
- **새 창·기본 앱·창 사이 연결**: `test_new_window`·`test_mac_app_events`·`test_default_app`·`test_file_associations`·`test_launch_args`·`test_instances`·
  `test_instance_link`·`test_error_window`·`test_app_logging`
- **경로·공유 설정·작품**: `test_paths`·`test_paths_windows`·`test_mac_mounts`·`test_shared_config`·`test_path_map_setup`·`test_path_map_setup_dialog`·
  `test_path_map_auto_ui`·`test_stored_paths`·`test_work_paths_ui`·`test_work_season_job`
- **사이드바·썸네일·북마크**: `test_sidebar_refresh`·`test_video_list`·`test_thumbnails`·`test_bookmarks`·`test_sidebar_all_tab`·`test_sidebar_sort`(목록 정렬 — 규칙: 이름은 그대로·종류/버전 묶음과 묶음 안 순서·번호순·개수 줄과 같은 읽기; 창: 단추가 탭 줄의 All 탭 바로 옆(처음 켠 폭·가장 좁은·중간·넓은 사이드바 — 글이 `↕`·`이름 ▾`·`정렬: 이름 ▾`로 맞춰지고 세 탭이 다 보이며 단추가 줄 안에 온전히, 넓혔다 좁혀도; 폭은 플랫폼마다 달라 잰 값으로 정하고 처음 켠 폭의 실측을 통과해도 기록에 `[정렬 단추 측정 — <플랫폼>]`으로 남김 — `capsys.disabled()` 안에서 찍음: `sys.__stderr__`에 쓰면 pytest가 fd 2까지 잡아 통과한 시험의 글은 CI 기록에 나오지 않았음; **진짜 글꼴로 잰 탭 줄** — 도우미 `tests/sort_button_probe.py`(시험 아님)를 자식 프로세스로 돌려 처음 켠 폭·가장 좁은 폭에서 세 탭이 다 보이고·단추가 줄 안·**All 탭의 글자를 가리지 않음**(`label_gap ≥ 0`)을 단언, Windows는 자식에 `QT_QPA_FONTDIR`로 Windows 글꼴 폴더를 주고 글꼴이 테마 시트의 것(Segoe UI·Malgun Gothic·Arial)으로 풀렸는지도 봄 — Windows CI의 시험 프로세스는 글꼴이 없어 글자마다 12px로 재므로, 잰 값은 `[정렬 단추 측정(진짜 글꼴) — <플랫폼>]` JSON으로 기록에)·기본은 목록 그대로·종류/버전/이름으로 되돌리기·항목 객체와 고른 것·현재 항목 유지·영상을 열거나 모델을 초기화하지 않음·끝에 붙은 새 영상과 다시 읽기(새·없어진 영상)가 묶음 자리로·바뀐 것 없으면 목록 그대로·목록을 비우고 새로 불러와도 유지·쓰는 중에는 미룸·테이크 색과 아이콘이 따라감·선택 재생은 보이는 차례·Seq/All 탭·시간: 최근에 고친 것부터(`os.utime`으로 시각을 정한 빈 파일)·다시 고를 때만 다시 읽음·못 읽은 것은 맨 뒤 + 기록·새 영상은 그것만 읽어 제자리에·쓰는 중에는 디스크도 안 읽음·시퀀스는 첫 프레임의 시각, '최근 변경 사항' 2026-11-12)·`test_sidebar_take_colors`(테이크·버전별 글자색 — 규칙·색의 hue 거리와 명암 대비·목록/테마/All 탭/선택 재생·개수 줄의 색, '최근 변경 사항' 2026-11-12)·`test_sidebar_counts`(개수 줄 — 글 규칙, 탭을 따름, 목록 변화·비우기, All 목록 다시 만들기 전에도 원본에서 셈)·`test_open_with`(명령 — QuickTime 앱 ID·Mac `open -a`·Windows 인자 그대로·명령 줄 한도, 등록한 앱 목록 — 다른 키 보존·다른 창이 더한 앱 보존·나쁜 값은 덮지 않고 UserFileError·앱 아닌 것 거부, Mac `open` 실패·멈춤, Windows 앱 폴더 cwd·빌드 앱의 환경 정리(`_MEIPASS` 아래 PATH 조각·변수)·DLL 검색 경로를 띄우기 전 값으로 되돌리기(띄우기 실패해도)·풀지 못하면 띄우지 않음·띄운 뒤 되돌리기 실패는 `DllDirectoryRestoreError` — 가짜 popen·DLL 검색 경로, 진짜 kernel32는 Windows에서만)·`test_sidebar_open_with`(메뉴 모양 Mac/Windows·Mov/Seq/All, 넘기는 파일 — 목록 순서·고른 것 밖에서 연 줄·시퀀스 첫 프레임(대소문자를 가리는 NFS의 `.TGA` — `os.stat`을 가리게 바꿔서, 첫 프레임이 없어지면 알림)·All 섞인 선택의 정확한 차례, DLL 되돌리기 실패 창, 등록·취소·없어진 앱·지우기, 띄우기 실패 창·없는 파일·20개 넘으면 물음·깨진 설정 파일 — 진짜 앱은 띄우지 않음)
- **워커·OCR·내보내기**: `test_workers_split`·`test_workers_transnetv2_guard`·`test_ocr_worker_lifetime`·`test_animatic2_availability`·`test_transnetv2_detect`·
  `test_runtime`·`test_export`·`test_unsaved_ocr_flag`·`test_review_sync`
- **창 모양**: `test_stylesheet_freeze`(테마 시트를 해시로 고정)·`test_theme_geometry`(테마를 바꾸면 색만 바뀜 — 두 시트의 색 아닌 속성이 같음·보이는 위젯의 자리·크기·줄 높이·스크롤바·글꼴이 그대로, '최근 변경 사항' 2026-11-12)·`test_light_theme`(밝은 테마에서 창이 바탕 #fafafa를 실제로 칠함 — 투명한 그림에 그려 봄, 접는 상자 머리·OCR 라벨이 테마를 따름, 어두운 테마 색은 그대로, '최근 변경 사항' 2026-11-12)·`test_settings_menu`(Settings에 GPU Acceleration·4K 성능 모드가 없음·그 처리기·콤보 상자가 남지 않음·드래그 미리보기 값과 CPU 색 변환은 예전 그대로·**VideoPlayer를 이루는 클래스끼리 이름을 말없이 가리지 않음** — `super()`로 잇는 확장만 허용, '최근 변경 사항' 2026-11-12)·`test_overlay_box_steady`(B 키가 프레임마다 떨리지 않음 — 글자 크기는 번호와 무관, 상자는 글자에 딱 맞고 같은 자릿수 안에서 제자리, 아이템 글꼴은 숫자 폭이 같음 — 두 길·좁은 프레임, '최근 변경 사항' 2026-11-09)·`test_overlay_text_size`(B 키 오버레이 글자가 프레임 높이에 비례 — 1080p 1.5배·4K 2배 픽셀)·`test_playback_fps_label`(재생 FPS 라벨의 실제 fps — 진행한 프레임 세기·재생 중에만·첫 틱 제외·죽은 캡처·NaN·넉넉한 창에서 다 보임)·`test_scrollbar_style`·`test_slider_click`·`test_window_resize`·`test_high_dpi`·`test_force_focus`·`test_middle_panel_toggle`·`test_gl_viewport`(Mac GL 뷰포트 — 선택 규칙·GL 적용 시 보존 설정·테마 배경)·`test_overlay_slider_sync`(화살표 프레임 이동의 오버레이 슬라이더 동기화·대체 탐색 경로 한 칸 어긋남)·`test_windows_display`(Windows 화면 그리기 메뉴·GL 확인·[측정]의 끊김)·`test_playback_clock`·`test_playback_timer`(재생 속도 — 시각표 계산, 진짜 타이머로 빠르지 않음·모든 프레임 차례로·늦어도 건너뛰지 않음·반복 재생)·`test_switch_without_rewind`(영상을 바꿀 때 떠나는 캡처를 건드리지 않음 — read·set 횟수, 와이프의 B·Stop 단추는 그대로, '최근 변경 사항' 2026-11-12)·`test_drag_release_seek`(긴 영상 멈춤 회귀 — 놓을 때 읽는 장수를 read 수로 고정, 캐시에 맞는 드래그는 read·set 0)·`test_drag_flag_release`(메인 슬라이더를 놓으면 `is_dragging` 해제 — 진짜 마우스 드래그, 놓은 뒤 그림에 와이프 B가 빠지지 않음, 캐시 미적중 드래그를 놓으면 B를 A와 같은 장에 다시 맞춤, 와이프면 정밀 이동 허용 오차 0·B가 이미 그 자리면 다시 안 읽음, '최근 변경 사항' 2026-11-10)
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
- **사용법 매뉴얼**(2026-11-11 — Qt 없는 모듈이라 대부분 창 없이 돎; 그림은 시험용 작은 PNG를 만들어 넣고, 저장소의 진짜 그림은 따로 봄)
  - `test_manual_html`: 진짜 글 전체가 만들어짐(쪽·목차·버전마다 id), 모든 링크(`#쪽`·`#쪽/닻`)가 실제 id를 가리킴, 바깥 주소 없음(그림은 `data:`), **단축키 쪽이 코드가 받는 키를 빠뜨리지 않음**(키 목록으로 고정 — 단축키를 더하면 여기에도), 묶음이 `GROUPS` 안, `지금 버전` 표시는 목록에 있는 버전에만, 버전 글 이스케이프; 저장소 그림 — 글이 쓰는 그림 = 폴더의 PNG(남는 것·없는 것 없음), 2배 배율 크기, 진짜 그림으로 만들면 base64가 들어감, **그림 찍는 도구의 샷 이름 = 매뉴얼의 그림 이름**·배율 같음, 설명 번호 9개 이하; 표시·블록 — 굵게·코드·키·`<`/`&` 이스케이프, 키 모양(`Shift+F`·`+` 하나·`F (ㄹ)`·`\`), 표·차례 목록·알림 상자, 절 id와 절 셋부터의 칩, 쪽 사이 링크; 틀린 것은 ValueError(모르는 쪽·닻·블록, 겹치는 닻·쪽 이름, 없는 묶음, 업데이트 내역 쪽 이름과 겹침, PNG 아님), 없는 그림은 FileNotFoundError 그대로; 그림 폭에 따른 배치(`beside`/`below`)·보일 크기; 업데이트 내역은 `{}`를 키로 바꾸지 않음
  - `test_manual_open`: 그림 폴더(소스·빌드 앱), 그림 읽기·없으면 FileNotFoundError, 쓰는 자리(Mac·Windows·그 밖), 쓰기 — 파일 하나·임시 파일 안 남음·덮어씀·`os.replace` 실패면 앞 파일 그대로 + 예외·그림이 빠졌으면 빈 매뉴얼을 쓰지 않음, 배포 빌드일 때만 `current_version`, 열기 — Mac `open` 인자·실패 글(명령·출력), Windows `os.startfile`·그 OSError 그대로, `open_manual` 차례; 창 — **`show_help`는 MRO에 `VideoPlayerBase` 하나뿐**(`player_playback`에 다시 생기면 실패), 성공 기록 줄, 실패는 오류 창(트레이스백)·밖으로 예외 없음, Help 메뉴(F1)·단추 연결(글자로); 빌드 — smoke 단계가 그림 전부로 매뉴얼을 씀·묶음에 그림이 없으면 실패·`run`이 그 단계를 부름, spec이 `image_names()`의 그림을 `manual_images`로 넣음(글자로)
  - `test_release_notes`: 새 버전이 위·겹침 없음(번호로 비교 — `1.10.0` > `1.9.0`), 버전마다 요약·항목, 날짜 없는 것은 맨 위 하나뿐, 경로(`/Volumes/` 등) 없음, 노트 글 모양(요약·빈 줄·묶음·`- 항목`), 없는 버전은 LookupError, `python -m yesoncheck.release_notes` 출력 = `notes_text`·없는 버전은 종료 코드 ≠ 0
- **슬라이더 호버 썸네일**(2026-11-10 — 실제 번들 ffmpeg·번호 클립 `prores_clips.make_numbered_clip` 320×180이라 띠 그림도 축소 없이 번호가 그대로 읽힘; 진짜 워커를 만든 시험은 끝에서 스레드·ffmpeg 프로세스가 남지 않았는지 늘 확인 — 2026-11-11부터는 워커가 띄운 프로세스 전부(`pids` — ffprobe·거친 ffmpeg까지). 거친 띠(2026-11-11)는 GOP 12의 번호 H.264(`prores_clips.make_numbered_h264` — libx264, 키프레임이 정확히 12장마다·B 프레임 그대로, 그림 번호는 `frame_number`)에 `MAX_THUMBS`를 줄여 간격 > 1로 봄)
  - `test_hover_strip`(Qt 없음): 계획 — 500장 이하 프레임마다·501장 간격 2·14,400장 간격 29·497장·한 장, 호출 때 `MAX_THUMBS`를 읽음, 원본 크기를 듦, 스레드 규칙(Ruling 25·26) — 720p 이하는 코덱과 상관없이(hevc·prores도) `(None, None)`, 1080p 이하 h264(허용 목록 `LONG_GOP_FULL_THREADS_CODECS`)도 `(None, None)`, 720p보다 큰 목록 밖 코덱(hevc·vp9·av1·목록 밖 all-intra cfhd·prores·dnxhd)·코덱 모름·1080p보다 큼(한 화소 줄이라도 — 4K h264·prores)은 부른 쪽 값, 두 문턱 모두 호출 때 읽음, `ALL_INTRA_CODECS`는 `hover_keyframes`와 같은 객체, 320×320 상자 안 짝수 크기(16:9·4:3·세로 9:16·정사각·아주 좁은 비율)·나쁜 입력 ValueError, 저장소 — put 뒤에만 has/image·memoryview 복사·길이 검사·메모리 상한, 크기 상한 — 경계·GB 글(구멍 파일 없이 monkeypatch), 설정 — 왕복·다른 키 보존·불리언 아님 ValueError·저장 TypeError·깨진 파일 `UserFileError`·기본 경로·플랫폼 분기·캐시
  - `test_hover_strip_builder`: 간격 1 순서대로 모든 장·간격 step 샘플·명령 모양, `paused` → 더 채우지 않고 프로세스가 정지 상태(psutil)·재개하면 끝까지, 띄우기 전 `paused`면 띄운 직후 정지, stop — 프로세스·스레드 끝(정지 중·읽기에서 막힌 중에도), 정지 중 EOF는 재개 뒤 거둠(꼬리 함정), stop 뒤 예상 못 한 예외는 신호 없이 기록, 없는 파일 `failed`(stderr·명령), **잘린 파일**(헤더 48장·꼬리 잘림 — 종료 코드 0 + stderr 오류 줄)은 `done`(채운 장수·번호 맞음) + 경고 기록, 계획보다 적으면 `done`·많으면 버림 + 기록, mp4v mp4·H.264 mp4(`conftest.make_video` — libx264), 정지 실패(psutil 오류·OSError)는 기록 + 읽기만 멈춤, 같은 `paused` 값은 잠금도 안 잡음, 두 스레드 옵션(`-filter_threads`·`-threads`)은 상수를 따름(4K 원본 — `test_command_shape`도 4K 원본으로 예전 명령 글자 그대로, 1080p는 코덱을 모르거나 prores면 같은 명령·h264면 옵션 없음; 2026-11-11에 원본 크기를 넣어 고침), 720p 이하 원본은 코덱과 상관없이 두 옵션이 없음(나머지는 4K 명령과 같음), 워커가 헤더의 코덱으로 명령을 정함(1080p로 계획한 긴 h264는 두 명령 모두 옵션 없음·긴 ProRes·짧은 파일·헤더 실패는 1코어); **거친 패스**(2026-11-11): 명령 모양(`-skip_frame nokey` 자리·select 없음·스레드 규칙), 거친 띠가 먼저 다 차고(`coarse_done` 순간 정확한 띠 0장 — 직접 연결로 그 순간을 적음) 그림 번호 = 키프레임 번호(GOP 12) → 정확한 띠 → `done` 순간 `coarse_strip` None, 키프레임이 `MAX_COARSE`를 넘으면 m장마다(select 없이 — 그림 번호로 짝 확인), 소리 트랙이 있는 H.264(`make_video`의 `video_args` — 영상 패킷만 셈), 편집 목록으로 앞이 잘린 H.264(`-ss 1.3 -c copy` — `KD_`를 빼 목록 14장 = 출력 = 채움, 그림 번호 − 32 = 목록 번호), all-intra ProRes는 헤더만 읽고 'all-intra 코덱 prores' 건너뜀(패킷 스캔 없음)·촘촘한 키프레임(GOP 2)은 스캔 뒤 'K × 4 > 전체' 건너뜀·가변 속도 헤더는 '가변 프레임' 건너뜀(stderr 없음), 간격 1은 ffprobe도 기록도 없음, ffprobe 실패(실행 파일 없음·0이 아닌 코드·못 찾음)·장수 불일치(목록이 하나 많음 — EOF에서, 하나 적음·2장뿐 — 넘는 장에서 끊어 kill)·거친 ffmpeg 종료 코드 ≠ 0·예상 못 한 예외는 stderr 한 줄 + 사유 + 정확한 띠 완성(`failed` 없음), 거친 패스 도중 멈춤(evidence `status` — Windows 건너뜀·`drain` — 모든 OS)·재개, 스캔 도중(아무것도 안 보내는 TCP 입력의 ffprobe) 띄운 직후 정지·stop(그 뒤 프로세스 없음), 거친 패스 도중 stop은 거친 띠를 놓고 정확한 ffmpeg를 띄우지 않음, start 전 stop은 프로세스 0개, 패킷 ffprobe가 끝나는 순간의 stop은 반쪽 JSON을 조용히·트레이스백은 '멈춘 띠 워커' 머리로; 기존 `test_stop_kills_process_and_thread`는 '띄웠다면 거둠'으로 고침(stop이 먼저면 아예 안 띄움); 도중 멈춤 시험은 `evidence` 매개변수 — `status`(psutil 상태, **Windows는 skip**: 파이프 쓰기에서 막힌 스레드가 있으면 정지돼 있어도 running — CI run 42768144735)·`drain`(파이프를 비워 한 장 미만 + 비우는 도우미가 read1에서 막혀 살아 있음 — 모든 OS, Windows는 이것으로 확인)
  - `test_hover_keyframes`(Qt 없음, 2026-11-11): 헤더(가짜 run — 명령 모양·분수 속도·start 없음/N/A, 0/0·없음·90000/1·241/1은 rate None → '가변 프레임' 사유, 영상 트랙 없음 RuntimeError, all-intra 네 코덱 → 'all-intra 코덱' 사유·h264는 없음, 0이 아닌 종료 코드 RuntimeError), 패킷 JSON 해석(K 플래그만·디코드 순서 정렬·버림(D) 패킷과 그 수 제외·start 보정·정확한 분수 r(24000/1001)·[0, 패킷 수 − 1] 자름·pts 없음 RuntimeError·속도 없는 헤더 ValueError), 진짜 ffprobe로 GOP 12 번호 H.264·편집 목록으로 자른 클립(`([4, 16], 28)`)·ProRes 헤더, 기본 run은 셸 없음·stdin 없음, `coarse_wanted` 사유(간격 1·K × 4 경계·촘촘한 GOP·키프레임 없음·스캔 전), `subsample`(m·목록 규칙), `KeyframeStrip`(put 뒤에만 has/image·복사·길이 검사·비었거나 정렬 아님 거부·`nearest` 앞·뒤·중간·같은 거리·같은 번호)
  - `test_slider_preview`(offscreen, 실제 시트 + `jump_to_click`): x → 값이 클릭 착지와 같음(메인·오버레이 시트 — 폭 전체를 3px 간격으로 클릭)·범위 밖은 끝에 붙고 거꾸로 가지 않음, 창 — 번호·그림·다른 스레드가 덮기 전에 복사·나쁜 배열 거부·계획 크기로 다시 맞춤·긴 번호에 맞춰 늚·포커스 안 가져감·커서가 있는 화면 안으로(`screenAt` 바꿔치기 — 다른 화면·None)·위가 모자라면 아래, 필터 — 보이기/숨기기·lookup 호출·창 비활성에 숨김·None이면 숨김·눌린 동안 숨김·늘 False·같은 프레임이면 다시 그리지 않음(채워짐·다른 프레임·숨은 뒤엔 다시)·lookup 예외는 숨김 + `report_from_handler` 처음 한 번(그 뒤로는 기록 한 줄씩), parent — 창이 가짐·ToolTip 창 그대로·화면 좌표 배치·창과 함께 지워짐·두 테마 아래 모양(라벨 배경 포함)·`popup_parent` 두 갈래(`sys.platform` 바꿔 끼움 — Windows는 parent 없는 창)·`detach()` 뒤엔 호버·창 비활성에 아무것도 안 함
  - `test_player_hover_thumbs`(실제 `VideoPlayer` offscreen — ProRes 파이프·mp4 cv2): 호버 번호 = 그 x를 클릭했을 때의 Current(메인·오버레이), 쉬면 띠가 다 차고 창에 그 장의 그림, `START_DELAY_S`(1초) 전엔 안 띄움(벽시계에 기대지 않는 단언)·재생 중 `paused`·멈춘 뒤 `IDLE_S`를 새로 셈·재생 중 틱은 `get` 없이 정지 한 번(가짜 psutil), ← 연타도 바쁨, 다음 파일을 여는 동안 옛 ffmpeg 정지(`_open_movie_capture` 안에서 STOPPED)·열기 실패 뒤 옛 워커가 이어 감, 기존 `is_dragging` 표지가 남아도 쉬면 띠를 만듦·슬라이더를 누르는 동안은 안 띄우고 진단 한 줄(계획마다 한 번), 바로 다른 파일로 가면 ffmpeg를 안 띄움, 놓인 워커의 신호 무시, 시퀀스·B는 안 만듦, `_release_side('A')`·창 닫기가 워커 정지, 창을 닫으면 필터를 떼고 팝업을 지움(이 플랫폼·Windows parent 갈래 — 닫힌 슬라이더 호버에 lookup 안 불림), 같은 경로 다시 열면 다시 만듦, A를 다른 길로 놓아도 낡은 계획이 안 보임·job 바꾸기가 띠를 버림·죽은 캡처면 숨김 + 틱 정지, 크기 상한·모르는 크기·읽지 못하는 파일은 기록만, 실패는 기록 + 창 파일마다 1회(A → B → A도)·ffmpeg 없음도 1회, 기능 끔이면 아무것도, 한 장짜리는 '1'; 거친 띠(2026-11-11): 조회가 정확한 샘플이 비면 가짜 워커에 꽂은 거친 띠의 가까운 키프레임(같은 거리면 앞쪽·안 찼으면 빈 상자)·정확한 샘플이 차면 그것·워커가 없거나 거친 띠를 버리면 빈 상자·창도 같은 그림, `coarse_done` 기록 한 줄(틱은 그대로)·옛 워커의 늦은 신호는 버림, 진짜 워커로 긴 H.264의 기록 차례(시작 → 거친 띠 먼저 → 거친 띠 완성 → 띠 완성)·끝난 뒤 호버는 정확한 띠·ffprobe가 없으면 stderr 한 줄 + 정확한 띠만 — 둘 다 오류 창 없음 (가짜 워커 `FakeBuilder`에 `coarse_done`·`coarse_strip`·`coarse_count`를 더함)
  - `test_hover_thumbs_settings`: 메뉴 항목(기본 체크·꺼진 세션은 해제·Windows는 화면 그리기 메뉴 바로 뒤), 끄면 저장 + 도는 워커 정지, 켜면 지금 영상으로 다시 시작·영상 없음/시퀀스면 아무것도, 저장 실패는 창 + 체크 되돌림(켜기 실패면 꺼진 채), 깨진 파일은 덮지 않음, 같은 값은 아무것도, 다른 창이 저장한 값은 쓰지 않고 적용, 파일의 나쁜 값은 고른 값으로 고침, 시작 때 읽기·깨진 prefs는 경고 1회 + 이 세션 끔(끝 글은 깨진 JSON·나쁜 값이 다름)·`app.launch`가 로더를 부름 (`test_mac_native_gate`의 `launch_until_window` 도우미는 새 로더를 끄는 한 줄을 더함 — 그 모듈은 디코더 설정만 봄, 단언은 그대로)
- **그 밖**: `test_smoke`·`test_fast_startup`·`test_files`·`test_user_files`·`test_media_info`(ffprobe JSON → 줄, 픽셀 형식 뜻, 실제 ffprobe로 시험 영상, 창의 HTML·자세히·실패 평문)·`test_frame_annotations_merge`·`test_annotation_burn_color`(도형 주석이 고른 색 그대로 — RGB 순서)·`test_annotation_click`·`test_external_tools`·`test_build_info`·
  `test_check_frozen_imports`·`test_release_tool`·`test_print_crash_reports`·`test_screenshot_check`·`test_refactor_checks`

CI(`.github/workflows/windows-build.yml`)는 세 플랫폼 — Windows(`windows-latest`), Mac Apple Silicon(`macos-15`), Mac Intel(`macos-15-intel`) — 에서
Python 3.10 환경을 만들고 소스 시험(`pytest tests`)을 돌린 뒤 앱을 빌드해 번들 검사와 빌드된 앱의 실행 시험(`ci/`)까지 함.
`test_paths_windows`·`test_update_helper_windows`처럼 한 OS에서만 도는 시험은 다른 OS에서 건너뛰므로, 어느 OS의 시험을 고쳤는지에 따라 CI에서 확인해야 함.

**코드를 옮기기만 하는 변경(동작이 그대로여야 할 때)의 검증 도구**:
- `ci/screenshot_check.py capture --out DIR` / `compare --baseline DIR --current DIR`: 장면 9개(처음 켠 창·밝은 테마·영상 A 열기·A/B 와이프·썸네일 모드·
  접는 상자 펼침·오버레이·주석 모드·OCR 검토 창)를 오프스크린으로 찍어 PNG 바이트와 위젯 트리까지 견줌. 위젯 트리는 숨은 위젯까지 담으므로
  슬라이더 호버 썸네일 뒤로 Mac·Linux에서는 숨은 `SliderPreviewPopup` 노드 + `QLabel` 둘이 모든 장면에 들어감(예상된 차이 — 팝업의 parent가 플레이어;
  Windows는 parent 없는 창이라 트리에 없음)
- `tools/refactor_checks/mixin_coupling.py snapshot|compare`: `VideoPlayer`의 MRO·메서드 본문 해시·`self` 결합을 정적 분석으로 스냅샷해 이동 전후를 견줌
  (예상된 차이는 `--allow` 목록에 적은 것만 통과)
- `tools/refactor_checks/runtime_globals.py`: 모든 함수가 쓰는 모듈 전역 이름이 풀리는지 확인 (코드를 옮기며 import를 빠뜨려 드물게 도는 분기에서만 터질 `NameError`를 잡음)

- `tools/make_manual_screenshots.py`: 사용법 매뉴얼의 그림을 합성 영상으로 다시 찍음(위 '주요 파일'의 '사용법 매뉴얼') — 화면을 바꾼 변경이면 돌려서 `yesoncheck/manual_images/`를 함께 커밋. 찍은 뒤 매뉴얼 모양은 `manual_open.write(<폴더>)`로 써서 브라우저(또는 헤드리스 크롬 `--screenshot`)로 확인

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
17. 슬라이더 호버 썸네일(2026-11-10 — Mac·Windows 실기): 메인·V 모드 오버레이 슬라이더 위 호버에 창이 떠서 커서를 따라가는지(뜨자마자 숨거나 깜빡이지 않는지 — 실제 플랫폼의 ToolTip 창·WindowDeactivate), 번호가 그 자리를 클릭한 Current와 같은지, 열자마자는 번호 + 빈 상자 → 쉬면 그림, 재생 중 4K fps(`[측정]`)·기록 줄 `[슬라이더 썸네일] 띠 만들기 시작`·`띠 완성`, 화면 가장자리·세로 영상·4GB 넘는 파일(번호만), Settings → 슬라이더 썸네일 끄고 켜기(Mac 메뉴 막대의 툴팁), 창을 닫은 뒤 ffmpeg가 남지 않는지
18. 슬라이더 호버 썸네일 — Windows 실기(PR #35): 다른 창에 가려진·비활성 YesonCheck 창의 슬라이더에 호버해도 그 창이 앞으로 오지 않고 포커스를 가져가지 않는지(팝업은 parent 없는 창 — `slider_preview.popup_parent`; 위젯을 parent로 쓰면 Qt가 창을 raise함), 창을 여럿 열고 닫은 뒤 앱을 끝낼 때 크래시가 없는지

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
- 슬라이더 썸네일 켬/끔(2026-11-10, Mac·Windows): 이 PC의 `prefs.json`(Mac `~/Library/Application Support/YesonCheck/prefs.json`, Windows `%LOCALAPPDATA%\YesonCheck\prefs.json` — `hover_strip.prefs_path()`가 플랫폼으로 가름)의 `"slider_thumbnails": true | false`(없으면 **켬**) — Settings → 슬라이더 썸네일이 `hover_strip.save_enabled`(`mac_prefs.update_pref` — 잠금 안에서 그 키만)로 씀, `app.load_slider_thumbnails`가 켤 때 한 번 읽음(이 창은 바로, 다른 창은 다음 실행부터). NAS 공유 설정에 넣지 않음(PC마다 다른 선택). 깨진 파일·불리언이 아닌 값은 켤 때 경고 창 1회 뒤 그 세션은 끔(파일은 그대로 — 메뉴로 고르면 그 값으로 고침; 깨진 JSON이면 메뉴로도 저장하지 못함). 띠 자체는 디스크에 쓰지 않음(RAM에 지금 A 파일 하나 분만)
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

### 2026-11-12 (시험 — Windows 배포 CI에서 흔들리던 호버 멈춤 시험)

`tests/test_player_hover_thumbs.py::test_opening_next_file_pauses_old_builder_while_opening`이 배포 CI의 Windows 작업을 두 번(1.9.0·1.9.1) 실패시켰음(재실행마다 약 1시간) — 여는 순간 옛 썸네일 ffmpeg가 정지됐는지를 psutil `status()`로 봤는데, **Windows의 psutil은 파이프 쓰기에서 막힌 스레드가 있으면 정지된 프로세스도 `running`으로 읽음**(빌더 시험의 `status` 갈래를 Windows에서 건너뛰는 까닭과 같음 — 이 시험만 빠져 있었음). 고침(시험만 — 앱 코드 무변경): 증거를 둘로 나눔 — ① **멈춤 표지**(모든 플랫폼): `_open_movie_capture`에 들어설 때 옛 워커의 `paused`가 이미 True(이 시험이 지키는 플레이어의 몫) ② **프로세스 상태**(POSIX만): psutil이 stopped. 표지가 실제 정지로 이어지는 것은 Windows에서도 빌더 시험의 `drain` 갈래가 봄. 확인: `_hover_thumbs_pause`의 `worker.paused = True`를 잠깐 없애면 `(경로, False, 'running')`으로 실패(표지만으로도 잡힘) — 되돌림. 사용자 지시("1.9.1을 내보낸 뒤 수정 시작해").

### 2026-11-12 (영상을 바꿀 때 떠나는 영상을 되감지 않음)

사용자 보고(1.9.0, Mac): 사이드바에서 다음 영상을 누르자 **떠나는** 영상에 대해 "VideoToolbox로 영상을 읽다가 도중에 실패해 … 리더가 0번 프레임 앞에서 끝났습니다 — 받은 장 수가 파일의 프레임 수 80보다 적음"이 뜸. 기록과 파일로 본 원인: 그 영상이 열려 있는 동안 **같은 이름으로 다시 렌더됨**(파일의 고친 때·안에 적힌 만든 시각이 오류 몇 분 전 — 그 폴더에서 그날 바뀐 영상은 그것 하나). 새 영상을 열 때 `open_file` → `_stop_playback_for_open` → `stop_video` → `seek_to_frame(1)`이 **떠나는 캡처**를 처음으로 되감다가 바뀐 파일에서 한 장도 못 받은 것(파일이 바뀌면 읽기가 0장으로 끝난다는 고리는 시각이 맞아떨어진 것으로 본 추정 — 재현은 안 함).
- **그 되감기는 남는 것이 없었음**: 1번 프레임·슬라이더·소리 위치·와이프의 B를 맞추는 일은 바로 뒤 `display_first_frame`(= 새 캡처의 `seek_to_frame(1)`)이 전부 다시 함. 비용만 있었음 — 위 오류 창, ffmpeg 파이프면 놓을 캡처에 ffmpeg를 한 번 더 띄움(`movie_pipe_source` '알고 둔 한계' ⑧ — 4K 약 0.5초), Mac 네이티브 약 0.03초(그 기록의 '멈추기').
- **고침**: `_stop_playback_for_open`이 `stop_video`를 부르지 않고 타이머·소리만 멈춘 뒤 단추·표시를 멈춘 상태로(`_show_stopped` — `stop_video`에서 떼어 낸 뒷부분). **Stop 단추·재생 끝의 `stop_video`는 그대로 처음으로 되감음.** 선택 재생은 전부터 되감지 않았음(그 갈래 무수정). 사용자 승인("빌드 전부 완료하고 진행하자") 뒤의 열기 길 변경.
- 시험 `tests/test_switch_without_rewind.py`(캡처를 감싸 read·set 횟수를 셈): 다른 영상으로 바꿀 때 떠나는 캡처를 건드리지 않음(멈춰 있을 때·재생 중일 때), B를 열 때 A는 첫 화면의 한 번만 읽음(예전 두 번), 새 A를 열면 와이프의 B도 1번 프레임으로(새 영상의 첫 화면이 맞춤), Stop 단추는 여전히 1번 프레임으로.
- **확인할 것(눈)**: Mac·Windows에서 사이드바 클릭·↑↓로 넘기기, 재생 중 넘기기, A/B 와이프에서 A 바꾸기.
- **배포 노트에 넣을 글**: "다른 영상으로 넘어갈 때 보던 영상을 처음으로 되감지 않습니다 — 전환이 조금 빨라지고(Windows의 4K ProRes에서 길면 약 0.5초), 보던 파일이 그사이 다시 렌더됐을 때 뜨던 오류 창이 뜨지 않습니다. Stop 단추는 전처럼 처음으로 되감습니다."

### 2026-11-12 (사이드바 — 목록 정렬: 이름·종류·버전·시간)

사용자 요청 "사이드바 리스트에 소트 기능 필요해. 사용자 선택해서 소팅할 수 있게. 이름 정렬 같은 기능 있잖아. 지금은 OSAN - OSRO - OSAN 섞여 있잖아. 이러면 사용자가 OSAN만 재생하고 싶을 때 힘들잖아."
- **무엇**: 탭 줄의 All 탭 바로 옆 **정렬 단추**(사이드바가 넓으면 `정렬: 이름 ▾`, 좁으면 `이름 ▾`·`↕`) → `이름`(기본 — 예전 순서)·`종류`(이름 끝의 OSAN·OSRO·HD … 끼리 묶음 — 없는 것 먼저, 종류 이름순)·`버전`(v01·TK2 … 끼리 — 번호 없는 것 먼저, 번호순)·`시간`(파일을 고친 시각이 최근인 것부터 — 이어진 요청 "정렬에 시간도 추가할 수 있어?"; 방향 '최근 것부터'와 뜻 '고친 시각'은 내 결정 — 사용자에게 알림). 묶음 안에서는(시간은 같은 시각이면) 이름 순서 그대로(안정 정렬). Mov·Seq·All 탭에 함께, ↑↓·선택 재생도 보이는 차례(`_playlist_selection`이 줄 순서로 모음 — 무수정). 종류·버전을 읽는 규칙은 개수 줄과 같아(`sidebar_counts.kind_and_version`) 개수 줄의 묶음 = 목록의 묶음.
- **시간 정렬의 디스크 읽기**: 이름이 아니라 파일의 고친 시각이라 `os.stat`이 필요 — 줄을 옮길 때 GUI 스레드에서 읽음(`_read_sidebar_times` → 항목의 `SIDEBAR_MTIME_ROLE`): 사용자가 `시간`을 고를 때(이미 시간이어도 — 다시 고르면 다시 읽음) 모든 영상을, 그 뒤 들어온 새 영상은 그것만. **저절로 도는 목록 다시 읽기에서는 다시 읽지 않음**(앱을 오갈 때마다 모든 파일을 NAS에 묻지 않게 — 그사이 다시 렌더한 영상을 위로 올리려면 `시간`을 한 번 더 고름). 실측(이 Mac, 10GbE NFS, 실제 job의 영상 571개): 0.21초·두 번째 0.01초 — job 목록을 만들 때의 폴더 읽기(GUI 스레드, 폴더 수백 개)보다 가벼워 스레드로 빼지 않음; Windows SMB는 안 잼. 읽지 못한 파일(지워짐·연결 끊김)은 `UNKNOWN_TIME`(맨 뒤)으로 두고 기록 한 줄(`[정렬] 고친 시각 읽음: n개 x초 — 읽지 못한 m개는 맨 뒤에 (첫 오류: …)`) — 창은 없음(없어진 영상은 목록 다시 읽기가 알림). 시퀀스는 첫 프레임 파일의 시각(`_sidebar_seq_time` — 한 번 읽어 기억, `시간`을 다시 고르면 비움).
- **내 결정(사용자에게 알림)**: 기준은 넷(파일 크기·영상 길이는 넣지 않음 — 길이는 파일마다 ffprobe가 필요), 단추 자리는 처음에 목록 아래로 뒀다가 사용자 지시("정렬버튼을 All 탭 옆으로 해줘")로 탭 줄의 All 탭 옆으로 — 기본 폭(176~182px)에서는 탭 막대 155px 옆에 21~27px뿐이라 단추 글이 폭에 맞춰 줄어들게 했고(가장 좁을 때 `↕` 17px — 여백 0; 그것도 안 들어가면 줄 밖으로 밀려 잘리지 않고 줄의 오른쪽 끝에 맞춰 All 탭의 오른쪽 여백에 조금 겹침 — Windows CI에서 탭 막대·글꼴이 조금 더 넓어 단추가 줄 밖으로 밀렸던 것; 탭 위젯의 최소 폭을 키워 자리를 보장하는 길은 창의 처음 크기 계산을 바꿔(`test_window_resize` 실패) 쓰지 않음), 넓을 때도 All 탭 바로 옆에 붙도록 탭 막대를 왼쪽 정렬로(그래서 Mac의 넓은 사이드바에서 탭이 가운데가 아니라 왼쪽 — 실제 Mac 화면 캡처로 세 폭 확인), 고른 정렬은 **창이 떠 있는 동안만**(job·폴더를 바꿔도 유지, 앱을 다시 켜면 이름 — 저장하면 다음에 켰을 때 순서가 달라 보이는 까닭을 놓치기 쉬움; 원하면 prefs에 저장하는 것은 후보).
- **어떻게**(위 '주요 파일'의 `sidebar_sort.py`·`sidebar_sorting.py`): Mov 목록은 원본이라(다시 읽기 계획·썸네일·선택 재생이 그 항목을 씀) **항목 객체를 그대로 두고 줄만 옮김**. 이름 순서는 항목의 기본 순위(`SIDEBAR_RANK_ROLE` — 정렬로 처음 바꿀 때의 줄 번호)로 기억. 다시 읽기(`_apply_sidebar_read`)는 계획을 기본 순위 순서로 세우고 바꿀 것이 있을 때만 목록을 잠깐 그 순서로 되돌렸다가 다시 정렬 — 계획 코드(`plan_refresh`·`_apply_sidebar_plan`)는 그대로. **이름(기본)에서는 새 코드가 목록을 건드리지 않음**(순위도 없음) — 기존 시험은 하나도 고치지 않음.
- **알고 둔 것**: 종류 묶음의 차례는 이름순이라 개수 줄(많은 순)과 차례가 다름(다시 읽을 때 묶음이 자리를 바꾸지 않게); 정렬해 둔 채 목록을 다시 읽어 바뀐 것이 있으면 목록을 두 번 옮김(기본 순서로 → 다시 정렬 — 600줄에서 눈에 띄지 않음, 5,000줄은 안 잼); 목록을 쓰는 중(썸네일 만드는 중 등)에 고르면 단추 글은 바로 바뀌고 줄은 끝난 뒤 옮겨짐; 기준을 바꾸면 Seq 목록은 통째로 다시 넣음(썸네일 모드면 Seq 썸네일을 다시 읽음); 시간 정렬은 고를 때 GUI가 파일 수만큼의 stat 동안 멈춤(이 Mac 571개 0.2초 — 수천 개 job·느린 연결에서는 길어질 수 있음, NAS가 멈추면 함께 멈춤 — job 불러오기와 같은 성질), 목록에 시각이 보이지는 않음(차례만 — 툴팁은 경로로 쓰이는 중); 단추의 `▾` 글자는 글꼴에 없으면 다른 글꼴로 대신 그려짐(Windows 실기 미확인); 매뉴얼 그림은 탭 줄이 보이는 것을 다시 찍음(좁은 사이드바라 단추는 `↕`로 보임 — 사이드바 그림의 6번 설명에 적음).
- **별도 리뷰(읽기 전용 — 차단 결함 없음, 가벼운 지적 9건)에서 고친 것**: 시퀀스의 고친 시각 캐시가 목록을 다시 불러와도 남던 것(→ Seq 목록을 비울 때 함께 비움 — 영상 항목과 같게), 기준을 바꿀 때 Seq 목록을 목록 쓰는 중에도 바로 다시 넣던 것(→ Mov 줄 옮기기와 함께 미룸), 창이 지워지는 중 탭 줄에 크기 이벤트가 오면 지워진 단추를 건드릴 수 있던 것(→ `sip.isdeleted` 확인), 문서의 낡은 줄 수·빠진 '시간'. **그대로 둔 것(알고 둠)**: 대소문자를 가리는 NFS의 `.TGA` 시퀀스는 시간 정렬 때 첫 프레임을 찾느라 시퀀스마다 폴더를 읽음(`first_frame_path` — 같은 폴더에 그런 시퀀스가 많으면 느림, 안 잼); 묶음 안 순서가 Mov(읽은 순서)와 All(이름 자연 정렬)에서 다를 수 있음(이름 정렬에서도 원래 그랬음); 목록을 쓰는 중에 처음 `시간`을 고르면 All 탭이 잠깐 시각 없는 차례로 보였다가 고쳐짐; 5,000줄 목록의 줄 옮기기 시간은 안 잼.
- 시험 `tests/test_sidebar_sort.py`(위 '테스트 전략' — 리뷰 뒤 더한 것: 목록을 다시 불러오면 시퀀스 시각을 새로 읽음·쓰는 중에는 Seq 목록도 그대로·정렬 뒤 클릭 → Shift+클릭이 한 묶음을 고름·창이 지워진 뒤의 단추 맞춤).
- **탭 줄 실측(CI 2026-11-12 — 따로 띄운 프로세스, 화면 없는 Qt)**: Mac(Arial) 처음 켠 폭 — 탭 위젯 182·탭 막대 155·`↕` 단추 17px·All 탭에서 5px 떨어짐, 가장 좁은 폭(158) — All 탭의 오른쪽 여백에 13px 겹치고 글자와는 3px. Windows(Windows 글꼴 폴더를 줘서 Segoe UI) 처음 켠 폭 — 182·153·22px·5px 떨어짐, 가장 좁은 폭(160) — 14px 겹치고 글자와는 2px; 단추 글 후보 폭 [86, 56, 22](Mac [80, 53, 17]). 두 플랫폼 모두 세 탭이 다 보이고 단추가 줄 안. **Windows CI의 시험 프로세스 자체는 글꼴이 없는 환경**(위 `movie_pipe_source` 항목의 '다음 후보' — 글자마다 12px: 탭 막대 204·단추 41px·All 탭에 34px 겹침)이라 창 시험의 단언은 잰 값 기준의 느슨한 것이고, 글자를 가리지 않는다는 단언은 진짜 글꼴의 자식 프로세스 시험이 함. FreeType으로 잰 값이라 실제 Windows 화면(DirectWrite·화면 배율 125/150%)과 몇 px 다를 수 있음 — 모양은 실기 확인.
- **확인할 것(눈)**: Mac·Windows에서 실제 job으로 종류·버전·시간 정렬과 되돌리기, 정렬한 채 새로고침(F5)·job 바꾸기·선택 재생, 썸네일 모드, 단추 모양과 자리(두 테마, 사이드바 폭을 바꿔 가며 — Windows의 화면 배율 125/150%에서도 All 탭의 글자를 가리지 않는지, `↕`·`▾` 글자가 제대로 보이는지).
- **배포 노트에 넣을 글**: "사이드바의 All 탭 옆에 정렬 단추가 생겼습니다 — 이름(기본)·종류·버전·시간. 종류로 정렬하면 OSAN·OSRO처럼 같은 종류끼리 모여 한 종류만 골라 이어서 재생하기 쉽고, 시간으로 정렬하면 최근에 고친(다시 렌더한) 영상이 위로 옵니다. Mov·Seq·All 탭에 함께 적용됩니다."


### 2026-11-12 (Help — '실행 및 빌드'를 뺌)

사용자 질문 "헬프에 실행및 빌드가 왜 있는 거지? 필요없으면 제거하는 게 낫지 않아?". 소스 폴더의 `run_app.sh`·`build_app.sh`를 새 터미널에서 돌리던 개발용 창이었고(Mac에서만 보임), **배포한 앱에는 그 스크립트가 들어 있지 않아**(spec에 없음) 누르면 '스크립트 없음' 경고만 떴음. 소스 실행에서는 이미 터미널에서 띄운 상태라 쓸 일이 없음 → `player_base`의 메뉴 항목과 `show_run_and_build_dialog`(61줄), 쓰이지 않게 된 import 둘(`subprocess`·`QDialogButtonBox`), README의 언급 넷, 매뉴얼 Help 메뉴 표의 한 줄을 지우고 `help_menu` 그림을 다시 찍음. 실행·빌드는 터미널에서 `./run_app.sh`·`./build_app.sh` 그대로. 시험 `tests/test_settings_menu.py`(Help 메뉴에 그 항목·처리기가 없음). **배포 노트에 넣을 글**: "Help 메뉴에서 개발용 항목 '실행 및 빌드'를 뺐습니다(Mac)."

### 2026-11-12 (CI — 충돌 보고서를 기다렸다가 출력: Mac pytest 세그폴트의 네이티브 스택을 보려고)

- **증상(원인 미확인 — main에 원래 있던 간헐 크래시)**: Mac CI의 pytest가 `tests/test_mac_app_events.py::test_open_startup_file_missing_video_shows_error_window_naming_it`에서 `Fatal Python error: Segmentation fault`로 죽음 — 파이썬 스택은 늘 같은 자리: `VideoPlayerBase.__init__` → `_init_hover_thumbs` → `slider_preview.py`의 `SliderPreviewPopup.__init__`(`super().__init__(parent, Qt.ToolTip | …)`). 본 것: 2026-11-12 `feat/take-colors`의 Intel 1회(다시 돌려 통과), 같은 날 `fix/smooth-downscale-raster`의 Intel·Apple Silicon 동시 1회. 그 시험은 `launch_env` 시험들(진짜 `app.launch` + 가짜 창) 바로 뒤에 진짜 `VideoPlayer`를 처음 만드는 시험.
- **이 Mac에서 재현하지 못함**: 전체 실행·CI와 같은 차례(test_a… ~ test_mac_app_events) 실행·그 파일만 30번(main) 모두 통과; 쓰레기가 된 앱 전체 이벤트 필터(`FileOpenRouter` — launch 시험이 순환 참조로 남김)를 걸어 둔 채 위젯 생성 순간마다 순환 GC를 강제로 돌리는 실험(창 10번씩 × 네 조건)도 죽지 않음 — 그 가설은 확인되지 않음.
- **왜 네이티브 스택이 없었나**: 워크플로의 '충돌 보고서' 단계(`ci/print_crash_reports.py`, `if: failure()`)가 pytest가 죽은 지 1~2초 만에 돌아 "충돌 보고서 0개"만 찍음 — macOS(ReportCrash)가 `.ips`를 쓰는 데 몇 초~수십 초가 걸림.
- **고침(진단 도구만 — 앱 코드 무변경)**: `print_crash_reports.py --wait 초`(`--poll` 기본 2초 — 0 이하는 인자 오류) — **방금 다 쓰인** 보고서(이 job·우리 프로세스·본문까지 읽히는 것·이 도구가 시작되기 `--fresh`초(기본 30) 전부터 고쳐진 것)가 없으면 그만큼까지 기다림. 쓰는 중인 보고서(JSON이 덜 됨·머리 줄만 있고 본문이 아직 — `is_complete`)·다른 프로그램의 보고서·**앞서 쓰인 우리 보고서**는 기다림을 끝내지 않고, 기한이 지나면 있는 대로(앞서 쓰인 것·덜 쓰인 것·읽지 못한 것 포함) 출력. 방금 다 쓰인 것을 처음 본 뒤에도 `--settle`초(기본 20, 기한은 넘기지 않음) 더 지켜봄 — 자식이 죽고 곧이어 pytest 본체도 죽으면 보고서가 둘인데 첫 것만 보고 끝내면 본체의 것을 놓침. 폴더를 훑는 사이 사라진 파일(`FileNotFoundError` — macOS가 옮김·지움)은 그 번에 건너뛰고 수를 끝 줄에(트레이스백으로 죽으면 모은 출력을 다 잃음). 끝 줄: `… 기다림 n초(최대 m초)`(방금 다 쓰인 것이 끝내 없었으면 ` — 방금(이 단계 직전 30초 안) 다 쓰인 보고서는 없음`)·`훑는 사이 사라진 파일 n개`(있을 때만). 워크플로는 `--wait 120`: 이 단계가 도는 Mac job의 실패(pytest·빌드·실행 시험·업데이트 시험)마다, 방금 쓰인 우리 보고서가 없으면 2분을 다 기다리고 있으면 최대 20초 더 — 알고 둠. **'방금'만 보는 까닭**(이 PR의 첫 CI에서 찾음 — Intel job이 러너의 DNS 실패로 `test_smoke_from_source`의 OCR 단계에서 실패했을 때 '기다림 0초'): `test_smoke`가 일부러 죽인 파이썬 둘(`faulthandler_sigsegv`·`time_sleep` 프레임 — 같은 `python3.10`)의 보고서가 몇 분 전에 이미 있어 그것을 보고 기다림을 끝냈음 — 그 뒤에 pytest가 진짜로 죽으면 그 보고서를 놓침(종료 플레이크로 앞서 죽은 자식의 보고서도 같음). 별도 리뷰(읽기 전용 — 승인, 지적 MEDIUM 1·LOW 4)에서 고친 것: 머리 줄만 쓰인 보고서로 기다림이 끝나던 것, 훑는 사이 사라진 파일, `--poll` 0·음수, 잇달아 죽은 프로세스(→ `--settle`), 이 줄의 '늘 2분' 문구. **모르는 것**: macOS가 `.ips`를 한 번에 쓰는지·임시 이름으로 썼다 옮기는지·고친 시각을 크래시 시각으로 맞추는지, 보고서 쓰기가 120초를 넘는 경우가 있는지 — 다음에 진짜 세그폴트가 날 때의 기록으로 확인. 시험 `tests/test_print_crash_reports.py`(가짜 시계·sleep·벽시계 — 기다렸다 출력·기한에 포기·쓰는 중인 보고서(덜 된 JSON·머리 줄만)·다른 프로그램의 보고서·기다림 없으면 sleep 안 함·앞서 쓰인 우리 보고서는 기다림을 안 끝냄·그것뿐이면 기한까지 기다리고 끝 줄에 적음·단계 직전에 쓰인 것은 바로·`--fresh` 폭·첫 보고서 뒤 `--settle`초 더(기한 안에서)·사라진 파일은 건너뛰고 셈·`--poll` 0 이하는 오류).
- **다음에 그 세그폴트가 나면**: 실패한 job의 '충돌 보고서' 단계에서 죽은 스레드의 네이티브 프레임을 볼 것(Qt·sip 어느 함수인지) — 원인을 정한 뒤에 고침. 그 전까지는 실패한 job만 다시 돌림(`gh run rerun <id> --failed`).

### 2026-11-12 (테마 전환 — 색만 바뀌고 자리·크기·글꼴은 그대로)

사용자 보고 "테마 전환시 전체적으로 UI 사이즈 변경돼. 테마만 전환돼야 하는데"·"화이트 테마 전환시 버튼의 비율들이 바뀌는 거 같아" (1.9.0에도 있던 것 — 밝은 테마를 고친 뒤 눈에 띔).
- **원인**: 두 테마 시트를 따로 써서 **색이 아닌 속성**까지 달랐음. 화면 없이 잰 값(1280×900): 테마를 바꾸면 보이는 위젯 63개가 **전부** 자리·크기가 바뀜 — 밝은 시트는 `QWidget` 규칙에 `font-size: 12px`이 없어 자식 위젯이 시스템 글꼴 크기(이 Mac 17px 대 12px)로 커지고(메뉴 줄 19 → 24px, 라벨 14 → 19px), `QPushButton`·`QComboBox`에 `min-height: 20px`(단추 32 → 38px), 목록 줄에 `padding: 6px`(줄 높이 14 → 32px), 스크롤바 `width: 12px`(19 → 12px), 콤보 화살표·슬라이더·스플리터 치수도 따로였음.
- **고침**: 밝은 시트를 **어두운 시트와 같은 틀**(같은 선택자·같은 치수)로 다시 쓰고 색만 밝은 테마 것으로 — 어두운 시트는 글자 하나 안 바뀜(기준: 켤 때의 테마이고 매뉴얼 그림의 테마). 밝은 테마에서 달라지는 모양: 글꼴·단추·목록 줄이 어두운 테마와 같은 크기(더 촘촘), 콤보 화살표가 어두운 테마와 같은 것, 스크롤바가 같은 굵기, 목록 줄 사이의 가는 선과 마우스를 올린 줄의 바탕 없음, 우클릭 메뉴(QMenu)가 목록과 같은 흰 바탕·테두리(어두운 시트처럼 `QListWidget, QListView, QMenu` 규칙 — 전에는 시스템 색). 색이 아닌 차이로 남긴 것은 체크 상자의 체크 그림(`image`) 하나.
- **지키는 시험** `tests/test_theme_geometry.py`: ① 두 시트의 규칙에서 색이 아닌 속성이 선택자마다 같음(값 안의 색은 빼고 견줌 — 한쪽에만 치수를 넣으면 실패) ② 진짜 창(접는 상자 펼침·목록 60줄)에서 테마를 바꿔도 보이는 위젯의 자리·크기가 그대로(밝게 → 다시 어둡게) ③ 목록 줄 높이·스크롤바 굵기·글꼴 크기(메뉴 줄·목록·단추·콤보·개수 줄·딸린 창)가 그대로. `test_stylesheet_freeze`의 밝은 시트 해시 갱신(어두운 쪽 그대로).
- **확인**: `ci/screenshot_check.py` 9장면 — 어두운 테마 8장면 PNG 바이트 동일, light_theme만 다름. 실제 화면(cocoa·GL) `screencapture`로 밝은 테마의 배치가 어두운 테마와 같은지 눈으로 봄.
- **배포 노트에 넣을 글**: "테마를 바꿔도(T 키) 단추·글자·목록의 크기와 자리가 그대로입니다. 전에는 밝은 테마에서 글자와 단추가 커지고 배치가 달라졌습니다."

### 2026-11-12 (사이드바 — 테이크·버전별 글자색)

사용자 요청 "사이드바 리스트에서 tk1, tk2…v01, v02 등 테이크 넘버가 다른 건 다른 컬러로 표시하면 가독성이 좋을 거 같아" → "시퀀스가 푸른색이니까 이 색깔 피해서 설정해줘" → "화이트 테마에서도 가독성 떨어지는지 체크해야 돼".
- **규칙** `yesoncheck/sidebar_take_colors.py`(Qt 없음): 번호는 개수 줄과 같은 규칙(`sidebar_counts.kind_and_version` — 이름 끝의 TK·v + 숫자)으로 읽고(`take_number`), `take_color(이름, 테마)`가 **1번·0번·번호 없음은 None(테마 기본색 — 따로 칠하지 않음)**, 2번부터 `TAKE_COLORS[테마]`의 넷을 돌려 씀(2 초록·3 분홍·4 보라·5 연두·6 초록…; TK와 v는 같은 번호면 같은 색). 색 값 — 어두운 `#7ee081`·`#ff8fd0`·`#c9a7ff`·`#d7e35a`, 밝은 `#187a35`·`#c2187a`·`#6f42c1`·`#766c00`.
- **색을 고른 기준(시험이 지킴)**: ① 이미 뜻이 있는 색과 색상(hue)이 25도 넘게 떨어짐 — All 탭의 시퀀스(하늘색 `ALL_SEQ_FG`)·선택 재생 중(빨강)·어두운 테마의 고른 줄(주황 #ff9900; 그래서 5번은 노랑이 아니라 연두) ② 목록 바탕과의 명암 대비 4.5:1 이상 — 실측 어두운 테마(#232323) 7.6~11.2:1, 밝은 테마 흰 바탕 5.4~6.5:1(처음 고른 밝은 연두 #857a00이 4.4:1이라 바꿈). 두 테마의 목록을 화면 없이 찍어 눈으로도 봄.
- **칠하기** `SidebarAllMixin`(개수 줄 옆): `_paint_mov_item(item)` = 테이크 색을 칠하거나 따로 칠한 색을 지움(같은 값이면 건드리지 않음 — 모델 신호 없음). `_apply_take_colors(repaint=False)`는 제 타이머(`_take_color_timer` 0ms — Mov 모델의 rowsInserted·modelReset 뒤에만; 탭을 바꾸거나 Seq 목록이 바뀔 때는 돌지 않음 — 리뷰: 처음에는 개수 줄 타이머에 이어 탭을 누를 때마다 전체를 돌았음, 5,000줄 약 30ms)로 **아직 칠한 적 없는 항목만**(따로 칠한 글자색이 없는 것 — 새 항목) 칠함: 목록을 다시 읽어도 이미 칠한 항목(테이크 색·선택 재생 강조)은 그대로(처음에는 전부 다시 칠해 `test_sidebar_refresh`의 '남는 항목은 그대로'가 깨졌음). 테마를 바꾸면(`set_dark_theme`·`set_light_theme`) `repaint=True`로 전부 다시 — 선택 재생이 빨갛게 강조한 줄(`SidebarPlaylistMixin._playlist_highlighted_path` — 강조할 때 적고 `reset_sidebar_colors`가 지움; `self.playlist`·`current_playlist_index`는 폴더 불러오기 같은 다른 길도 고쳐 써서 따로 둠, 리뷰)만 빼고. All 목록의 mov 사본은 원본을 복제하므로 따라오고(원본의 dataChanged → 미룬 다시 만들기) 시퀀스는 하늘색 그대로.
- **개수 줄에도 같은 색**(사용자 지시 "여기에도 일관성있게 적용돼야지" — `638개 — OSAN 615 (v01 397 · v02 176 …)`): `sidebar_take_colors.count_line_html(글, 테마)`가 `sidebar_counts.count_text`의 글에서 **괄호 안**의 버전·테이크 토막(`v02 176`) 중 2번 이상을 같은 색의 `<span>`으로 감쌈(버전·테이크는 늘 괄호 안 — 괄호 밖 포맷 이름이 `v2`처럼 생겨도 그대로; 나머지 글은 escape, All 탭의 줄 바꿈은 `<br>`). 칠할 토막이 없으면 None → 라벨은 예전처럼 평문(`Qt.PlainText`), 있으면 `Qt.RichText`(`_update_sidebar_count`). Seq 탭은 목록에 테이크 색이 없으므로 줄도 칠하지 않음(줄의 색 = 목록의 색). 테마를 바꾸면 줄도 다시 만듦.
- **선택 재생**(`sidebar_playlist`): 지금 항목이 아닌 줄과 끝난 뒤의 되돌리기(`reset_sidebar_colors`)가 테마 기본색을 직접 넣던 것을 `_paint_mov_item`으로 — 테이크 색이 남고, 기본색 줄은 따로 칠한 색을 지움(시트의 기본색과 같은 값이라 모양은 그대로). 코드로 본 것: 예전에는 선택 재생 뒤 테마를 바꾸면 직접 넣은 옛 테마 글자색이 남았음 — 이제 테마를 바꿀 때 다시 칠함.
- **알고 둔 것**: 고른 줄은 테이크 색이 아니라 목록 시트의 선택 글자색(어두운 테마 주황·밝은 테마 기본색 — `::item:selected`의 color가 우선). Seq 탭의 시퀀스에는 색을 넣지 않음(All 탭에서 시퀀스는 하늘색이어야 해서 탭마다 색이 달라짐 — 넣을지는 후보).
- 매뉴얼: 사이드바 쪽에 '테이크·버전 색' 절, 목록이 보이는 그림을 다시 찍음(합성 영상의 TK2 줄과 개수 줄의 `TK2 5`가 초록).
- 시험 `tests/test_sidebar_take_colors.py`: 번호 읽기(개수 줄 규칙·샷 코드 V005는 버전 아님)·1번과 번호 없음은 기본색·번호마다 색과 돌려 쓰기·모르는 테마 KeyError·뜻 있는 색과의 hue 거리·명암 대비, 창 — 목록에 들어오면 칠함·테마를 따라 바뀜·All 탭(영상은 테이크 색, TK2 시퀀스도 하늘색)·선택 재생 되돌리기 뒤에도 남음·재생 중인 줄은 다시 칠해도 빨강, 개수 줄 — 버전·테이크 토막의 색(테마별)·칠할 것이 없으면 평문·escape와 줄 바꿈·괄호 밖은 그대로·Seq 탭은 평문.
- **배포 노트에 넣을 글**: "사이드바 목록에서 테이크·버전 번호가 2 이상인 영상은 번호마다 다른 색으로 보입니다(2 초록·3 분홍·4 보라·5 연두). 1번과 번호 없는 이름은 기본색, All 탭의 이미지 시퀀스는 하늘색 그대로입니다. 목록 아래 개수 줄의 버전·테이크 글자도 같은 색입니다."

### 2026-11-12 (밝은 테마 — 어두운 테마가 섞여 보이던 것)

사용자 보고(1.9.0 Mac 화면) "화이트 테마 T 모드의 일관성이 없어. 블랙 테마가 섞여 있어". 섞여 있던 것 셋:
- **창 바탕이 검정(Mac)**: 밝은 시트에서 `QMainWindow { background: #fafafa }` **뒤에** `QWidget { background: transparent }`가 있었음 — 창 자신도 QWidget이라 같은 무게의 두 규칙 중 뒤의 것이 이겨 창 바탕이 투명(창이 아무것도 안 칠함 — `palette().window()` alpha 0). raster 화면에서는 시스템 창 색이 비쳐 티가 안 났고, **GL 뷰포트(Mac 기본 — 2026-10-28 b0afebc부터)에서는 칠하지 않은 자리가 검게** 나옴(이 Mac 실측 `screencapture`: GL 검정·`YESONCHECK_VIEWPORT=raster` 밝은 회색·고친 뒤 GL #fafafa). 화면 없는(offscreen) 화면은 흰색으로 보여 `ci/screenshot_check.py`의 light_theme 장면도 못 잡았음. → 두 규칙의 차례를 바꿈(QWidget 먼저, QMainWindow 뒤).
- **접는 상자(ROI 설정·OCR 분석·결과 관리·수정 사항 주석)의 머리**가 어두운 색 고정: `CollapsibleBox`가 단추에 색을 직접 넣어(위젯 자신의 시트는 창 시트보다 우선) 테마를 바꿔도 남았음. → 색(바탕·테두리·글자, hover·checked)은 두 테마 시트의 `QPushButton#collapsibleToggle`로 옮기고(어두운 쪽은 예전 값 그대로, 밝은 쪽 #e9ecef·#ced4da·#2c3e50, 펼침·hover #dee2e6), 단추에는 objectName과 테마와 무관한 모양(정렬·여백 8px·굵기·모서리)만 남김. **함정**: 여백까지 창 시트로 옮기면 가운데 열 컨테이너의 시트(`compact_buttons` — QPushButton 좌우 여백 6px)가 창 시트보다 가까워 그쪽이 이기고 글자가 2px 밀림(화면 비교로 잡음) — Qt는 시트가 다르면 무게(specificity)보다 가까운 조상의 시트를 먼저 침.
- **'OCR 분석 방식:'·패턴 라벨**의 글자색이 #e0e0e0 고정(`OCR_OPTION_LABEL_STYLE`) — 밝은 바탕에서 거의 안 보임. → 색을 빼 테마 시트의 QLabel 색을 따름(어두운 테마는 같은 #e0e0e0).
- **확인**: `ci/screenshot_check.py`로 고치기 전·후 9장면 — 어두운 테마 8장면은 PNG 바이트까지 같고 light_theme만 다름. 실제 화면(cocoa·GL)은 격리한 HOME으로 창을 띄워 `screencapture -R`로 전후를 찍어 봄(창·펼친 상자). 시험 `tests/test_light_theme.py`는 창·단추를 **투명한 그림에 그려**(`render` → ARGB) 바탕을 실제로 칠하는지와 색을 봄(칠하지 않은 자리는 투명으로 남음 — GL 합성 자체는 화면 없는 시험이 못 봄), `test_stylesheet_freeze`의 해시·글자 수 갱신(어두운 3,519자·밝은 4,443자).
- **그대로 둔 것**: 시간 슬라이더 띠(남색)·Stop 단추(회색)·영상 아래 정보 라벨들은 두 테마에서 같은 고정 시트(어두운 테마에서도 같은 모양). 딸린 창(QDialog)·우클릭 메뉴는 창 시트의 `QWidget { background: transparent }`를 받아 시스템 창 색으로 보임 — 이 Mac(라이트 모드)에서 밝은 회색(실측), macOS 다크 모드에서는 미확인(어두운 바탕에 어두운 글자일 수 있음 — 후보). 작품 경로 관리 창처럼 자기 시트를 가진 창도 그대로.
- **배포 노트에 넣을 글**: "밝은 테마(T 키)에서 창 바탕이 검게 나오고(Mac) 접는 상자가 어두운 색으로 남던 것을 고쳤습니다."

### 2026-11-12 (Settings — GPU Acceleration·4K 성능 모드 메뉴를 뺌)

사용자 요청 "Settings 버그 2건 … 검토해줘. 개선 시킬 수 있는지" → 검토 뒤 사용자 결정 '둘 다 메뉴에서 빼기'. 두 메뉴는 저장소 첫 커밋(2026-10-12)부터 **고른 값이 적용된 적이 없었음**(1.1.0~1.9.0):
- **원인**: ① 4K 성능 모드 — `set_performance_mode`가 `VideoPlayerBase`(메뉴용, 정수 index)와 `PlayerPlaybackMixin`(문자열 모드)에 같은 이름으로 둘이라 MRO에서 앞선 playback 쪽이 정수를 받아 늘 `else`(auto) 갈래, 메뉴 체크도 쌓임. ② GPU Acceleration — 빌드의 OpenCV(PyPI 4.6.0.66)에 CUDA가 없어 항목이 [CPU, AMD (OpenCL)] 둘인데 OpenCL에 index 2를 넘김(체크 모두 풀림·콤보 −1). 짝이 되는 콤보 상자 둘(`gpuComboBox`·`performanceComboBox`)은 만들기만 하고 레이아웃에 없어 메뉴가 유일한 길이었음.
- **고쳐서 살리지 않은 까닭(실측·코드)**: GPU 설정이 바꾸는 것은 BGR → RGB 색 변환뿐인데 OpenCL(`cv2.UMat` 올림 → 변환 → 내려받기)이 CPU보다 느림 — 이 Mac(RX 5700 XT, 150회 번갈아, load 19): 1080p CPU 1.1ms 대 OpenCL 7.3ms, 4K 2.8ms 대 25.2ms, 프로세스의 첫 OpenCL 호출 293ms, 결과 픽셀은 같음(Windows는 안 잼 — 4K 한 장 25MB를 올리고 내려받는 구조는 같음). 4K 성능 모드는 재생이 아니라 슬라이더 드래그 미리보기의 세 값(캐시 장수·갱신 간격·건너뛰기 문턱)만 바꾸고, '속도'일수록 문턱이 커서(20·30장) 짧은 샷의 미리보기가 듬성해지며 캐시 300장은 4K에서 7.5GB. 그 설정이 겨누던 4K 문제는 네이티브(VideoToolbox)·ffmpeg 파이프·전체 프레임 캐시가 대신 풂.
- **한 일**: `player_base`에서 두 서브메뉴·`set_gpu_mode`·`set_performance_mode`·두 콤보 상자·`gpuLabel`·읽는 곳 없던 `skip_frame_processing`을, `player_playback`에서 콤보를 읽던 처리기 셋(`change_gpu_backend`·`change_performance_mode`·`set_performance_mode`)을 지움. **값은 켠 직후의 값 그대로**(`cache_size` 50·`drag_update_interval` 30ms·`frame_skip_threshold` 5·`performance_mode` 'auto'·`use_gpu` False) — 메뉴를 건드리지 않은 창이 늘 쓰던 값이라 동작 변화 없음(예전에는 4K 성능 모드에서 무엇을 누르든 100·15ms·10으로 바뀌었음 — 그 길이 사라짐). **재생·탐색 코드는 무수정**: `process_frame`의 GPU 갈래·`optimize_for_4k`의 모드 갈래·`process_frame_gpu_optimized`는 타지 않는 채 남음(지울 후보).
- 매뉴얼 설정 쪽의 두 줄을 지우고 `settings_menu` 그림을 다시 찍음. Mac의 Settings는 이제 `재생 디코더 (Mac)`·`슬라이더 썸네일` 둘.
- 시험 `tests/test_settings_menu.py`: 메뉴에 두 항목이 없음, 처리기·콤보가 남지 않음, 드래그 미리보기 값·CPU 색 변환(HD 길·4K 길)이 그대로, 그리고 **이름 가림 가드** — `VideoPlayer.__mro__`의 프로젝트 클래스 둘이 같은 이름을 정의하면 실패(뒤쪽을 진짜 `super().이름(...)` 호출로 잇는 확장만 허용 — `ast`로 봄, 주석·docstring 속 글자는 안 침; `__init__`도 봄; 지금 예외는 `instance_status` 하나). 알고 둔 한계(리뷰): 인스턴스 속성으로 가리는 것·`super(Cls, self)` 꼴·Qt 메서드 재정의는 범위 밖. `set_performance_mode`·`show_help`(2026-11-11)가 이렇게 가려져 있었음.
- **배포 노트에 넣을 글**(다음 배포의 0번에서 `release_notes.py`에): "Settings에서 GPU Acceleration과 4K 성능 모드를 뺐습니다. 두 항목은 골라도 적용되지 않던 것이라 재생·탐색 동작은 그대로입니다."

### 2026-11-11 (사용법 매뉴얼 — Help → 사용법이 기능별 쪽·화면 그림·단축키·업데이트 내역이 든 HTML 매뉴얼을 브라우저로)
- **요청**(사용자, 배포 전): "헬프 사용법에 지금까지 설명되지 않은 기능 전부 추가" → "HTML로 깔끔하게 정리하는 게 낫지 않아? 가독성이 너무 떨어져" → "업데이트 릴리즈 내용도 같이" → "툰붐 하모니 매뉴얼처럼 툴 스샷 떠서 설명, 기능별로 분리" → "스샷에 예손 작품 이미지가 들어가면 안 돼" → "단축키 설명도 빼놓으면 안 돼".
- **찾은 것**: 사용법 코드가 둘이었음 — `player_playback.show_help`(QTextBrowser 창)가 MRO에서 앞이라 불렸고, `player_base.show_help`(QMessageBox — 내용도 다름)는 한 번도 안 불리는 죽은 코드였는데 기존 시험(`test_build_info`의 영어 Windows 날짜 시험)은 그 죽은 쪽을 보고 있었음('같은 이름의 메서드를 두 믹스인에 두지 않음' 규칙 위반). 둘 다 지우고 `player_base.show_help` 하나로.
- **고침**: 위 '주요 파일'의 '사용법 매뉴얼' — 글 `manual_content`(쪽 15개) + `release_notes`(1.1.0~1.9.0) → `manual_html`이 HTML 한 파일로 → `manual_open`이 사용자 폴더에 쓰고 기본 브라우저로. 그림 22장은 `tools/make_manual_screenshots.py`가 합성 영상으로 찍음. 앱 안의 창(QTextBrowser)이 아니라 브라우저로 한 까닭: 사용자 예시가 웹 매뉴얼(하모니)이고, Qt 리치 텍스트로는 목차·그림 배치·검색·확대가 조잡함(QtWebEngine은 빌드에 없음); 대가는 앱 밖으로 나가는 것. 빌드: spec `manual_datas`·smoke `사용법 매뉴얼` 단계. 배포 절차에 0번(릴리스 노트를 저장소에 먼저, 노트 파일을 거기서 뽑음 — BUILD.md 7-1)이 생김.
- **시험**: `test_manual_html`·`test_manual_open`·`test_release_notes`(아래 '테스트 전략'), `test_build_info`의 날짜 시험은 정보 창만(사용법 쪽은 죽은 코드를 보던 것이라 뺌 — 새 사용법에는 날짜 글이 없음).
- **쓰다가 찾은 기존 버그 둘(이 변경에서 고치지 않음 — 동작이 바뀌는 수정이라 사용자 결정 뒤에; 매뉴얼에는 '이 버전에서는 적용되지 않음'이라고 사실대로 적음)**: ① **Settings → 4K 성능 모드가 무엇을 골라도 자동** — `set_performance_mode`가 `player_base`(메뉴용 — 정수 index를 받아 체크·콤보를 맞춤)와 `player_playback`(문자열 'speed'·'ultra'·'quality')에 **같은 이름으로 둘**이라 MRO에서 앞선 playback 쪽이 메뉴의 정수를 받아 `else`(auto) 분기로 감, 메뉴 체크도 서로 풀리지 않고 쌓임(오프스크린 실측) — '같은 이름의 메서드를 두 믹스인에 두지 않음' 위반(`show_help`와 같은 종류). ② **Settings → GPU Acceleration → AMD (OpenCL)이 CUDA 없는 PC(pip cv2 — 사실상 전부)에서 아무 일도 안 함** — 메뉴 항목은 [CPU, OpenCL] 둘인데 OpenCL이 `set_gpu_mode(2)`를 불러 체크가 모두 풀리고 콤보 index가 −1이 됨(실측). 그리고 **목록에 포커스가 있으면 T·B 키가 듣지 않음**(`eventFilter`가 그 둘은 안 받음 — 실측; 영상 쪽을 클릭하면 됨 — 매뉴얼에 적음). **①②는 2026-11-12에 두 메뉴를 빼서 정리함(위 항목) — 매뉴얼의 '적용되지 않습니다' 문장도 그때 지움.**
- **알고 둔 것**: 그림은 Mac에서 찍은 어두운 테마 화면(Windows 전용 메뉴 항목은 글로만). 매뉴얼 모양은 헤드리스 크롬 렌더(밝은·어두운 테마)로 확인했고 여는 길은 이 Mac의 소스 실행에서 F1로(기본 브라우저) — Windows 브라우저·Windows에서의 `os.startfile` 열기는 미확인(CI의 smoke는 매뉴얼을 쓰기만 하고 열지 않음). `.html`의 기본 프로그램이 브라우저가 아닌 PC(편집기 등)에서는 그 프로그램으로 열림. 화면을 바꾸는 변경마다 그림을 다시 찍어야 함(자동으로 낡음을 알리는 장치는 그림 이름 대조뿐 — 그림 내용이 낡았는지는 사람이 봄).

### 2026-11-11 (슬라이더 호버 썸네일 — 긴 파일의 띠를 빨리: 해상도·코덱별 스레드·키프레임 거친 띠)
- **증상**(사용자 질문 2026-11-11 — '호버 이미지 생성이 즉시 가능해? 20분짜리 애니매틱은 시간이 오래 걸려'): 22.6분 애니매틱(FL106 — H.264 1280×720 24fps 32,553장 798MB, 키프레임 558개·GOP 최소 1·평균 58.4·최대 72장)의 띠 완성이 67.0초. 1코어(Ruling 14 — 4K 재생 보호용)가 720p에도 걸렸고, 띄엄띄엄 골라도 `select`는 디코드한 뒤 버리므로 파일 전체를 디코드함
- **측정**(이 Mac, 내부 측정 기록 `records/2026-11-10-slider-hover-thumbnails/measure.md`의 2026-11-11 절): FL106 — OS 캐시에 올린 뒤 번들 ffmpeg 9.0.2 각 1회: 지금 방식 67.0초 / 스레드 제한 없음 18.8초 / 키프레임만(`-skip_frame nokey`) 10.2초·558장 / 샘플마다 `-ss` 한 장 장당 0.19초(494장 약 94초) / `-hwaccel videotoolbox`는 번들 ffmpeg에서 초기화 실패. KOTH 1080p H.264 애니매틱(1920×1080 23.976fps 35,693장): 1코어 82.2초·기본 스레드 24.6초, 키프레임 패스 11.7초(1코어)·12.6초(기본 — 파싱 병목이라 스레드 무관). '즉시'(1초 안)는 어느 방식도 아님 — 바닥은 파일 전체를 demux·파싱하는 약 10초. **사용자 결정: 1단계와 2단계만**(커서 자리 우선 탐색·디스크 캐시는 하지 않음). 설계는 내부 저장소 `specs/2026-11-11-hover-strip-faster-design.md`
- **재생 게이트**(`yc_hover_measure.py` — 켬이 끔의 범위 안인지, 이 Mac): 1080p ProRes 422 HQ(FL_106_A001_TK1, 334장, 네이티브 재생) 켬·끔 각 9판 — 끔 최대간격 44~62ms·끊김 0/9, 켬 44·89·44·44·44·44·58·124·44ms·끊김 2/9(89ms는 Play 3.09초, 124ms는 7.04초 — 둘 다 ffmpeg는 Play 직후 이미 정지돼 CPU 0.0) → **불통과**(Fisher p≈0.47 — 증명은 아니지만 범위 기준·재생 최우선); 720p H.264(FL106 앞 30초 721장, cv2) 켬·끔 각 3판 — 끔 91·44·87ms·끊김 1·0·1, 켬 45·67·76ms·끊김 0·2·1 → **통과**; 1080p H.264(KOTH 30초 클립, cv2) 켬·끔 각 3판 — 끔 76·84·50ms·끊김 1·1·0, 켬 62·65·48ms·끊김 0·1·0 → **통과**
- **1단계 — 해상도·코덱별 스레드**(Ruling 24·25·26, `hover_strip.thread_limits`): 원본 ≤ 1280×720이면 옵션 없음(어느 코덱이든), ≤ 1920×1080이고 헤더로 안 코덱이 허용 목록 `LONG_GOP_FULL_THREADS_CODECS`(`{"h264"}` — 재생 게이트를 잰 코덱만, 양성 증거로만 켬 — Ruling 26)에 있으면 옵션 없음, 그 밖(720p보다 크고 목록 밖 코덱·코덱 모름·1080p보다 큼)은 지금처럼 `-filter_threads 1 -threads 1`(1080p ProRes·4K 명령 글자 그대로 — `test_command_shape`가 고정). 코덱은 긴 파일(간격 > 1)이면 워커가 헤더 ffprobe로 늘 알아냄, 짧은 파일은 모름(짧은 1080p ProRes 샷이 바로 불통과 파일 — 1080p H.264 500장은 1코어로도 1~2초로 추정(측정 안 함)). `StripPlan`에 원본 크기(`source_width`·`source_height`)를 더함
- **2단계 — 키프레임 거친 띠 먼저**: 긴 파일이면 헤더 ffprobe(패킷 없이)로 all-intra·모르는 속도를 먼저 거르고(`거친 띠 건너뜀` 한 줄 — 실패 아님), 그 밖이면 패킷 ffprobe로 키프레임 번호를 읽어(`hover_keyframes.scan_keyframes` — 새 모듈, 버림(D) 패킷 제외) 키프레임이 전체의 1/4 이하면 `-skip_frame nokey`로 키프레임 전부를 받아(1000장 넘으면 m장마다 넣음 — select 없음) 거친 띠(`coarse_strip`)를 먼저 채운 뒤(`coarse_done`) 정확한 띠 — 정확한 띠가 끝나면(`done` 앞) 거친 띠는 버림. 호버는 정확한 샘플이 비면 가장 가까운 키프레임 그림(`player_hover_thumbs._hover_entry`). 거친 띠의 실패(ffprobe·종료 코드·장수 불일치 — 넘치면 그 자리에서 끊음·예외)는 **창 없이** stderr 한 줄 + 사유 전문 뒤 정확한 띠를 이어 감. stop 뒤에는 새 프로세스를 띄우지 않음. 기록 줄은 위 `player_hover_thumbs.py` 항목의 '기록 줄'
- **리뷰(읽기 전용) 반영**: 재리뷰 — 1080p 갈래를 막는 목록(all-intra가 아니면 풂)에서 허용 목록(h264)으로(Ruling 26); I-1 stop 뒤 정확한 ffmpeg를 띄우지 않음, L-1 편집 목록으로 앞이 잘린 mp4의 `KD_` 키프레임 제외(리뷰 실측: K 10개 중 KD_ 1 → 출력 9장), L-2 ffprobe 길의 stop(반쪽 JSON을 거짓 기록하지 않음·트레이스백은 '멈춘 띠 워커' 머리로), L-3 select 대신 파이썬에서 m장마다(장수 검사가 정확해짐 — 스펙 §3.2와 다름), L-4 목록을 넘으면 그 자리에서 kill, L-5 헤더로 all-intra·가변 속도를 패킷 스캔 전에(VFR은 실패가 아니라 건너뜀), L-6 거친 패스 도중 멈춤 시험의 Windows 증거(파이프 비우기), 기록 줄에 K와 줄인 장수 둘 다
- **실측**(이 Mac, 앱 안 idle, 최종 코드 20ddf7a): FL106 `거친 띠 완성: 558/558장 9.7초`·`띠 완성: 494/494장 28.3초`(load 5.2; 예전 67.0초 — 처음 그림까지 약 10초, 다 정확해지기까지 약 28초), KOTH1410(1080p H.264 35,693장) 거친 띠 12.9초·정확한 띠 37.0초(load 9.4; 예전 1코어 헤드리스 82.2초), 4K 334장 `띠 완성 38.9초`(3차 38.3·38.2초와 같음 — 그대로)
- **대가**: all-intra가 아닌 긴 파일은 파일을 두 번 더 읽음(패킷 ffprobe 스캔 + 키프레임 패스 — 캐시에 있으면 FL106 798MB 약 0.5초, NAS 첫 읽기 약 3초; 헤더 ffprobe는 파일을 다 읽지 않음), 거친 띠 메모리가 잠깐 최대 1000장(16:9 173MB, 정사각 307MB — 정확한 띠가 끝나면 놓음), 띠 완성까지의 총시간은 거친 패스만큼 늘어남(FL106 헤드리스 18.8초 → 앱 안 28.3초 — 대신 9.7초에 거친 그림), 옵션 없는 띠 ffmpeg(720p 이하·1080p 이하 h264)는 쉴 때 CPU를 다 씀
- **알고 둔 한계**: ① 거친 그림은 키프레임 자리라 커서 프레임과 최대 GOP/2(FL106 최대 72장 → 1.5초) 어긋남 — 정확한 띠가 덧씌우면 예전과 같은 ≤ step/2(1.4초); 긴 정지 패널로 GOP가 긴 파일은 더 벌어질 수 있음 ② 긴 1080p ProRes(all-intra)는 1코어 그대로이고 거친 띠도 없음 — FL106 크기의 1080p ProRes 애니매틱이면 720p보다 약 2.5배 더 걸릴 것(측정 안 함) ③ 옵션 없는 띠 ffmpeg가 CPU를 다 쓰므로 쉬는 때 다른 무거운 일(OCR·내보내기 — 이 창은 모름)과 겹치면 나눠 씀(채움기와 같은 성질) ④ 거친 띠 줄 '건너뜀'은 긴 파일만(스펙 §3.1과 다름 — 간격 1이면 줄 없음: 짧은 파일마다 줄이 늘고 기존 시험의 '기록 없음' 단언을 지키려고) ⑤ 패킷에 pts가 없는 원시 스트림(.264 등)은 거친 띠 실패 기록 뒤 정확한 띠만 ⑥ 재생 게이트는 이 Mac 한 대·판 수가 적음(9판·3판) — 1080p H.264 통과는 cv2 재생에서만 잼 ⑦ Windows는 CI(시험)만 — 실기 미확인 ⑧ 1080p 기본 스레드는 허용 목록(`LONG_GOP_FULL_THREADS_CODECS` = h264)만 — hevc·vp9·av1 등 재생 게이트를 안 잰 코덱의 긴 1080p는 1코어 그대로(양성 증거로만 켬, Ruling 26 — 막는 목록이던 때 `ALL_INTRA_CODECS` 밖의 all-intra가 1080p에서 기본 스레드로 가던 구멍도 사라짐); 거친 띠 판단은 그대로라 `ALL_INTRA_CODECS` 밖 코덱은 패킷 스캔이 파일 전체를 읽은 뒤에야 K × 4로 가름 ⑨ 짧은(500장 이하) 1080p H.264는 헤더를 읽지 않아 1코어 그대로 — 1~2초로 추정(측정 안 함)
- 시험: 새 파일 `tests/test_hover_keyframes.py`, `test_hover_strip`(원본 크기·크기 × 코덱 스레드 규칙 — 1080p는 허용 목록 h264만)·`test_hover_strip_builder`(거친 패스·헤더 코덱으로 명령 정하기·stop 규칙 — `test_command_shape`·`test_threads_option_follows_constant`는 4K 원본으로, `test_stop_kills_process_and_thread`는 '띄웠다면 거둠'으로 고침)·`test_player_hover_thumbs`(거친 띠 조회·기록·진짜 워커 긴 H.264)에 더함, 시험 도우미 `prores_clips.make_numbered_h264`·`conftest.make_video`의 `video_args`

### 2026-11-10 (와이프 드래그 뒤 B 검게 남음 — is_dragging 표지가 놓을 때 안 풀림)
- **증상**(사용자 보고 — 내부 인수인계 기록(2026-10-12)에는 '고치지 않은 기존 버그'로 남아 있던 것): 와이프를 켜고 메인 시간 슬라이더를 끌었다 놓으면 B 칸이 검게 남음
- **원인**: `VideoPlayer.is_dragging`은 `on_slider_moved`(드래그 미리보기)가 True로 두고 `on_slider_value_changed`(valueChanged)만 False로 되돌림. 그런데 드래그 미리보기(`_update_ui_fast`·`_ultra_fast_ui_update`)가 슬라이더 값을 `blockSignals`로 먼저 써 두므로 Qt가 뒤이어 `setValue(position)`을 해도 값이 같아 valueChanged가 오지 않고, 메인 슬라이더의 `sliderReleased` 처리 `sync_audio_on_release`는 표지를 건드리지 않아 놓은 뒤에도 True로 남음(다음 클릭·휠까지). 오버레이 슬라이더는 `on_overlay_slider_released`에서 이미 되돌리고 있었음. **발견 경위**: 슬라이더 호버 썸네일의 '쉬는 때' 판정이 이 표지 때문에 멈춰(드래그를 한 번 놓은 뒤 연 모든 파일에서 띠가 안 생김 — 위 `player_hover_thumbs.py`) 드러남. 그래서 그 판정은 지금도 `is_dragging`을 보지 않고 `isSliderDown`·위치 변화만 봄
- **고침 ①(표지)**: `player_playback.py`의 `sync_audio_on_release` 맨 앞(`if self.cap_a:` 안 첫 문장 — 놓을 때의 정확한 이동 앞이라 그 이동의 그림이 B를 다시 그림)에 `self.is_dragging = False` 한 줄
- **영향 범위**(표지를 보는 세 곳): `_update_ui_after_seek`(표지가 서 있으면 와이프 B를 None으로 그림 — 놓을 때의 이동 첫 그림이 B 없이 나갔다가 이어 `update_frame`이 B를 다시 그림), `update_frame`(OCR 검토 창이 열려 있으면 최소 갱신 — B·오버레이 생략), `optimize_for_4k`(자동 모드에서 GPU 길 건너뜀)
- **둘째 원인과 고침 ②(캐시 미적중 드래그 — 같은 PR에서 이어 고침, Ruling 19·20)**: 캐시에 없는 자리로 끌면(처음 훑는 구간 — 긴 영상에서는 거의 이쪽) 미리보기(`_quick_preview_seek`)가 캡처를 목표로 옮기고 와이프 B 동기화는 통째로 건너뛰어 `frame_b`를 None으로 둠. 놓을 때는 캡처가 이미 목표 곁(차이 ≤ 5장)이라 `sync_audio_on_release`가 이동을 안 해 B를 아무도 안 맞추고 그림도 0번 — 표지(①)를 풀어도 B 칸이 검게 남음(offscreen 하니스·48장 mp4(cv2)·와이프 켠 실제 `VideoPlayer`에서 고치기 전·①만 한 뒤 모두 잼: 놓은 뒤 그림 0번, ←/→(`_seek_direct_fast` → `_update_ui_fast`)는 A만 읽어 그림 4번 모두 B 없음, 슬라이더 클릭(`_precise_seek`)에서만 돌아옴 — 실제 앱 눈 확인 전). 고침 두 규칙(둘 다 `sync_audio_on_release`의 이동 판정): **(a) 와이프에 B가 있으면(`cap_b`·`wipeEnabled`) 정밀 이동의 허용 오차를 5장 → 0으로**(`tolerance` — 와이프가 아니면 그대로 5장이라 `test_drag_release_seek`의 '캡처가 제자리면 아무것도 안 읽음' 등은 변화 없음). 까닭(리뷰 M1): 캐시 적중 뒤 캡처(c)는 그림(t)과 다른 자리라 B만 t에 맞추면 `update_frame` 끝의 `update_position_info`가 캡처 c 기준으로 슬라이더·Current·오버레이 슬라이더를 c로 되돌려 그림은 t인데 슬라이더·라벨이 최대 5장 튀고, A 캡처(c+1)·B 캡처(t+1)가 갈려 이어지는 와이프 재생이 |c−t|장 어긋남 — 정밀 이동(`_precise_seek`)은 A 캡처·B·슬라이더·라벨을 함께 t로 맞춤. **(b) 정밀 이동이 안 도는 놓기**(와이프에서 캡처 == 목표 — 캐시 미적중 드래그)는 `elif`: **`frame_b`가 None이거나 B 캡처가 목표가 아닐 때만** B를 `target_frame_idx`에 읽고(`seek_to_frame`의 B 동기화와 같은 모양, 못 읽으면 None) `update_frame()`으로 다시 그림. B가 이미 그 자리면 읽지도 그리지도 않음(리뷰 M2) — 평범한 클릭(누를 때 `valueChanged` → 정밀 이동이 A·B를 맞춤)·오버레이 슬라이더 놓기(`_overlay_slider_final_seek`가 B를 맞춘 뒤 `sync_audio_on_release`를 또 부름). (a)의 모서리(재리뷰 Low): `_precise_seek`가 반환값이 없고 끝에서 3장째(목표 ≥ 총 − 3)는 `_seek_conservative`의 기존 가드(`목표 == cap_a의 POS` — POS는 '다음에 읽을 번호'라 A가 목표 − 1에 있을 때 참)가 이동 없이 False를 돌려주므로, 놓는 쪽이 이동 뒤 `cap_a.get(POS) − 1 != 목표`면(와이프일 때만) `_seek_direct`로 A 캡처·B·슬라이더·라벨을 함께 맞춤(기존 탐색 코드는 안 바꿈 — 안 맞추면 그림만 목표이고 B가 옛 장·A 캡처가 한 장 앞). 마지막 프레임 길(`_seek_to_last_frame`)은 그대로. 대가: 와이프를 켠 채 캐시에 맞게 끌다 놓으면(캡처가 목표와 다름) 5장 안이어도 직접 이동 한 번(A·B 한 장씩)
- **시험** `tests/test_drag_flag_release.py`(여덟 — 진짜 마우스 드래그 누름→`QMouseEvent` 이동→놓음, 놓기 직전 표지 True를 단언): ① 놓은 뒤 표지 False / 마지막 움직임이 캐시에 맞아 놓을 때 이동이 도는 드래그에서 놓은 뒤 그림 어디에도 B가 빠지지 않음(마지막 그림만 보면 옛 코드도 통과 — 이어 `update_frame`이 B를 다시 그려서 — 모든 그림을 봄) / `sync_audio_on_release` 단독 호출도 표지를 풀음. ② 캐시 미적중 드래그를 놓으면(A·B 같은 클립) 마지막 그림에 B가 있고 `frame_b`·`frame_a` 평균 밝기가 같음(같은 장). ③ 와이프 + 캐시 적중 + 캡처와 5장 차이로 놓기(`setSliderPosition` 20→25→20): 슬라이더 20·Current 21·A/B 캡처 모두 20 ④ 평범한 클릭을 놓을 때 `cap_b` read·set 0·그림 0 ⑤ 오버레이 슬라이더 놓기에서 B read·set 각 1번 ⑥ 끝에서 3장째(48장 클립의 45번)로 캐시 적중 뒤 A가 목표 − 1에 있는 놓기(`setSliderPosition` 45→44→45 — 정밀 이동이 아무것도 안 하는 모서리)에서 놓은 뒤 B가 그려지고 슬라이더 45·Current 46·A/B 캡처 모두 45. 고치기 전 ①의 셋 모두 실패(표지 True 그대로·첫 그림 `(A, B 없음)`), ①만 한 뒤 ②가 실패(놓은 뒤 그림 0번), (a)·(b) 전 ③④⑤가 실패(슬라이더가 25로 튐·클릭 놓기에 B 읽기 1번·오버레이 놓기에 B 읽기 2번), 직접 이동 폴백 전 ⑥이 실패(놓은 뒤 그림 0번)

### 2026-11-10 (슬라이더 호버 썸네일 — DJV식 미리보기, Settings 켜기/끄기)
- **요청**(사용자, 2026-11-09·10): 시간 슬라이더 위에 커서를 올리면 그 자리 프레임의 작은 그림이 커서 위로 살짝 뜨고 커서를 따라 바뀌게 — DJV처럼(그림 + 아래 번호), 클릭하기 전에 필요한 그림을 찾게. 4K 재생 매끄러움이 최우선(호버 때문에 재생이 흔들리면 실패). 지금의 드래그 미리보기는 재생 캡처를 탐색해(본화면이 튀고 파이프 스트림·링이 깨짐) 호버에 쓸 수 없어 **재생 캡처와 무관한 별도 출처**로 만듦
- **사용자 결정**: 방식은 'A 미리 띠'(쉴 때 뒤에서 만들어 RAM에 두고 호버는 꺼내 보이기만 — 온디맨드 디코드는 고르지 않음), 지금 연 파일 하나 분만 RAM(바꾸면 버림·디스크에 안 씀), 짧은 렌더 샷·긴 애니매틱 둘 다(장수가 많으면 띄엄띄엄 자동), 이미지 시퀀스는 이번엔 제외('영상만 먼저'), 띠가 아직 없는 구간은 번호 + 빈 상자, Settings에서 켜고 끔, 크고 긴 파일은 '크기 상한'. 설계·계획은 내부(비공개) 저장소의 `docs/superpowers/specs/2026-11-10-slider-hover-thumbnails-design.md`·`plans/` 같은 이름
- **규칙**(위 '주요 파일'의 `player_hover_thumbs.py`와 그 아래 `hover_strip`·`hover_strip_builder`·`slider_preview`): 띠는 최대 500장(넘으면 `ceil(N/500)` 간격), 그림은 **320×320 상자 안**(가로 영상 폭 320·세로 영상 높이 320 — 실행 중 정함: 16:9 500장 86MB, 어떤 비율이든 ≤ 154MB), **4GB 넘는 파일은 계획만**(번호 + 빈 상자 + 기록 한 줄 — 실행 중 정함, 스펙 §5.9 ⑦). 열린 지 **1.0초** 뒤(처음 0.5초 — 3차 측정 전 Ruling 14) **쉬는 때만** ffmpeg 하나(디코드·축소 1코어 — `-threads 1 -filter_threads 1`; 쉬는 때 = 재생 아님·두 슬라이더 안 눌림·A의 위치 `cap_a.get(POS_FRAMES)`(50ms마다 읽음)가 0.3초 동안 그대로 — 기존 `is_dragging` 표지는 드래그 뒤 True로 남을 수 있어 보지 않음, 실기 보고로 실행 중 정정), 바빠지면 **psutil로 ffmpeg 프로세스를 정지**(파이프를 안 읽기만 하면 디코드 중인 장을 마저 디코드해 재생 첫 틱과 겹침), 쉬면 재개 — 재생 중 틱은 재생 캡처의 `get`·슬라이더를 보지 않고 정지 표지만(워커는 값이 바뀔 때만 psutil), 다음 파일을 여는 동안도 옛 띠 ffmpeg를 정지(`open_file` 맨 앞 삽입 한 줄). 호버 번호는 두 슬라이더 모두 **메인 값→프레임 식**(오버레이 클릭도 `sync_audio_on_release`를 거쳐 메인 식으로 착지 — 실행 중 정정, 스펙 §5.4), x → 값은 **Qt의 클릭 식 그대로**(핸들 폭 −1 보정 없음). A가 `_release_side` 밖(job 불러오기)에서 놓여도 옛 파일의 번호·그림이 뜨지 않게 조회마다 확인(낡은 계획 가드) + job 바꾸는 자리에 닫기 한 줄. 실패는 기록 + 오류 창 파일마다 1회(이 창이 떠 있는 동안 실패한 파일 모두 기억, 다시 시도 없음) — **잘린 파일**(종료 코드 0 + stderr 오류 글 — 복사·렌더가 진행 중인 NAS 파일)은 실패가 아니라 채운 데까지 done + 경고 기록(창 없음). Settings → 슬라이더 썸네일(prefs.json `slider_thumbnails`, 기본 켬 — 위 '설정 파일'), 깨진 prefs는 켤 때 경고 1회 + 이 세션 끔(깨진 JSON이면 '파일을 고치거나 지운 뒤 다시 켜면 켜집니다'). 메인 슬라이더의 툴팁 'Position'은 지움. 기존 파일은 삽입 몇 줄만(`player_base`·`player_playback`·`app`; 재생·탐색·그리기 코드는 글자 그대로)
- **실측**(이 Intel Mac iMac20,2, 4K ProRes 4444 334장 NAS 파일 — 네이티브 VideoToolbox `hw=no`, GL; 내부 `docs/superpowers/records/2026-11-10-slider-hover-thumbnails/measure.md`): 띠 만들기 시작 0.5초 뒤 Play(켬) 대 기능 끔, 프로세스마다 한 번 번갈아 각 6판(3차는 10판) — `[측정]`은 한 판(3차 틱만 3번 — 14.81초)을 빼고 모두 333장 13.88초(24.0fps). **1차**(ffmpeg 기본 스레드 — 이 Mac 16개, 11fbeed): 끔 43~58ms·끊김 0, 켬 44~104ms·끊김 0~2(104ms 판은 측정 도중 다른 파이썬 프로세스가 끼어든 판 — 빼도 5판 중 3판이 69·73·78ms·끊김 1) → 게이트 실패. 진단을 단 판의 끊김은 모두 Play 뒤 0.50~0.53초(12·13번 장)이고 ffmpeg는 이미 Play 뒤 26~37ms에 정지해 있었으며, 앱 코드 없이 'Play 전 0.5초 ffmpeg 디코드 + Play 때 정지'만 재현해도 3판 중 1판이 같은 자리(0.565초, 64ms) → Play **직전**의 16스레드 디코드 버스트로 보고(추정) `FFMPEG_THREADS = 2`를 넣음(Ruling 11 — 2c1ea88). **2차**(`-threads 2`, f34e79a — 같은 하니스·프로토콜): **끔 43~69ms·끊김 0~1**(1판이 Play 뒤 0.49초·12번 장에서 69ms — 띠 없이도 이 자리의 끊김이 남), **켬 44~131ms·끊김 0~3**(4판은 44~55ms·끊김 0, 2판이 96ms·3번(0.56·5.6·7.7초)과 131ms·2번(1.2·1.5초)) → **게이트(켬이 끔의 범위 안 — 스펙 §5.3) 여전히 실패 — 미해결**. **3차 구성**(최종 리뷰 수정 묶음 — Ruling 14): 디코드·축소 1코어(`-threads 1 -filter_threads 1` — `-threads`는 디코더만 묶고 `-vf scale`은 CPU 수만큼 slice 스레드였음: 번들 ffmpeg 프로세스 스레드 `-threads 2`만 54개 → 둘 다 1이면 22개)·`START_DELAY_S` 1.0초·재생 중 틱은 `get` 없이 정지 표지만. **3차**(b7a14b6 — 같은 하니스, off는 연 뒤 1.55초에 Play(켬의 '열기 → Play' 1.50~1.55초에 맞춤), 켬·끔 각 10판 + '끔 + 쉬는 때 틱만'(기능 켬, 워커만 아무것도 안 하는 대역 — ffmpeg 없이 타이머·틱만) 6판, 읽기 전용 리뷰어 에이전트가 함께 돎): **끔 44~145ms·끊김 0~1**(8판 44~58ms·끊김 0, 2판 84ms(0.13초)·145ms(9.3초)), **켬 44~111ms·끊김 0~1**(5판 44~52ms·끊김 0, 5판 77~111ms·끊김 1 — 4번은 재생 중간 1.7~9.9초, 'Play 뒤 0.5초' 자리는 1번), **틱만 44~608ms·끊김 0~7**(3판 44~45ms, 2판 68·95ms, 1판은 ffmpeg 없이도 10.6~12.2초에 608ms 포함 7번 — 이 Mac 쪽 멈춤) → **게이트(켬이 끔의 범위 안 — 스펙 §5.3) 범위 기준 통과**(켬이 범위 밖인 판: 1차 5판 중 3판 → 2차 6판 중 2판 → 3차 10판 중 0판). 단서: 끔의 범위가 그 2판으로 넓어졌고 끊긴 판 비율은 켬 5/10·끔 2/10·틱만 3/6 — 이 표본으로는 켬과 끔의 차이를 가르지 못함(Fisher p = 0.35, 최대간격 Mann-Whitney p = 0.54). 세 차례 모두 정지는 뜻대로: 재생 중 ps `T 0.0`·재생 중 ffmpeg CPU 0.0초(켬 23판 모두), 3차 정지된 ffmpeg의 RSS 167,476~183,148 KB(약 164~179 MiB — 띠 저장소 57.7MB와 따로) — 넘친 틱은 재생 중 ffmpeg의 CPU 탓이 아님. 띠 완성: 쉬기만 하면 1차 **5.7·6.5초** → 2차 **20.0·19.7초**(334장 — 스레드 2개라 약 3배) → 3차 **38.3·38.2초**(1코어), Play를 끼우면 기록 줄 1차 20.1~21.0초 → 2차 34.5~34.9초 → 3차 52.3~53.7초(멈춘 시간 포함 — 재생이 끝난 뒤 1차 5.7~6.6초·2차 20.1~20.5초·3차 37.9~39.3초에 다 참). 화면 대조 `ci/screenshot_check.py`(main 6dab053 대 이 브랜치): **PNG 9/9 바이트 동일**, 위젯 트리는 8장면(OCR 검토 창 빼고)에서 Settings 메뉴의 새 항목 `슬라이더 썸네일` 하나만. 시험(bebc77e에서 이 Mac 전체 실행 17분 27초): 125개 파일·수집 3,116개 — 3,068 통과·46 건너뜀·알려진 플레이크 둘(`test_reader_keeps_up_while_main_thread_holds_gil`·`test_app_exits_cleanly_while_shared_config_load_runs`) 실패 → GIL 부하 시험은 따로 돌리면 통과, 종료 시험(자식 종료 코드 −11)은 따로 돌려도 간헐 실패 — main에서도 같음, `compileall` 통과, `runtime_globals` unresolved 0(함수 1,958·모듈 92), 끝난 뒤 ffmpeg 프로세스 없음. `check_frozen_imports.py`는 빌드 앱이 있어야 돌아 이번엔 안 돌림 — 소스 쪽(새 모듈 넷을 소스 import가 다 부름)은 `test_check_frozen_imports`가 봄
- **알고 둔 한계**(스펙 §5.9): ① Windows 파이프 전체 캐시 채움기와 띠 워커가 같은 파일을 쉴 때 동시에 디코드할 수 있음(4K 약 7초 CPU를 나눠 씀 — 둘 다 재생이 시작되면 멈춤; 후보: 채움이 끝난 뒤 RAM의 프레임을 줄여 띠를 만들면 디코드 0) ② 긴 파일은 띄엄띄엄이라 그림이 커서 프레임과 최대 `step/2`장 다름(20분 24fps 애니매틱 = 간격 58장 ≈ 1.2초) — 번호는 정확 ③ ffmpeg가 세는 장수와 재생 캡처의 장수가 다른 파일(VFR h264 등)은 뒤쪽 샘플이 비거나 그림이 조금 어긋남(기록에 채운 장수) ④ 같은 깨진 `prefs.json`이면 켤 때 창이 셋까지(디코더(Mac)·화면 그리기(Windows)·슬라이더 썸네일), 깨진 JSON이면 메뉴로도 켜지 못함 ⑤ 쉬는 때 판정은 이 창의 재생·드래그·탐색만 봄(다른 창·다른 앱·OCR·씬 감지·내보내기 워커는 모름 — 채움기와 같음) ⑥ 레티나에서 320px 그림은 2배 확대라 조금 부드러움(`THUMB_WIDTH` 하나로 조절 — 메모리는 제곱으로 늚) ⑦ 4GB 넘는 파일(긴 ProRes mov)은 번호 + 빈 상자만(후보: 샘플마다 `-ss`로 한 장씩 — 파일 일부만 읽음) ⑧ 정지된 ffmpeg가 재생 동안 NAS 파일 핸들을 쥐고 있음 — 그 사이 공유가 끊기면 재개 뒤 읽기 오류 → 실패 길(창 1회) ⑨ (위 실측) 띠를 만드는 중의 Play: 1·2차(기본 16스레드·`-threads 2`)에서는 켬 판의 일부가 끔의 범위 밖(69~131ms)이었고, 3차 구성(1코어·처음 띄우기 전 1.0초·싼 재생 틱)에서는 켬 10판이 모두 끔의 범위(44~145ms) 안 — 범위 기준 통과. 다만 끊긴 판 비율은 켬 5/10·끔 2/10(표본이 작아 차이를 가르지 못함 — p = 0.35)이라 '띠가 재생에 영향 0'을 보인 것은 아님; 넘친 틱은 재생 중 ffmpeg의 CPU 탓이 아님(정지 확인). 대가로 띠 완성이 쉬기만 해도 4K 334장 약 38초(1차 약 6초) ⑩ Windows에서 띠 ffmpeg가 정지된 동안 앱이 비정상 종료하면 ffmpeg.exe가 정지된 채 남아 NAS 파일 핸들을 쥘 수 있음(그 파일의 이름 바꾸기·지우기가 막힘) — 작업 관리자에서 끝낼 것; 후속 후보: Job 객체(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` — 앱이 죽으면 OS가 자식을 끝냄, Windows 실기 없이 넣지 않음)
- **눈 확인 몫**(offscreen 시험이 닿지 않음 — 사용자): 실제 macOS·Windows에서 ToolTip 팝업이 뜰 때 메인 창에 WindowDeactivate가 가지 않는지(가면 뜨자마자 숨음)·팝업이 커서·슬라이더와 겹쳐 Leave로 깜빡이지 않는지·화면 가장자리에서 안으로 밀리는지, Mac 네이티브 메뉴 막대에서 Settings → 슬라이더 썸네일의 툴팁이 보이는지, 레티나에서 그림이 볼 만한지, 밝은 테마에서도 어두운 창
- **뒤따른 고침(PR #35 — merge 뒤 Windows CI)**: ① 도중 멈춤 시험이 Windows에서 실패 — Windows의 psutil `status()`는 모든 스레드의 대기 사유가 Suspended일 때만 STOPPED라, 파이프가 차서 WriteFile에서 막힌 ffmpeg 스레드가 있으면 정지돼 있어도 running으로 보임(CI run 42768144735; 띄운 직후 정지는 맞게 보임). 기능 결함이 아니라 확인 방법의 문제라 시험을 `evidence` 매개변수로 — `status`는 Windows에서 skip, `drain`(파이프를 비워 한 장도 더 오지 않음 + 비우는 도우미 생존)은 모든 OS. ② Windows CI의 종료 크래시(0xC0000005 — 자식 `VideoPlayer` show·close 뒤)·이 Mac의 종료 세그폴트 플레이크(`test_app_exits_cleanly_while_shared_config_load_runs` -11)를 두고 리뷰 가설 'parent 없는 최상위 팝업이 QApplication보다 늦게 지워짐' → 팝업에 parent를 줌: Mac·Linux는 플레이어 창(이 Mac 18/24 → 7/24 실패 — 줄었지만 남음, main에도 있는 플레이크), Windows는 Qt 툴팁과 같이 desktop screen(창을 raise하지 않게) — Qt 5가 Desktop 종류 parent를 비우므로 Windows 팝업은 parent 없는 창(실측·시험 고정). 그래서 **창을 닫으면 필터를 떼고 팝업을 즉시 지움**(`_hover_thumbs_destroy` — 모든 플랫폼 같은 길, Windows는 parent가 없어 이 길이 유일한 정리; 이 Mac에서는 parent 덕에 이미 지워지던 것이라 플레이크 수치는 같은 때 번갈아 잰 16:16에서 지우기 전 6·지운 뒤 4로 차이 없음). parent 창의 테마 시트가 내려와도 인라인 시트가 이기고 번호 글꼴 종류만 앱 글꼴
- 시험 새 파일 다섯(위 '테스트 전략'의 '슬라이더 호버 썸네일'). 기존 시험 파일은 `test_mac_native_gate`의 도우미 `launch_until_window`에 새 로더를 끄는 한 줄만(그 모듈은 디코더 설정만 봄 — 단언 그대로)

### 2026-11-09 (BB_Animatic — job 바로 아래 Quicktime도 목록에)
- **증상**(사용자 보고): BB_Animatic → season15 → F54_Music Video를 고르면 목록이 빔
- **원인**: BB_Animatic 규칙은 `job/<씬>/Quicktime/*`(F01~F15 — 예: `F14/SEQ18B/Quicktime`)만 봤는데 F54는 씬 폴더 없이 `F54_Music Video/Quicktime/FASA54_SQ01_FNL-YESON.mov`
- **고침**: `video_list.scan_job`의 BB_Animatic 갈래에 job 바로 아래 `Quicktime`을 더함(BM_Animatic의 `ANIMATIC`과 같은 모양). 다른 작품은 이 갈래를 지나지 않음
- **실데이터 대조**(이 Mac에서 BB_Animatic 74개 job 전부, 고치기 전·후 코드): 바뀐 job은 F54 하나(영상 0 → 1개), 나머지 73개 job은 목록이 글자 그대로(영상 합 1,448 → 1,449)
- 시험 `tests/test_video_list.py`(job 바로 아래 Quicktime·그 아래 하위 폴더는 아님·예전 모양 그대로·다른 작품 다섯은 job/Quicktime을 보지 않음)
### 2026-11-09 (Windows 소리 — K-Lite 필요 안내, 소리 진단 기록)
- **보고**(사용자): Windows 11에서 소리가 나오지 않음, Windows 10은 정상. 원인 미확인 — 기록에 아무것도 없었음: 빌드 앱은 Qt(C++) 경고를 기록 파일로 보내지 않았고(소리 백엔드가 실패를 알리는 길), QMediaPlayer의 오류·상태 신호도 받지 않았음
- **넣은 것**(고치기 전에 증거부터 — 다음에 어느 PC에서 소리가 안 나도 기록으로 바로 알게): `qt_messages`(Qt 경고 → 기록)·`media_player_log`(출력 장치·재생 가능성·백엔드 환경 변수·Windows는 실제로 불러온 백엔드 DLL, 파일마다 상태·소리 트랙·오류 → `[소리]` 줄). 동작은 그대로
- **원인(사용자 PC에서 확인)**: Qt 5의 Windows 기본 소리 백엔드 DirectShow는 mp4·mov를 혼자 열지 못함 — 소리가 나던 Windows 10 PC에는 K-Lite Codec Pack 18.4(LAV Splitter·LAV Audio)가 깔려 있었고, Windows 11 PC에 K-Lite를 깔자 소리가 남. 유튜브(브라우저)는 Windows 11에서도 소리가 났음(장치·드라이버 정상). 소리가 있는 파일: 애니매틱 mp4(H.264 + AAC)·립싱크/레이아웃 mov(H.264·ProRes + PCM `sowt`) — 렌더 ProRes(FL·KOTH)는 소리 트랙이 없음
- **Media Foundation으로 바꾸기는 하지 않음**: Windows 11(K-Lite 깔린 채)에서 `QT_MULTIMEDIA_PREFERRED_PLUGINS=windowsmediafoundation`으로 켜자 소리가 나지 않았음(원인 미확인 — 그 상태의 기록은 받지 못함; Windows 판이 N인지·실제 불러온 백엔드는 확인 전). 사용자 결정: 'K-Lite를 쓰는 게 편하다 — 오디오 코덱이 다양해서 K-Lite가 효율적' → README '준비 사항'에 Windows는 K-Lite Codec Pack(Basic) 필요, '트러블슈팅'에 기록 줄 읽는 법. 다시 볼 때의 후보: 앱에 든 ffmpeg로 소리를 풀어 QAudioOutput으로(코덱 무관 — 소리 맞추기·탐색을 다시 짜야 함)
- 시험 `tests/test_audio_log.py`(Qt 메시지 줄 모양·sys.stderr로·빌드 앱 기록 파일에 남음·쓰기 실패에도 예외 없음, 출력 장치 줄·상태/오류/소리 트랙 줄·창의 재생기에 붙음)
### 2026-11-09 (B 키 오버레이 — 숫자 폭이 같은 글꼴, 상자는 글자에 딱 맞춤)
- **증상**(사용자 보고, PR #30을 넣은 앱): 상자는 멈췄지만 재생 중 프레임 숫자가 떨림, 번호가 짧으면 오른쪽에 빈자리
- **원인**: Mac 네이티브 아이템 길의 글꼴이 앱 기본 글꼴(SF)이라 숫자 폭이 다름('1' 29.3px 대 '0' 39.9px, 60px Bold) — 프레임마다 글자 폭이 달라져 '/전체'가 움직였음. PR #30은 상자만 가장 넓은 번호에 맞춰 고정해 글자 안의 떨림은 남고 빈자리가 생겼음
- **고침**: 아이템 글꼴을 `OVERLAY_FONT_FAMILIES`(Helvetica Neue — 모든 Mac, 없으면 Arial; 둘 다 숫자 폭이 같음 — 이 Mac에서 잼)로, 상자는 글자에 딱 맞춤(사용자 결정 — PR #30의 상자 고정·`box_width`를 되돌림): 같은 자릿수 안에서는 글자 폭·상자 끝이 그대로, 자릿수가 바뀔 때(9→10·99→100)만 한 칸. 좁은 프레임에서 줄이는 글자 크기는 계속 '자리 잡을 글'로(번호와 무관). 굽는 길(cv2 Hershey — Windows·Mac ffmpeg 방식)은 원래 숫자 폭이 같아 상자 규칙만 예전대로
- 시험 `tests/test_overlay_box_steady.py`(글꼴이 그 글꼴들을 고름·숫자 폭이 같음·같은 자릿수에서 글자 폭이 같음 — 그 글꼴이 없는 시험 환경은 사유와 함께 건너뜀, 상자가 글자에 딱 맞음·같은 자릿수에서 제자리), `test_native_overlay_item`의 상자 오른쪽 기대를 글자 끝 + pad로

### 2026-11-09 (B 키 오버레이 — 흰 상자 오른쪽 끝 고정)
- **증상**(사용자 보고, 스크린숏은 Mac 네이티브 아이템 길): B 모드에서 프레임 번호가 1·2·3 자리로 바뀌면 흰 상자 오른쪽 끝이 계속 움직여 떨려 보임
- **원인**: 두 그리기 길 모두 상자 너비를 지금 글자의 너비로 정함 — 굽는 길(cv2 Hershey, Windows·Mac ffmpeg 방식)은 숫자 폭이 같아도 자릿수가 바뀌고, 아이템 길(Qt 글꼴 — Mac 시스템 글꼴)은 숫자 폭마저 다름('1' 29.6px 대 '0' 40.1px, 60px Bold). 좁은 프레임에서 줄이는 배율도 지금 글자로 정해 글자 크기까지 떨렸음
- **고침**: 상자 너비·줄이는 배율·Qt 글꼴 크기를 '자리 잡을 글'(`overlay_text_layout.overlay_reserve_text` — 'Frame: n/N'의 n을 N 자릿수만큼 그 글꼴에서 가장 넓은 숫자로)로 정함 — 굽는 길은 `OverlayLayout.box_width`, 아이템 길은 `max(지금 글자, 자리 잡을 글)`의 Qt 너비. 글자는 왼쪽 맞춤 그대로(번호가 짧으면 오른쪽에 빈자리). 상자의 왼쪽·위·아래와 기준선은 그대로
- 시험 `tests/test_overlay_box_steady.py`(자리 잡을 글 규칙·가장 넓은 숫자·4K/1080p/360p/좁은 600×1080에서 배율·상자 너비가 번호 1~166 내내 같음·구운 흰 상자 오른쪽 끝 열이 같고 글자는 늘 안·아이템 상자 오른쪽 끝과 글꼴 크기가 같음 — 두 길을 옛 규칙으로 되돌리면 실패함을 확인), `test_native_overlay_item`의 상자 오른쪽·줄이는 배율 기대를 새 규칙으로
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
- **남은 같은 종류(이 수정의 범위 밖)**: 모든 전환의 기본 비용(ffprobe·ffmpeg 시작·NAS에서 첫 4K 프레임 — 이 Mac 파이프 4K 0.69~0.76초, 11-05), 선택 재생이 아닌 열기(사이드바 클릭·↑↓)의 `stop_video` → 옛 캡처 `seek_to_frame(1)`(파이프면 놓을 캡처에 ffmpeg를 한 번 더 띄움 — `movie_pipe_source.py` 항목 '알고 둔 한계' ⑧) — **이것은 2026-11-12에 없앰**. 후보: 다음 파일 미리 열기
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
