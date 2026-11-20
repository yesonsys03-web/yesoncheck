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
                      "en": "Groups by kind — HD, TX … at the end of the name. Name order within a group"},
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
    "side_menu.open_a": {"ko": "비디오 A 열기 ([)", "en": "Open as video A ([)"},
    "side_menu.open_b": {"ko": "비디오 B 열기 (])", "en": "Open as video B (])"},
    "side_menu.merge": {"ko": "애니매틱 하나로 합치기 (J)", "en": "Merge animatics into one (J)"},
    "side_menu.copy": {"ko": "파일 복사 (C)", "en": "Copy files (C)"},
    "side_menu.thumbnails": {"ko": "썸네일 재생성 (R)", "en": "Regenerate thumbnails (R)"},
    "side_menu.info": {"ko": "미디어 정보 (M)", "en": "Media info (M)"},
    # Seq
    "side_menu.seq.open_a": {"ko": "비디오 A로 열기 ([)", "en": "Open as video A ([)"},
    "side_menu.seq.open_b": {"ko": "비디오 B로 열기 (])", "en": "Open as video B (])"},
    # 사이드바 줄에 마우스를 올리면 뜨는 A·B 단추의 툴팁 (sidebar_ab_buttons)
    "side_ab.open_a": {"ko": "비디오 A로 열기 ([)", "en": "Open as video A ([)"},
    "side_ab.open_b": {"ko": "비디오 B로 열고 와이프 켜기 (])", "en": "Open as video B and turn on wipe (])"},
    "side_ab.close_b": {"ko": "B 닫기 — 와이프 끄기 (])", "en": "Close B — turn off the wipe (])"},
    "side_ab.playlist": {"ko": "선택 재생 중에는 열지 않습니다 — 이어 재생을 끝낸 뒤 여세요",
                         "en": "Not while playing a selection — end it first"},
    "side_menu.seq.export": {"ko": "선택한 시퀀스로 MOV 만들기…", "en": "Make MOV from selected sequences…"},
    "side_menu.seq.thumbnails": {"ko": "썸네일 다시 만들기 (R)", "en": "Remake thumbnails (R)"},
    "side_menu.seq.info": {"ko": "정보 보기 (M)", "en": "Show info (M)"},
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
    # 주석 쪽 (도구 패널) — 고정된 글·툴팁
    "annot.mode": {"ko": "주석 모드", "en": "Annotation mode"},
    "annot.mode.tip": {"ko": "활성화 후 도형을 그리거나 텍스트를 입력합니다.\n기존 주석을 클릭하면 자동으로 편집(이동·크기 조절)할 수 있습니다.",
                       "en": "Turn it on, then draw a shape or enter text.\nClick an existing annotation to edit it (move or resize)."},
    "annot.tool": {"ko": "도구:", "en": "Tool:"},
    "annot.tool.text": {"ko": "텍스트", "en": "Text"},
    "annot.tool.rect": {"ko": "사각형", "en": "Rectangle"},
    "annot.tool.ellipse": {"ko": "타원", "en": "Ellipse"},
    "annot.tool.line": {"ko": "선", "en": "Line"},
    "annot.tool.arrow": {"ko": "화살표", "en": "Arrow"},
    "annot.color": {"ko": "색상:", "en": "Color:"},
    "annot.color.red": {"ko": "빨강", "en": "Red"},
    "annot.color.yellow": {"ko": "노랑", "en": "Yellow"},
    "annot.color.green": {"ko": "초록", "en": "Green"},
    "annot.color.sky": {"ko": "하늘", "en": "Sky blue"},
    "annot.color.white": {"ko": "흰색", "en": "White"},
    "annot.font_size": {"ko": "텍스트 크기:", "en": "Text size:"},
    "annot.font_size.tip": {"ko": "텍스트 주석 크기 (선택 항목 또는 새 텍스트에 적용)",
                            "en": "Size of text annotations (applies to the selected item or new text)"},
    "annot.stroke": {"ko": "선 굵기:", "en": "Line width:"},
    "annot.stroke.tip": {"ko": "도형·선·화살표 굵기 (선택 항목 또는 새 도형에 적용)",
                         "en": "Width of shapes, lines and arrows (applies to the selected item or a new shape)"},
    "annot.range": {"ko": "표시 프레임:", "en": "Frames:"},
    "annot.range.start": {"ko": "시작", "en": "from"},
    "annot.range.end": {"ko": "~ 끝", "en": "~ to"},
    "annot.range.start.tip": {"ko": "주석이 보이기 시작하는 프레임 (1부터 시작)\n입력 후 Enter 또는 다른 칸을 클릭하세요.",
                              "en": "First frame the annotation is shown on (frames start at 1)\nType it, then press Enter or click another field."},
    "annot.range.end.tip": {"ko": "주석이 보이기 끝나는 프레임 (시작 프레임 이상)\n입력 후 Enter 또는 다른 칸을 클릭하세요.",
                            "en": "Last frame the annotation is shown on (not before the first frame)\nType it, then press Enter or click another field."},
    "annot.list.tip": {"ko": "전체 주석 목록 · 클릭하면 시작 프레임으로 이동", "en": "All annotations · click one to go to its first frame"},
    "annot.delete": {"ko": "선택 주석 삭제", "en": "Delete selected annotation"},
    "annot.clear_frame": {"ko": "현재 프레임에 보이는 주석 전체 삭제", "en": "Delete all shown on this frame"},
    "annot.export": {"ko": "주석 포함 영상보내기", "en": "Export video with annotations"},
    "annot.export.tip": {"ko": "주석이 픽셀에 박힌 새 영상 파일을 생성합니다.\n먼저 아래에서 보내기 저장 폴더를 선택하세요.",
                         "en": "Makes a new video file with the annotations burned into the picture.\nChoose the export folder below first."},
    "annot.export_dir.choose": {"ko": "보내기 저장 폴더 선택", "en": "Choose export folder"},
    # 주석 쪽 — 상태에 따라 바뀌는 글 (만든 때의 뜻을 기억했다가 언어가 바뀌면 다시 그림)
    "annot.export_dir": {"ko": "보내기 저장 폴더: {folder}", "en": "Export folder: {folder}"},
    "annot.export_dir.none": {"ko": "보내기 저장 폴더: 미지정 (선택 필요)", "en": "Export folder: not set (choose one)"},
    "annot.storage.shared": {"ko": "서버 공유 저장: {path}", "en": "Saved on the shared server: {path}"},
    "annot.storage.blocked": {"ko": "⚠ 저장 불가: {path}", "en": "⚠ Cannot save: {path}"},
    "annot.storage.unreadable": {"ko": "⚠ 주석 저장 안 함 (주석 파일을 읽지 못함): {path}",
                                 "en": "⚠ Annotations are not saved (could not read the annotation file): {path}"},
    "annot.storage.not_writable": {"ko": "⚠ 주석 저장 불가 (쓰기 권한 없음): {folder}",
                                   "en": "⚠ Cannot save annotations (no write permission): {folder}"},
    "annot.storage.failed": {"ko": "⚠ 주석 저장 실패: {detail}", "en": "⚠ Saving annotations failed: {detail}"},
    "annot.status.none": {"ko": "주석: 없음 (자동 저장)", "en": "Annotations: none (saved automatically)"},
    "annot.status.none_shared": {"ko": "주석: 없음 (서버 폴더에 자동 저장)",
                                 "en": "Annotations: none (saved automatically to the server folder)"},
    "annot.status.loaded": {"ko": "주석 {count}개 자동 로드 · 서버 공유 JSON", "en": "{count} annotations loaded · shared server JSON"},
    "annot.status.unreadable": {"ko": "⚠ 주석 파일을 읽지 못함 — 이 영상은 주석을 저장하지 않음",
                                "en": "⚠ Could not read the annotation file — annotations for this video are not saved"},
    "annot.status.added": {"ko": "프레임 {start}~{end}에 {kind} 주석 추가 (자동 저장)",
                           "en": "Added: {kind} annotation on frames {start}~{end} (saved automatically)"},
    "annot.status.counts": {
        "ko": "전체 {total}개 / {frames}개 프레임에 표시 · 목록 {total}개 · 현재 프레임 {frame}: {here}개 (자동 저장)",
        "en": "{total} in all / shown on {frames} frames · list {total} · current frame {frame}: {here} (saved automatically)"},
    # 주석의 종류 이름 — 상태 글·목록 항목에 보임. 한국어는 예전부터 보이던 글 그대로(도형은 내부 이름)
    "annot.kind.text": {"ko": "텍스트", "en": "text"},
    "annot.kind.rect": {"ko": "rect", "en": "rectangle"},
    "annot.kind.ellipse": {"ko": "ellipse", "en": "ellipse"},
    "annot.kind.line": {"ko": "line", "en": "line"},
    "annot.kind.arrow": {"ko": "arrow", "en": "arrow"},
    "annot.list.text": {"ko": "[{range} 텍스트 {size}px] {preview}", "en": "[{range} text {size}px] {preview}"},
    # OCR 쪽 (도구 패널) — 방식 이름 Titmouse·King·Bento는 두 언어에서 같음(글자 표에 없음)
    "ocr.roi.select": {"ko": "OCR ROI 지정", "en": "Set OCR ROI"},
    "ocr.roi.select.tip": {"ko": "영상에서 OCR 분석에 사용할 영역을 드래그하여 지정합니다.",
                           "en": "Drag on the video to set the area used for OCR analysis."},
    "ocr.roi.sequence.tip": {"ko": "이미지 시퀀스에서는 OCR·컷 감지를 쓸 수 없습니다.",
                             "en": "OCR and cut detection cannot be used on image sequences."},
    "ocr.roi.not_needed.tip": {"ko": "{mode} 모드는 ROI가 필요 없습니다.", "en": "{mode} mode does not need an ROI."},
    "ocr.mode_name.animatic": {"ko": "애니매틱", "en": "Animatic"},
    "ocr.mode_name.animatic2": {"ko": "애니매틱2", "en": "Animatic 2"},
    "ocr.roi.clear": {"ko": "ROI 초기화", "en": "Reset ROI"},
    "ocr.roi.tracking": {"ko": "ROI 트래킹 활성화", "en": "Enable ROI tracking"},
    "ocr.roi.tracking.tip": {"ko": "활성화하면 지정한 ROI 영역이 동영상에서 이동하는 텍스트를 자동으로 추적합니다.",
                             "en": "When on, the ROI automatically follows text that moves in the video."},
    "ocr.mode.label": {"ko": "OCR 분석 방식:", "en": "OCR method:"},
    "ocr.mode.all": {"ko": "All (사용자 패턴)", "en": "All (custom pattern)"},
    "ocr.mode.animatic": {"ko": "애니매틱 (Auto Cut)", "en": "Animatic (Auto Cut)"},
    "ocr.mode.animatic2": {"ko": "애니매틱2 (TransNetV2)", "en": "Animatic 2 (TransNetV2)"},
    "ocr.mode.tip": {
        "ko": "이미지에 따라 분석 정확도가 다를 수 있으므로 적합한 방식을 선택하세요.\n"
              "- Titmouse: 기본 OCR 설정\n"
              "- King: 빨간색 텍스트 인식 최적화\n"
              "- Bento: 작은 텍스트 및 특수 패턴 인식 최적화 (예: Seq 02A_S09 - Panel 6)\n"
              "- All: 사용자 정의 패턴으로 텍스트 인식 (#=영문, W=숫자, 예: \"### WW#_#WW - #### W\")\n"
              "- 애니매틱: PySceneDetect를 사용한 자동 컷 감지 (ROI 불필요)",
        "en": "Accuracy depends on the picture, so choose the method that fits.\n"
              "- Titmouse: the standard OCR settings\n"
              "- King: tuned for red text\n"
              "- Bento: tuned for small text and special patterns (e.g. Seq 02A_S09 - Panel 6)\n"
              "- All: reads text by a pattern you define (#=letter, W=digit, e.g. \"### WW#_#WW - #### W\")\n"
              "- Animatic: automatic cut detection with PySceneDetect (no ROI needed)"},
    "ocr.mode.tip.animatic2": {
        "ko": "\n- 애니매틱2: TransNetV2(딥러닝)를 사용한 컷 감지 (디졸브/페이드 감지 향상, ROI 불필요)",
        "en": "\n- Animatic 2: cut detection with TransNetV2 (deep learning — better at dissolves and fades, no ROI needed)"},
    "ocr.pattern.label": {"ko": "패턴:", "en": "Pattern:"},
    "ocr.pattern.placeholder": {"ko": "예: ### WW#_#WW - #### W (#=영문, W=숫자)", "en": "e.g. ### WW#_#WW - #### W (#=letter, W=digit)"},
    "ocr.pattern.tip": {
        "ko": "All 모드에서 사용할 텍스트 패턴을 입력하세요.\n"
              "- # = 영문 (A-Z, a-z)\n"
              "- W = 숫자 (0-9)\n"
              "- _ = 언더바\n"
              "- - = 하이픈\n"
              "- 공백 = 공백\n"
              "예시:\n"
              "- \"seq 04A_S05 - Panel 1\" → \"### WW#_#WW - #### W\"\n"
              "- \"MS101_B010\" → \"##WWW_#WWW\"",
        "en": "Enter the text pattern to use in All mode.\n"
              "- # = letter (A-Z, a-z)\n"
              "- W = digit (0-9)\n"
              "- _ = underscore\n"
              "- - = hyphen\n"
              "- space = space\n"
              "Examples:\n"
              "- \"seq 04A_S05 - Panel 1\" → \"### WW#_#WW - #### W\"\n"
              "- \"AB101_C010\" → \"##WWW_#WWW\""},
    "ocr.analyze": {"ko": "OCR 구간 추출", "en": "Extract OCR segments"},
    "ocr.analyze_range": {"ko": "선택 구간 분석", "en": "Analyze a frame range"},
    "ocr.analyze_range.tip": {"ko": "지정한 프레임 범위만 OCR 분석합니다. 결과는 기존 분석 결과에 병합됩니다.",
                              "en": "Runs the analysis on the frame range you give only. The result is merged into the existing one."},
    "ocr.reopen": {"ko": "OCR 오픈", "en": "Open OCR result"},
    "ocr.reopen.tip": {"ko": "이전에 분석한 OCR 결과를 다시 엽니다 (분석한 내용과 수정한 내용이 모두 표시됩니다)",
                       "en": "Reopens the last OCR result (shows both what was analyzed and what you edited)"},
    "ocr.save": {"ko": "OCR 저장", "en": "Save OCR result"},
    "ocr.save.tip": {"ko": "현재 OCR 분석 결과를 파일로 저장합니다", "en": "Saves the current OCR result to a file"},
    "ocr.load": {"ko": "OCR 로드", "en": "Load OCR result"},
    "ocr.load.tip": {"ko": "저장된 OCR 분석 결과를 불러옵니다", "en": "Loads a saved OCR result"},
    # 뷰어 오른쪽 위의 배지 (주석 모드 동안)
    "badge.annotation": {"ko": "주석 모드", "en": "Annotation mode"},
    # V 모드의 오버레이 컨트롤 — 안내 글 (우클릭으로 보임)
    "overlay.help": {"ko": "드래그로 이동, 테두리로 크기조절, Ctrl+휠로 확대/축소, Ctrl+O로 리셋",
                     "en": "Drag to move, drag the border to resize, Ctrl+wheel to zoom, Ctrl+O to reset"},
    # 업데이트 알림 띠 (창 맨 위) — 글과 단추. 기록 줄에는 한국어 글이 그대로 남음 (Message)
    "update.offer": {"ko": "⬆ 새 버전 {new}{ga} 나왔습니다 · 지금 {current}", "en": "⬆ Version {new} is available · now {current}"},
    "update.download": {"ko": "{version} 받는 중 ({source})… {done} / {total} MB",
                        "en": "Downloading {version} ({source})… {done} / {total} MB"},
    "update.staging": {"ko": "준비 중…", "en": "Preparing…"},
    "update.cancelling": {"ko": "취소하는 중…", "en": "Cancelling…"},
    "update.helper": {"ko": "업데이트 도우미를 시작하는 중…", "en": "Starting the update helper…"},
    "update.checking": {"ko": "다른 창 확인 중…", "en": "Checking other windows…"},
    "update.closing": {"ko": "다른 창을 닫는 중…", "en": "Closing other windows…"},
    "update.updated": {"ko": "{version}{ro} 업데이트했습니다", "en": "Updated to {version}"},
    "update.notes": {"ko": "바뀐 점", "en": "What's new"},
    "update.update": {"ko": "업데이트", "en": "Update"},
    "update.later": {"ko": "나중에", "en": "Later"},
    "update.cancel": {"ko": "취소", "en": "Cancel"},
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
    "menu.compare.ab_buttons": {"ko": "사이드바 A·B 단추", "en": "Sidebar A·B buttons"},
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


