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
    "transport.prev": {"ko": "한 장 뒤로 (←)", "en": "Step back one frame (←)"},
    "transport.play": {"ko": "재생 (Space)", "en": "Play (Space)"},
    "transport.pause": {"ko": "일시정지 (Space)", "en": "Pause (Space)"},
    "transport.next": {"ko": "한 장 앞으로 (→)", "en": "Step forward one frame (→)"},
    "transport.last": {"ko": "끝으로 (End)", "en": "Go to end (End)"},
    "transport.loop": {"ko": "반복 재생 (L)", "en": "Loop playback (L)"},
    "transport.frame": {"ko": "프레임 번호 — 숫자를 치고 Enter", "en": "Frame number — type a number and press Enter"},
    "transport.volume": {"ko": "볼륨 {percent}%", "en": "Volume {percent}%"},
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
    # 도구 패널 (뷰어 오른쪽 — 주석·OCR)
    "panel.annotation": {"ko": "수정 사항 주석", "en": "Annotations"},
    "panel.ocr": {"ko": "OCR", "en": "OCR"},
    "panel.close.tip": {"ko": "패널 닫기 (N)", "en": "Close panel (N)"},
    "ocr.section.roi": {"ko": "ROI 설정", "en": "ROI"},
    "ocr.section.analysis": {"ko": "OCR 분석", "en": "OCR analysis"},
    "ocr.section.results": {"ko": "결과 관리", "en": "Results"},
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
    "menu.playback.prev": {"ko": "한 장 뒤 (←)", "en": "Step back one frame (←)"},
    "menu.playback.next": {"ko": "한 장 앞 (→)", "en": "Step forward one frame (→)"},
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


def missing():
    """한 언어라도 글이 없거나 빈 키 (키 이름순)."""
    return sorted(key for key, texts in TEXTS.items()
                  if any(not str(texts.get(code, "")).strip() for code in LANGUAGES))
