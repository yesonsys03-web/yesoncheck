"""메인 창의 화면 글자 표 — 키 하나에 한국어·English 글 (Qt 없음).

화면에 보이는 글자(단추·툴팁·메뉴)는 코드에 직접 적지 않고 `text("키")`로 읽는다. 지금 언어는 이 프로세스에 하나
(`set_language` — 창마다 프로세스가 하나). 언어를 고르는 메뉴와 저장은 다음 단계라 지금은 늘 기본(한국어).

글을 더하거나 고칠 때는 **두 언어를 함께** — `missing()`이 빠진 키를 알려 주고 시험이 그것이 비었는지 본다.
글 안의 `{이름}`은 `text(키, 이름=값)`으로 채운다. 단추·메뉴 이름에 붙는 단축키 표기(`(Space)`)도 글에 적는다.
"""

LANGUAGES = ("ko", "en")
DEFAULT_LANGUAGE = "ko"

TEXTS = {
    # 재생 줄 (transport_bar)
    "transport.first": {"ko": "처음으로 (Home)", "en": "Go to start (Home)"},
    "transport.prev": {"ko": "한 장 뒤로 (←, ,)", "en": "Step back one frame (←, ,)"},
    "transport.play": {"ko": "재생 (Space)", "en": "Play (Space)"},
    "transport.pause": {"ko": "일시정지 (Space)", "en": "Pause (Space)"},
    "transport.next": {"ko": "한 장 앞으로 (→, .)", "en": "Step forward one frame (→, .)"},
    "transport.last": {"ko": "끝으로 (End)", "en": "Go to end (End)"},
    "transport.loop": {"ko": "반복 재생 (L)", "en": "Loop playback (L)"},
    "transport.frame": {"ko": "프레임 번호 — 숫자를 치고 Enter", "en": "Frame number — type a number and press Enter"},
    "transport.volume": {"ko": "볼륨 {percent}%", "en": "Volume {percent}%"},
    # 재생 줄의 fps 칸 — 재생 코드가 넣는 규약 글('재생: 24 FPS · 실제 23.8'·'재생: 정지' — 번역하지 않음)에서 보일 글만
    # (transport_bar.shown_fps). 'real'은 '실제'보다 넓지 않은 낱말로 골랐다 — 칸의 너비 본보기는 두 언어 중 넓은 쪽이라
    # 더 긴 낱말(actual)이면 한국어 화면의 재생 줄 자리가 달라진다.
    "fps.actual": {"ko": "실제", "en": "real"},
    "fps.state.idle": {"ko": "대기", "en": "idle"},
    "fps.state.stopped": {"ko": "정지", "en": "stopped"},
    "fps.state.paused": {"ko": "일시정지", "en": "paused"},
    # 고른 영상 이어 재생(선택 재생)
    "playlist.end": {"ko": "이어 재생 끝내기", "en": "End playlist"},
    "playlist.end.tip": {"ko": "고른 영상 이어 재생을 끝내고 처음으로 돌아갑니다",
                         "en": "Ends playing the selected videos in a row and returns to the start"},
    "playlist.play": {"ko": "고른 영상 이어 재생", "en": "Play selected in a row"},
    "playlist.pause": {"ko": "이어 재생 일시정지", "en": "Pause playlist"},
    "playlist.play.tip": {"ko": "목록에서 고른 영상을 차례로 재생합니다 (Enter)",
                          "en": "Plays the videos selected in the list one after another (Enter)"},
    # 재생 줄의 도구 토글
    "transport.wipe": {"ko": "A|B 와이프", "en": "A|B Wipe"},
    "transport.wipe.tip": {"ko": "A와 B를 와이프로 견줍니다 (W)", "en": "Compare A and B with a wipe (W)"},
    "transport.wipe.x": {"ko": "X", "en": "X"},
    "transport.wipe.x.tip": {"ko": "좌우로 나눔 (X축)", "en": "Split left and right (X axis)"},
    "transport.wipe.y": {"ko": "Y", "en": "Y"},
    "transport.wipe.y.tip": {"ko": "위아래로 나눔 (Y축)", "en": "Split top and bottom (Y axis)"},
    "transport.annotate": {"ko": "주석", "en": "Annotate"},
    "transport.annotate.tip": {"ko": "수정 사항 주석 패널을 열고 닫습니다", "en": "Opens and closes the annotation panel"},
    "transport.ocr": {"ko": "OCR", "en": "OCR"},
    "transport.ocr.tip": {"ko": "OCR 패널을 열고 닫습니다", "en": "Opens and closes the OCR panel"},
    # 사이드바
    "sidebar.works": {"ko": "작품 선택", "en": "Select show"},  # 사용자 지시 2026-11-16 (예전 가운데 열의 글자는 'Yeson 작품')
    "sidebar.open_folder": {"ko": "폴더 열기", "en": "Open folder"},
    "sidebar.bookmarks": {"ko": "북마크", "en": "Bookmarks"},
    "sidebar.bookmark.add": {"ko": "북마크 추가", "en": "Add bookmark"},
    "sidebar.bookmark.manage": {"ko": "북마크 관리… (P)", "en": "Manage bookmarks… (P)"},
    "sidebar.refresh": {"ko": "새로고침", "en": "Refresh"},
    "sidebar.refresh.tip": {"ko": "목록 다시 읽기 (F5)", "en": "Reload the list (F5)"},
    "sidebar.mode.list": {"ko": "목록", "en": "List"},
    "sidebar.mode.thumb": {"ko": "썸네일", "en": "Thumbnails"},
    # 작품·시즌·job 콤보의 안내 항목(0번 — 골라도 아무 일 없음)
    "picker.work": {"ko": "작품선택", "en": "Select show"},
    "picker.loading": {"ko": "공유 설정 불러오는 중…", "en": "Loading shared settings…"},
    "picker.season": {"ko": "시즌선택", "en": "Select season"},
    "picker.job": {"ko": "job선택", "en": "Select job"},
    # 목록 아래 개수 줄 (sidebar_counts) — 영문은 하나일 때 낱말이 다름. 괄호 안의 'TK2 5' 꼴은 두 언어에서 같음(색을 칠하는 쪽이 읽음)
    "count.item": {"ko": "{count}개", "en": "{count} item"},
    "count.items": {"ko": "{count}개", "en": "{count} items"},
    "count.sequence": {"ko": "시퀀스 {count}개", "en": "{count} sequence"},
    "count.sequences": {"ko": "시퀀스 {count}개", "en": "{count} sequences"},
    "count.base": {"ko": "기본", "en": "Base"},  # 종류가 없는 파일의 묶음
    "count.no_version": {"ko": "없음", "en": "none"},  # 버전이 있는 파일과 같은 종류에 섞인, 버전 없는 파일
    # 정렬 단추 (탭 줄의 All 탭 옆 — sidebar_sort)
    "sort.button": {"ko": "정렬: {label} ▾", "en": "Sort: {label} ▾"},
    "sort.button.short": {"ko": "{label} ▾", "en": "{label} ▾"},
    "sort.button.tip": {
        "ko": "목록을 정렬합니다 — 이름·종류·버전·시간. Mov·Seq·All 탭에 함께 적용되고 선택 재생도 보이는 차례대로 재생합니다",
        "en": "Sorts the list — name, kind, version or time. Applies to the Mov, Seq and All tabs, and playing the selected "
              "videos in a row follows the order shown"},
    "sort.name": {"ko": "이름", "en": "Name"},
    "sort.kind": {"ko": "종류", "en": "Kind"},
    "sort.version": {"ko": "버전", "en": "Version"},
    "sort.time": {"ko": "시간", "en": "Time"},
    "sort.name.tip": {"ko": "이름 순서 (기본)", "en": "Name order (default)"},
    "sort.kind.tip": {"ko": "종류끼리 묶음 — 이름 끝의 OSAN·OSRO·HD 등. 묶음 안에서는 이름 순서",
                      "en": "Groups by kind — OSAN, OSRO, HD … at the end of the name. Name order within a group"},
    "sort.version.tip": {"ko": "버전·테이크끼리 묶음 — v01·v02·TK1·TK2 등. 묶음 안에서는 이름 순서",
                         "en": "Groups by version or take — v01, v02, TK1, TK2 …. Name order within a group"},
    "sort.time.tip": {
        "ko": "파일을 고친 시각이 최근인 것부터 — 다시 렌더한 영상이 위로. 다시 고르면 시각을 다시 읽습니다",
        "en": "Most recently modified files first — re-rendered videos move to the top. Choose it again to read the times again"},
    # Seq 목록의 항목 글과 툴팁 (sidebar_sequences)
    "seq.label": {"ko": "{base} ({first}–{last}, {count}프레임)", "en": "{base} ({first}–{last}, {count} frames)"},
    "seq.label.missing": {"ko": ", 빠짐 {missing}", "en": ", {missing} missing"},
    "seq.tip.folder": {"ko": "폴더: {folder}", "en": "Folder: {folder}"},
    "seq.tip.range": {"ko": "범위: {first}–{last} ({count}프레임)", "en": "Range: {first}–{last} ({count} frames)"},
    "seq.tip.missing": {"ko": "빠짐 {missing}프레임", "en": "{missing} frames missing"},
    # 썸네일 진행 막대 (만드는 동안만 보임 — %v/%m은 QProgressBar가 채움)
    "thumb.making": {"ko": "썸네일 생성 중: %v/%m", "en": "Making thumbnails: %v/%m"},
    "thumb.all_saved": {"ko": "썸네일 모두 디스크에 저장됨", "en": "All thumbnails are saved on disk"},
    "thumb.done": {"ko": "썸네일 생성 완료", "en": "Thumbnails done"},
    "thumb.stopped": {"ko": "썸네일 생성 멈춤 ({reason})", "en": "Thumbnails stopped ({reason})"},
    "thumb.stop.closed": {"ko": "창을 닫음", "en": "window closed"},
    "thumb.stop.list_changed": {"ko": "목록이 바뀜", "en": "list changed"},
    "thumb.stop.list_mode": {"ko": "목록 모드로 바꿈", "en": "switched to list mode"},
    # 목록의 우클릭 메뉴 — Mov
    "side_menu.open_a": {"ko": "비디오 A 열기", "en": "Open as video A"},
    "side_menu.open_b": {"ko": "비디오 B 열기", "en": "Open as video B"},
    "side_menu.merge": {"ko": "애니매틱 하나로 합치기", "en": "Merge animatics into one"},
    "side_menu.copy": {"ko": "파일 복사", "en": "Copy files"},
    "side_menu.thumbnails": {"ko": "썸네일 재생성", "en": "Regenerate thumbnails"},
    "side_menu.info": {"ko": "미디어 정보", "en": "Media info"},
    # Seq
    "side_menu.seq.open_a": {"ko": "비디오 A로 열기", "en": "Open as video A"},
    "side_menu.seq.open_b": {"ko": "비디오 B로 열기", "en": "Open as video B"},
    "side_menu.seq.export": {"ko": "선택한 시퀀스로 MOV 만들기…", "en": "Make MOV from selected sequences…"},
    "side_menu.seq.thumbnails": {"ko": "썸네일 다시 만들기", "en": "Remake thumbnails"},
    "side_menu.seq.info": {"ko": "정보 보기", "en": "Show info"},
    # All
    "side_menu.all.select_movs": {"ko": "Mov만 모두 선택", "en": "Select all Mov only"},
    # 맨 아래의 '다른 앱으로 열기' (sidebar_open_with)
    "open_with.menu": {"ko": "다른 앱으로 열기", "en": "Open with another app"},
    "open_with.count": {"ko": "{text} ({count}개)", "en": "{text} ({count})"},
    "open_with.app": {"ko": "{app}로 열기", "en": "Open with {app}"},
    "open_with.only_sequences.tip": {"ko": "고른 것이 시퀀스뿐입니다 — 등록한 앱으로 여세요",
                                     "en": "Only sequences are selected — open them with a registered app"},
    "open_with.movies_only.tip": {"ko": "시퀀스는 넘기지 않습니다 (영상만)", "en": "Sequences are not passed (videos only)"},
    "open_with.register": {"ko": "앱 등록…", "en": "Register app…"},
    "open_with.remove": {"ko": "앱 지우기", "en": "Remove app"},
    "open_with.no_apps": {"ko": "(등록한 앱 없음)", "en": "(no registered apps)"},
    "open_with.missing": {"ko": "{app} (찾을 수 없음)", "en": "{app} (not found)"},
    "open_with.prefs_problem": {"ko": "설정 파일을 읽지 못했습니다", "en": "Could not read the settings file"},
    # 창 제목의 꼬리 (앞은 'Yeson Checker <버전>' — 언어와 무관)
    "title.loading": {"ko": " — 공유 설정 불러오는 중…", "en": " — loading shared settings…"},
    "title.config_problem": {"ko": " — 공유 설정 오류 (작품 목록 없음)", "en": " — shared settings error (no show list)"},
    "title.path_map_problem": {"ko": " — 변환표 오류", "en": " — path map error"},
    "title.path_map_problem.windows": {"ko": " — 변환표 오류 (작품 경로 관리에서 자동 설정)",
                                       "en": " — path map error (set it up in Manage show paths)"},
    # 도구 패널 (뷰어 오른쪽 — 주석·OCR)
    "panel.annotation": {"ko": "수정 사항 주석", "en": "Annotations"},
    "panel.ocr": {"ko": "OCR", "en": "OCR"},
    "panel.close.tip": {"ko": "패널 닫기 (N)", "en": "Close panel (N)"},
    "ocr.section.roi": {"ko": "ROI 설정", "en": "ROI"},
    "ocr.section.analysis": {"ko": "OCR 분석", "en": "OCR analysis"},
    "ocr.section.results": {"ko": "결과 관리", "en": "Results"},
    # Settings → 언어 (Language) — 메뉴 제목과 항목(한국어·English)은 두 언어에서 같음(ui_language)
    "settings.language.tip": {"ko": "이 창은 바로, 이미 열린 다른 창은 다음에 켤 때부터",
                              "en": "Applies to this window now; other open windows follow the next time they start"},
    "settings.language.env_tip": {
        "ko": "환경 변수 YESONCHECK_LANGUAGE={value} 값이 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다",
        "en": "The environment variable YESONCHECK_LANGUAGE={value} takes precedence — remove it and restart the app to use this setting"},
    # Settings — 재생 디코더 (Mac) · 화면 그리기 (Windows) · 축소 필터 (Windows) · 슬라이더 썸네일 · 공유 설정 폴더 (Windows).
    # 한국어 글은 옮기기 전의 글자 그대로. 이 이름들을 인용하는 알림 글(문장은 한글)은 그때의 화면 글을 끼워 씀.
    "settings.decoder": {"ko": "재생 디코더 (Mac)", "en": "Playback decoder (Mac)"},
    "settings.decoder.videotoolbox": {"ko": "VideoToolbox (기본)", "en": "VideoToolbox (default)"},
    "settings.decoder.ffmpeg": {"ko": "ffmpeg (예전 방식)", "en": "ffmpeg (legacy)"},
    "settings.decoder.tip": {
        "ko": "이 창은 바로 바꾸고 이 Mac의 설정 파일(prefs.json)에 저장합니다 — 이미 열린 다른 창은 다음에 켤 때부터 따릅니다",
        "en": "Switches this window now and saves to this Mac's settings file (prefs.json) — other open windows follow the next "
              "time they start"},
    "settings.decoder.cv2_tip": {
        "ko": "YESONCHECK_MOVIE_SOURCE=cv2가 모든 빠른 디코더를 끕니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다",
        "en": "YESONCHECK_MOVIE_SOURCE=cv2 turns off every fast decoder — remove it and restart the app to use this setting"},
    # 환경 변수가 디코더를 덮을 때 — 값마다 키: 한국어는 받침에 맞는 조사(on이·off가)
    "settings.decoder.env_tip.on": {
        "ko": "환경 변수 YESONCHECK_MAC_NATIVE=on이 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다",
        "en": "The environment variable YESONCHECK_MAC_NATIVE=on takes precedence — remove it and restart the app to use this "
              "setting"},
    "settings.decoder.env_tip.off": {
        "ko": "환경 변수 YESONCHECK_MAC_NATIVE=off가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다",
        "en": "The environment variable YESONCHECK_MAC_NATIVE=off takes precedence — remove it and restart the app to use this "
              "setting"},
    # 체크된 디코더의 툴팁에 보이는 출처 — 한국어 글은 mac_native_gate의 출처 글(기록·비교용)과 같음 (player_base.DECODER_SOURCE_KEYS)
    "settings.decoder.source.fallback": {"ko": "prefs.json 읽기 실패 — 이 세션만 ffmpeg",
                                         "en": "Could not read prefs.json — ffmpeg for this session only"},
    "settings.decoder.source.gl_fallback": {"ko": "네이티브 화면 그리기 실패 — 이 창만 ffmpeg",
                                            "en": "Native drawing failed — ffmpeg for this window only"},
    "settings.display": {"ko": "화면 그리기 (Windows)", "en": "Display rendering (Windows)"},
    "settings.display.cpu": {"ko": "CPU (기본)", "en": "CPU (default)"},
    "settings.display.gpu": {"ko": "GPU", "en": "GPU"},
    "settings.display.tip": {"ko": "이 PC의 설정 파일(prefs.json)에 저장합니다 — 다음에 여는 창부터 적용됩니다",
                             "en": "Saved to this PC's settings file (prefs.json) — applies from the next window you open"},
    "settings.display.env_tip": {"ko": "{name}={value}가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다",
                                 "en": "{name}={value} takes precedence — remove it and restart the app to use this setting"},
    "settings.display.status": {"ko": "지금 이 창: {renderer}", "en": "This window: {renderer}"},
    "settings.downscale": {"ko": "축소 필터 (Windows)", "en": "Downscale filter (Windows)"},
    "settings.downscale.linear": {"ko": "Linear (기본)", "en": "Linear (default)"},
    "settings.downscale.area": {"ko": "고품질 (면적 평균)", "en": "High quality (area average)"},
    "settings.downscale.linear.tip": {
        "ko": "예전 방식 — 가장 빠름. 영상을 반쯤으로 줄여 보면 가는 선이 고르지 않을 수 있습니다",
        "en": "The original method — fastest. Thin lines may look uneven when the video is shown at about half size"},
    "settings.downscale.area.tip": {
        "ko": "줄여 볼 때 가는 선이 고르게 보입니다 — 프레임마다 CPU로 줄이므로 4K 재생이 느려지면 Linear로 되돌리세요 (이 창에 바로 적용)",
        "en": "Thin lines look even when the video is scaled down — every frame is scaled on the CPU, so switch back to Linear "
              "if 4K playback slows down (applies to this window right away)"},
    "settings.hover_thumbs": {"ko": "슬라이더 썸네일", "en": "Slider thumbnails"},
    "settings.hover_thumbs.tip": {
        "ko": "슬라이더 위에 커서를 올리면 그 프레임의 작은 그림을 보여 줍니다 — 이 창은 바로, 이미 열린 다른 창은 다음에 켤 때부터",
        "en": "Shows a small picture of the frame under the cursor on the slider — applies to this window now; other open "
              "windows follow the next time they start"},
    "settings.shared_config": {"ko": "공유 설정 폴더 변경...", "en": "Change shared settings folder..."},
    # Help
    "help.manual": {"ko": "사용법", "en": "User guide"},
    "help.update_check": {"ko": "업데이트 확인…", "en": "Check for updates…"},
    "help.default_app": {"ko": "동영상 기본 앱으로 정하기…", "en": "Set as default video app…"},
    "help.default_apps_settings": {"ko": "동영상 기본 앱 설정 열기…", "en": "Open default video app settings…"},
    "help.about": {"ko": "정보", "en": "About"},
    # 메뉴 — 제목은 두 언어 모두 영어, 항목의 단축키는 글자로만 알림(QAction 단축키를 걸지 않음)
    "menu.file": {"ko": "&File", "en": "&File"},
    "menu.view": {"ko": "&View", "en": "&View"},
    "menu.playback": {"ko": "&Playback", "en": "&Playback"},
    "menu.compare": {"ko": "&Compare", "en": "&Compare"},
    "menu.tools": {"ko": "&Tools", "en": "&Tools"},
    "menu.file.open_a": {"ko": "영상 A 열기… (O)", "en": "Open video A… (O)"},
    "menu.file.open_b": {"ko": "영상 B 열기…", "en": "Open video B…"},
    "menu.file.open_folder": {"ko": "폴더 열기… (I)", "en": "Open folder… (I)"},
    "menu.file.bookmark_add": {"ko": "북마크 추가", "en": "Add bookmark"},
    "menu.file.bookmark_manage": {"ko": "북마크 관리… (P)", "en": "Manage bookmarks… (P)"},
    "menu.view.fit": {"ko": "창에 맞춤 (3)", "en": "Fit to window (3)"},
    "menu.view.original": {"ko": "원본 크기 (4)", "en": "Original size (4)"},
    "menu.view.zoom_in": {"ko": "확대 (2, +)", "en": "Zoom in (2, +)"},
    "menu.view.zoom_out": {"ko": "축소 (1, -)", "en": "Zoom out (1, -)"},
    "menu.view.fullscreen": {"ko": "전체 화면 (F)", "en": "Full screen (F)"},
    "menu.view.video_only": {"ko": "영상만 전체 화면 (Shift+F)", "en": "Video-only full screen (Shift+F)"},
    "menu.view.controls": {"ko": "컨트롤 숨기기/보이기 (V)", "en": "Hide/show controls (V)"},
    "menu.view.theme": {"ko": "테마 바꾸기 (T)", "en": "Switch theme (T)"},
    "menu.view.overlay_text": {"ko": "파일 이름·프레임 번호 글자 (B)", "en": "File name and frame number text (B)"},
    "menu.playback.play": {"ko": "재생/일시정지 (Space)", "en": "Play/Pause (Space)"},
    "menu.playback.prev": {"ko": "한 장 뒤 (←, ,)", "en": "Step back one frame (←, ,)"},
    "menu.playback.next": {"ko": "한 장 앞 (→, .)", "en": "Step forward one frame (→, .)"},
    "menu.playback.first": {"ko": "처음 (Home)", "en": "Go to start (Home)"},
    "menu.playback.last": {"ko": "끝 (End)", "en": "Go to end (End)"},
    "menu.playback.loop": {"ko": "반복 재생 (L)", "en": "Loop playback (L)"},
    "menu.playback.playlist": {"ko": "고른 영상 이어 재생 (Enter)", "en": "Play selected in a row (Enter)"},
    "menu.playback.playlist_end": {"ko": "이어 재생 끝내기", "en": "End playlist"},
    "menu.compare.wipe": {"ko": "와이프 켜기 (W)", "en": "Enable wipe (W)"},
    "menu.compare.x": {"ko": "X축 (좌우)", "en": "X axis (left/right)"},
    "menu.compare.y": {"ko": "Y축 (위아래)", "en": "Y axis (top/bottom)"},
    "menu.tools.annotation": {"ko": "주석 패널", "en": "Annotation panel"},
    "menu.tools.ocr": {"ko": "OCR 패널", "en": "OCR panel"},
    "menu.tools.toggle": {"ko": "도구 패널 열고 닫기 (N)", "en": "Open/close tool panel (N)"},
    "menu.tools.work_paths": {"ko": "작품 경로 관리…", "en": "Manage show paths…"},
}

_language = DEFAULT_LANGUAGE


def language():
    """지금 언어 (`LANGUAGES` 중 하나)."""
    return _language


def set_language(code):
    """지금 언어를 바꿈. 모르는 값은 ValueError — 지금 언어는 그대로."""
    global _language
    if code not in LANGUAGES:
        raise ValueError(f"모르는 언어: {code!r} (쓸 수 있는 값: {', '.join(LANGUAGES)})")
    _language = code


def text(key, **values):
    """키의 지금 언어 글. 모르는 키는 KeyError(글을 지어내지 않음). values는 글 안의 `{이름}`을 채움."""
    template = TEXTS[key][_language]
    return template.format(**values) if values else template


def korean(key, **values):
    """키의 한국어 글 — 화면이 아니라 기록 줄·딸린 창처럼 언어와 무관하게 한글로 남는 자리에서 (같은 글을 두 곳에 적지 않게)."""
    template = TEXTS[key][DEFAULT_LANGUAGE]
    return template.format(**values) if values else template


def missing():
    """한 언어라도 글이 없거나 빈 키 (키 이름순)."""
    return sorted(key for key, texts in TEXTS.items()
                  if any(not str(texts.get(code, "")).strip() for code in LANGUAGES))