class Message(str):
    """글자 표의 글 하나를 '키와 값'째로 들고 다니는 글자. **값은 늘 한국어 글**(기록 줄에 적고 견줄 수 있음 — 기록은 언어와
    무관하게 한글), `shown()`이 지금 언어로 만든 화면 글. 완성된 글을 받아 보이는 위젯(업데이트 알림 띠)이 언어가 바뀐 뒤
    같은 뜻의 글로 다시 그릴 수 있게 — 그냥 글자를 넘기면 그 위젯은 받은 글 그대로 둔다."""

    def __new__(cls, key, **values):
        self = super().__new__(cls, korean(key, **values))
        self.key = key
        self.values = values
        return self

    def shown(self):
        return text(self.key, **self.values)

    def __reduce__(self):  # copy·deepcopy·pickle — str의 기본은 한국어 글 하나로 다시 만들려다 KeyError (리뷰 M-3)
        return (_rebuild_message, (self.key, self.values))


def _rebuild_message(key, values):
    return Message(key, **values)


def shown(value):
    """화면에 보일 글: Message면 지금 언어로 만든 글, 그냥 글자면 받은 그대로."""
    return value.shown() if isinstance(value, Message) else value


# ---------------------------------------------------------------- 한국어 조사
# 화면 언어와 무관하게 한글 문장으로 남는 글(딸린 창·알림 띠의 한국어 글)이 바뀌는 낱말(버전 번호·지금 화면의 메뉴 이름)에
# 조사를 붙일 때. 글자 표의 한국어 글에 `{ga}`·`{ro}`처럼 조사 자리를 두고 부르는 쪽이 채운다(version_values).
PARTICLE_PAIRS = ("이/가", "을/를", "은/는", "과/와", "으로/로")  # 받침 있을 때/없을 때
_PAIR_OF = {part: pair for pair in PARTICLE_PAIRS for part in pair.split("/")}
_DIGIT_FINAL = {"0": "ㅇ", "1": "ㄹ", "2": "", "3": "ㅁ", "4": "", "5": "", "6": "ㄱ", "7": "ㄹ", "8": "ㄹ", "9": ""}  # 영 일 이 삼 …


def _final(word):
    """끝 글자의 받침 — 없으면 "", ㄹ이면 "ㄹ", 그 밖의 받침이면 "있음", 읽는 소리를 모르면(영문·기호) None. 숫자는 읽는 소리로."""
    last = str(word).rstrip()[-1:]  # 버전은 updates.Version일 수도 — 글로 보이는 모양으로
    if "가" <= last <= "힣":
        index = (ord(last) - ord("가")) % 28
        return "" if index == 0 else ("ㄹ" if index == 8 else "있음")
    if last in _DIGIT_FINAL:
        final = _DIGIT_FINAL[last]
        return final if final in ("", "ㄹ") else "있음"
    return None


def particle(word, pair):
    """word 뒤에 붙일 조사 — pair는 PARTICLE_PAIRS의 하나("이/가" 등). 끝 글자가 한글이면 받침으로, 숫자면 읽는 소리로(1.10.0 →
    '이'·'으로', 1.9.4 → '가'·'로'), ㄹ 받침 뒤의 으로/로는 '로'. 읽는 소리를 모르면(영문·기호) 두 꼴을 함께('을(를)'·'(으)로')."""
    if pair not in PARTICLE_PAIRS:
        raise ValueError(f"모르는 조사 짝: {pair!r} (쓸 수 있는 값: {', '.join(PARTICLE_PAIRS)})")
    with_final, without_final = pair.split("/")
    final = _final(word)
    if final is None:
        return "(으)로" if pair == "으로/로" else f"{with_final}({without_final})"
    if final == "" or (final == "ㄹ" and pair == "으로/로"):
        return without_final
    return with_final


def version_values(version, name="version"):
    """버전 번호를 넣는 글의 값 — {name: 버전, "ga": 이/가, "ro": 으로/로} (글자 표의 한국어 글이 `{ga}`·`{ro}`를 씀)."""
    return {name: version, "ga": particle(version, "이/가"), "ro": particle(version, "으로/로")}


def with_particle(name, korean_particle, noun="항목"):
    """한글 문장이 지금 화면의 이름(메뉴·단추)을 인용할 때의 '이름 + 조사'. 한국어 화면이면 name + korean_particle(예전 글 그대로 —
    이름이 정해져 있어 조사도 정해져 있음), English 화면이면 이름 뒤에 한국어 명사를 붙여 그 명사의 조사로('Slider thumbnails
    항목을') — 영어 낱말의 받침은 읽기에 따라 달라 고를 수 없음 (리뷰 M-8). korean_particle 앞의 공백은 한국어 글에만 남는다."""
    pair = _PAIR_OF.get(korean_particle.strip())
    if pair is None:
        raise ValueError(f"모르는 조사: {korean_particle!r}")
    if _language == DEFAULT_LANGUAGE:
        return name + korean_particle
    return f"{name} {noun}{particle(noun, pair)}"


def missing():
    """한 언어라도 글이 없거나 빈 키 (키 이름순)."""
    return sorted(key for key, texts in TEXTS.items()
                  if any(not str(texts.get(code, "")).strip() for code in LANGUAGES))
