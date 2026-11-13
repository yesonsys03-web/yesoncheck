"""English text of the user manual (Help → 사용법) — mirrors manual_content.PAGES block for block (no Qt, data only).

`manual_content`(한글)의 쪽·블록을 **같은 차례·같은 모양**으로 옮긴 영어 글. 한쪽을 고치면 다른 쪽도 함께 고칠 것 —
서로 같아야 하는 것: 쪽 key와 차례, 블록 종류와 차례, 닻, 그림 이름, 그림 설명 수(그림 위의 번호 표지와 짝), 단축키 표의 줄 수,
표의 줄·칸 수, 목록 항목 수, 글 안의 링크 대상(`[[쪽/닻|글]]`의 쪽·닻)과 `{키}`.
`Page`와 `RELEASES_KEY`는 `manual_content`의 것을 그대로 씀(여기서 다시 정하지 않음). `GROUPS`는 한글 `GROUPS`와 같은 자리끼리 짝.

화면 글자 규칙:
- 앱에서 영어인 이름(Open Video A, Play Selected, Settings …)은 그대로.
- 앱에서 한글인 이름(**▶ 수정 사항 주석**, `재생 디코더 (Mac)` …)과 화면에 뜨는 한글 글은 **한글 그대로** 적고, 그 쪽에서 처음 나올 때
  괄호 안에 영어 뜻을 붙임 — 영어로만 바꿔 적지 않음(화면에서 찾을 수 없게 됨). OS의 한글 이름(다음으로 열기·연결 프로그램 …)도 같은 모양.
- 키 표시(`{N}`, 단축키 표의 "F (ㄹ)")는 한글 쪽과 같은 글자. 한글 낱말이 든 키만 옮김("마우스 휠" → "Mouse wheel").
- 코드 표시 안의 자리 이름(`<이름>.mov` → `<name>.mov`)은 옮기고, 화면에 그대로 뜨는 글(`시퀀스 3개`, `정렬: 이름 ▾`)은 그대로.
"""
from yesoncheck.manual_content import Page

RELEASES_TITLE = "Release notes"
RELEASES_GROUP = "Reference"
RELEASES_LEAD = "What changed in each version. The newest version is at the top."

GROUPS = ("Getting started", "Viewing & playback", "Lists & files", "Review tools", "Settings & management", "Reference")

PAGES = (
    Page("start", "Getting started", "Getting started",
         "YesonCheck is a player for reviewing videos and image sequences frame by frame. A/B comparison, revision annotations, "
         "and splitting animatics with OCR or cut detection are all done in one window.",
         (
             ("h", "Screen layout", "screen"),
             ("fig", "overview", "Main window", (
                 "**Menus** — Settings and Help (manual, updates, version info). On Mac they are in the menu bar at the top of the "
                 "screen. → [[settings]]",
                 "**Sidebar** — folder and bookmark buttons and the video list (Mov, Seq and All tabs). → [[sidebar]]",
                 "**Middle control panel** — opening videos, OCR, revision annotations, wipe, Play Selected playback and choosing a "
                 "show. Press {N} to hide it.",
                 "**Video area** — where the video is shown. Use the mouse wheel to step one frame at a time; when zoomed in, drag "
                 "to pan. → [[view]]",
                 "**Info row** — file name, current frame, total frames, playback FPS and time. → [[playback]]",
                 "**Time slider** — click or drag to move; hover the mouse over it to preview the picture at that position.",
                 "**Play · Stop** — play/pause ({Space}) and stop.",
             )),
             ("h", "Opening videos", "open"),
             ("table", ("How", "Result"), (
                 ("Drop files onto the window",
                  "One file opens in A; two files open in A and B. With three or more, the first file opens in A and the rest are "
                  "added to the list."),
                 ("Drop a folder onto the window",
                  "The list is **replaced** by the videos in that folder and the first video opens in A. The folder is also added "
                  "to the bookmarks automatically."),
                 ("Drop onto the Mov list",
                  "The files are only added to the list, not opened (the video you are viewing and the list stay as they are)."),
                 ("Open Video A / Open Video B", "Choose a file and open it in A or B."),
                 ("Click in the list", "That video opens in A. Use {↑} {↓} to step through the videos one by one."),
                 ("Choose show → season → job", "Loads the video list of that job (a feature specific to Yeson's in-house workflow). "
                                                "→ [[library/works|Choosing a show]]"),
                 ("Double-click in Finder or File Explorer", "A new window opens with that video in A. → [[windows]]"),
                 ("A single frame of an image sequence", "The whole sequence that the frame belongs to opens. → [[sequences]]"),
             )),
             ("h", "Basic review workflow", "flow"),
             ("steps", (
                 "Choose show → season → job (for Yeson's in-house work), or drop a folder onto the window.",
                 "Click a video in the list. Use {↑} {↓} to move on to the next video.",
                 "Press {Space} to play, and use {←} {→} or the mouse wheel to go one frame at a time.",
                 "If something needs fixing, expand **▶ 수정 사항 주석** (Revision annotations) and mark it on the video. → [[annotations]]",
                 "Use **주석 포함 영상보내기** (Export video with annotations) to create a video that includes the annotations, and pass it on.",
             )),
             ("tip", "You can open this manual again at any time with {F1} or **Help → 사용법** (Manual). For a quick look at the "
                     "shortcuts only, see the [[shortcuts]] page."),
         )),
    Page("shortcuts", "Keyboard shortcuts", "Getting started",
         "Most of the review work can be done with the keyboard alone. The keys also work while the Korean input method is on — "
         "the character in parentheses is the same key on the Korean keyboard layout.",
         (
             ("h", "Playback · frame stepping", "play"),
             ("keys", (
                 ("Space", "Play / pause"),
                 (("←", ","), "Previous frame"),
                 (("→", "."), "Next frame"),
                 ("Mouse wheel", "Step one frame at a time — anywhere in the window except over the list (up = next, down = previous)"),
             )),
             ("h", "View", "view"),
             ("keys", (
                 (("+", "=", "2"), "Zoom in — around the position of the mouse cursor"),
                 (("-", "1"), "Zoom out"),
                 ("Ctrl+Wheel", "Zoom in / out (⌘+Wheel on Mac)"),
                 ("3", "Fit to window"),
                 ("4", "Original size (1:1)"),
                 ("Drag", "Pan the zoomed view"),
                 ("F (ㄹ)", "Full screen — including the controls"),
                 ("Shift+F", "Full screen — video only"),
                 ("V (ㅍ)", "Hide ↔ show all controls — while they are hidden, overlay controls appear on top of the video"),
                 ("N (ㅜ)", "Hide ↔ show the middle control panel only"),
                 ("T (ㅅ)", "Dark theme ↔ light theme"),
                 ("B (ㅠ)", "Show ↔ hide the file name and frame number text"),
                 ("Ctrl+O", "Reset the position and size of the overlay controls (⌘+O on Mac)"),
             )),
             ("note", "After you click in the list and the list has focus, {T} and {B} do not respond. Click once on the video side "
                      "and then press the key (the other keys work even while the list has focus)."),
             ("h", "List (after clicking in the sidebar, while the list has focus)", "list"),
             ("keys", (
                 (("↑", "↓"), "Move to the item above / below and open it in A (Mov · Seq · All)"),
                 ("Enter", "Start Play Selected playback — plays the selected videos one after another (Mov · All)"),
                 ("\\", "Pause ↔ resume Play Selected playback — starts it if it is not running (Mov · All)"),
                 ("Ctrl+Click", "Add items to the selection one at a time (⌘+Click on Mac)"),
                 ("Shift+Click", "Select everything in between as well"),
             )),
             ("h", "App windows · other", "misc"),
             ("keys", (
                 ("P (ㅔ)", "Open the bookmark manager window (if there are no bookmarks at all, only a notice appears)"),
                 ("R (ㄱ)", "Regenerate the thumbnails of the videos selected in the list"),
                 ("F5", "Refresh the list"),
                 ("F1", "사용법 (Manual — this document)"),
             )),
             ("h", "OCR review window", "review"),
             ("keys", (
                 ("D (ㅇ)", "선택한 구간 병합 (merge the selected segments)"),
                 ("X (ㅌ)", "선택 구간 삭제 (delete the selected segments)"),
                 ("R (ㄱ)", "전체 내보내기 (export all)"),
                 ("Space", "Play / pause the 프리뷰 영상 (preview video)"),
                 (("←", "→"), "Step the 프리뷰 영상 one frame at a time"),
                 ("Ctrl+Z", "실행 취소 (undo) — ⌘+Z on Mac"),
                 (("⌘+Shift+Z", "Ctrl+Y"), "다시 실행 (redo) — the first is for Mac, the second for Windows"),
                 ("Ctrl+Click", "Add segments to the selection one at a time (⌘+Click on Mac)"),
                 ("Shift+Click", "Select the segments in between as well"),
             )),
             ("h", "Bookmark manager window", "bookmarks"),
             ("keys", (
                 ("Double-click", "Open that folder"),
                 ("Enter", "Open the selected folder — while you are editing a path, save the edit"),
                 ("Esc", "Cancel editing the path"),
             )),
         )),
    Page("playback", "Playback and navigation", "Viewing & playback",
         "Play, step one frame at a time, and find the scene you want with the slider.",
         (
             ("fig", "playbar", "Info row and playback controls", (
                 "**File name** — the file open in A. If B is open too, both are shown.",
                 "**Current** — the current frame number (starting from 1).",
                 "**Total** — the total number of frames and the length in feet and frames (16 frames = 1 foot; `3F 00f` means "
                 "3 feet 0 frames).",
                 "**Playback FPS** — during playback, the speed actually achieved is shown as well, as in `재생: 24 FPS · 실제 23.8` "
                 "(재생 = playback, 실제 = actual).",
                 "**Time** — current time / total length.",
                 "**Time slider** — click to go to that position; drag to scrub through quickly.",
                 "**Play** — play / pause ({Space}).",
                 "**Stop** — stops and returns to the first frame.",
             )),
             ("h", "Playback", "play"),
             ("keys", (
                 ("Space", "Play / pause"),
                 (("←", ","), "Previous frame"),
                 (("→", "."), "Next frame"),
                 ("Mouse wheel", "Step one frame at a time (anywhere in the window except over the list)"),
             )),
             ("list", (
                 "Turn on **Loop Play** (middle panel) to repeat from the beginning after reaching the end.",
                 "The **FPS** field shows the frame rate of the open video.",
                 "If the `실제` (actual) value in the info row is far below the original FPS, playback is slow. The value is measured "
                 "once per second, so it fluctuates by about ±1; while playback is stopped and during the first second after it "
                 "starts, only the original FPS is shown.",
             )),
             ("h", "Slider preview", "hover"),
             ("fig", "hover", "The cursor hovering over the time slider", (
                 "**Preview popup** — the picture and number of the frame at the cursor position. The number is the frame you go to "
                 "if you click there.",
                 "**Mouse cursor** — as you move it, the picture and number change with it.",
             )),
             ("p", "Hover the mouse cursor over a time slider (the slider at the bottom of the window or the slider in V mode) to "
                   "see the scene at that position before you click."),
             ("list", (
                 "The pictures are generated in the background **while you are idle** (not playing or navigating), after a video "
                 "is opened in A. Generation pauses while you play or drag the slider and, once you are idle again, continues from "
                 "where it stopped.",
                 "Positions that have not been generated yet show only the number and an empty box.",
                 "For videos longer than 500 frames, pictures are generated at intervals and the nearest scene is shown (the number "
                 "is exact). For long H.264 videos, approximate pictures appear first and are then replaced by exact ones.",
                 "Files larger than 4 GB show only the number, without a picture. The preview is not available for image sequences yet.",
                 "To turn it off, uncheck **Settings → 슬라이더 썸네일** (Slider thumbnails) — it is on by default, and the setting "
                 "is saved on this PC only.",
             )),
             ("h", "Play Selected playback", "playlist"),
             ("p", "Plays the videos selected in the list one after another."),
             ("steps", (
                 "Select several videos in the list — Ctrl+click (⌘+click on Mac) to add one at a time, Shift+click to include "
                 "everything in between.",
                 "Click **Play Selected**, or press {Enter} in the list.",
                 "To pause or resume, click the button next to it or press {\\} — the button reads **Selected Pause** while playing "
                 "and **Selected Play** while paused.",
             )),
             ("list", (
                 "Videos that are not on disk at that moment are skipped.",
                 "In the All tab, **only the videos (mov)** among the selected items are played and sequences are skipped. "
                 "Right-click → **Mov만 모두 선택** (Select all Mov only) selects only the videos.",
                 "In the Seq tab, **Play Selected** is disabled.",
             )),
             ("h", "Sound", "sound"),
             ("p", "Adjust it with the **Volume** slider in the middle panel."),
             ("warn", "On **Windows**, K-Lite Codec Pack (Basic) must be installed to hear the sound of a video. Without it, the "
                      "picture plays but there is no sound."),
         )),
    Page("view", "Viewing", "Viewing & playback",
         "Zooming, full screen, hiding the controls, themes, and the file name / frame number display.",
         (
             ("h", "Zoom in · zoom out · pan", "zoom"),
             ("keys", (
                 (("+", "=", "2"), "Zoom in — around the position of the mouse cursor"),
                 (("-", "1"), "Zoom out"),
                 ("Ctrl+Wheel", "Zoom in / out (⌘+Wheel on Mac)"),
                 ("3", "Fit to window"),
                 ("4", "Original size (1:1)"),
                 ("Drag", "Pan the zoomed view"),
             )),
             ("h", "Full screen", "fullscreen"),
             ("keys", (
                 ("F (ㄹ)", "Full screen — including the controls"),
                 ("Shift+F", "Full screen — video only"),
             )),
             ("h", "Hiding the controls — V and N", "hide"),
             ("fig", "v_mode", "The controls hidden by pressing V", (
                 "**Overlay controls** — play button, frame number, file name, volume and slider. They float on top of the video.",
             )),
             ("list", (
                 "{V} — hides the sidebar and all the controls so that the video is shown larger. While they are hidden, play and "
                 "navigate with the overlay controls on top of the video. When the mouse leaves the video the overlay hides too, "
                 "and it reappears when the mouse comes back. Press {V} again to bring the controls back.",
                 "Drag the overlay controls to move them, drag their border to resize them, and use Ctrl+wheel to scale them up or "
                 "down. The size is remembered; the position returns to the bottom center every time they reappear. {Ctrl+O} resets "
                 "the size as well.",
                 "{N} — hides only the middle control panel. The list and the video stay, and the video gets wider by the space "
                 "that was hidden.",
             )),
             ("h", "Theme", "theme"),
             ("p", "Press {T} to switch between the dark theme and the light theme."),
             ("h", "File name · frame number display (B)", "overlay"),
             ("fig", "overlay_text", "After pressing B — bottom left of the video", ()),
             ("p", "Press {B} to show `File: file name, Frame: current/total` at the bottom left of the video. Press it again to "
                   "hide it. The text appears at the same size regardless of the resolution."),
         )),
    Page("compare", "A/B comparison (wipe)", "Viewing & playback",
         "Overlay two videos in one view and compare them by moving a dividing line — between takes, or before and after a fix.",
         (
             ("fig", "wipe", "Comparing A (sketch) and B (colored) with a vertical wipe", (
                 "**Enable Wipe Effect** — turns the wipe on.",
                 "**X-Axis Wipe · Y-Axis Wipe** — split left and right with a vertical line / split top and bottom with a "
                 "horizontal line. Both can be on at the same time.",
                 "**Wipe line** — drag it to move it. A is to the left of (above) the line and B is to the right of (below) it.",
                 "**File name** — the names of A and B are shown together.",
             )),
             ("h", "Steps", "steps"),
             ("steps", (
                 "Open a video in A.",
                 "Open B with **Open Video B**, or right-click in the list → **비디오 B 열기** (Open video B).",
                 "Turn on **Enable Wipe Effect** and click **X-Axis Wipe** or **Y-Axis Wipe**.",
                 "Drag the line on the video to compare.",
             )),
             ("h", "Things to know", "notes"),
             ("list", (
                 "If A and B have **different sizes (resolutions), the B area is black**. Compare videos of the same size.",
                 "**Only A is shown while you drag** the time slider; when you release it, B is synced to the same frame as A.",
                 "{←} {→} move **only A** one frame at a time (B stays where it is). The mouse wheel moves A and B together, and "
                 "clicking the time slider also syncs B to the same frame as A again.",
                 "Videos are compared only with videos, and image sequences only with sequences. If you open something of a "
                 "different kind from the other side, the other side is closed and the wipe is turned off.",
                 "Playing two 4K videos together makes the decoder do twice the work, so depending on the hardware playback may "
                 "not be real time.",
                 "When you view ProRes on Mac, A's file name text (B key) and annotations are not cut off at the line even with the "
                 "wipe on — they are visible over the B side as well.",
             )),
         )),
    Page("sidebar", "Sidebar (video list)", "Lists & files",
         "The list of videos and sequences to review. Open and select items here, and do various tasks from the right-click menu.",
         (
             ("fig", "sidebar", "Sidebar", (
                 "**Select Folder** — choose a folder and put the videos and sequences in it into the list.",
                 "**Add Bookmark** — adds a folder to the bookmarks.",
                 "**Bookmarks** — opens the bookmark manager window ({P}). → [[library/bookmarks|Bookmarks]]",
                 "**작품 경로 관리** (Manage show paths) — registers the locations of the show folders (for administrators — "
                 "password required; a feature specific to Yeson's in-house workflow).",
                 "**List · Thumb · 새로고침** (Refresh) — change how the list looks, and read the list again ({F5}).",
                 "**Mov · Seq · All tabs** — videos / image sequences / both. The `↕` next to the All tab is the **정렬** (Sort) "
                 "button. → [[sidebar/sort|Sorting]]",
                 "**List** — click an item to open it in A. Selected items are orange.",
                 "**Count line** — the number of items in the tab you are viewing.",
             )),
             ("h", "Tabs", "tabs"),
             ("table", None, (
                 ("Mov", "Video files."),
                 ("Seq", "Image sequences — one row per sequence. → [[sequences]]"),
                 ("All", "Videos and sequences in one list, in name order. Sequence names are shown in sky blue."),
             )),
             ("fig", "all_tab", "All tab — the sky-blue rows are image sequences", ()),
             ("h", "Count line", "count"),
             ("p", "Right below the list, the number of items in the tab you are viewing is shown; it follows the list as it changes."),
             ("list", (
                 "Items are counted per **type** at the end of the name (a suffix of letters only, such as `_HD` or `_TX`; `기본` "
                 "— default — when there is none), and the **versions/takes** (`TK1`, `v01`) within each type are shown in "
                 "parentheses. Example: `450개 — 기본 225 (TK1 225) · HD 225 (TK1 225)` (450개 = 450 items)",
                 "The Seq tab counts sequences, not frames. Example: `시퀀스 3개` (3 sequences)",
                 "The All tab shows the count per format on the first line (`10개 — mov 7 · png 3`) and the types and versions on "
                 "the second line.",
             )),
             ("h", "Sorting", "sort"),
             ("p", "Click the **정렬** (Sort) button next to the All tab to choose the order of the list. The button reads "
                   "`정렬: 이름 ▾` (Sort: Name) when the sidebar is wide, and `이름 ▾` or `↕` when it is narrow (hover the mouse "
                   "over it to see the current sort mode). Grouping by type or version makes it easy to pick just one type and "
                   "play it in a row — click the first row of the group, {Shift}+click the last row, then **Play Selected**."),
             ("table", ("Sort by", "Order"), (
                 ("이름 (Name)", "Name order (the default)."),
                 ("종류 (Type)", "Groups items by the type at the end of the name (a suffix of letters only, such as `_HD` or `_TX`). "
                               "Names without a type come first, then the types in name order. Within a group, items are in name order."),
                 ("버전 (Version)", "Groups items by version/take number (`v01`, `TK2`). Names without a number come first, then in "
                                  "number order. Within a group, items are in name order."),
                 ("시간 (Time)", "**Most recently modified files first** — re-rendered videos come to the top. The times are read "
                               "when you choose `시간`, so to bring up something that was re-rendered after that, choose `시간` once "
                               "more. For an image sequence, the time of its first frame file is used."),
             )),
             ("list", (
                 "The sort applies to the Mov, Seq and All tabs together. The up/down arrow keys and Play Selected playback also "
                 "follow the order shown.",
                 "The rules for reading the type and version are the same as for the count line below the list — the groups in "
                 "the count line and the groups in the list refer to the same things.",
                 "The chosen sort is kept until you close the window (even if you change the job or the folder). When you start "
                 "the app again, it starts in name order.",
                 "When new videos come into a sorted list (refresh, drag and drop), they go into the place of their group.",
             )),
             ("h", "Take/version colors", "takes"),
             ("p", "When the take/version number at the end of a video name is 2 or higher, the text of that row is shown in a "
                   "different color for each number — retakes stand out at a glance. The rule for reading the number is the same "
                   "as for the count line."),
             ("list", (
                 "**Number 1** (`TK1`, `v01`) and names without a number use the default color; **number 2** is green, "
                 "**number 3** pink, **number 4** purple, **number 5** yellow-green — from number 6 on, the colors repeat "
                 "starting from green.",
                 "This applies to the videos in the Mov tab and the All tab. Image sequences in the All tab are sky blue "
                 "regardless of the take.",
                 "Text such as `TK2 6` or `v02 176` in the **count line** below the list has the same colors — there you can see "
                 "which color is which number.",
                 "For selected rows and the row being played in Play Selected playback (red), those colors take precedence.",
             )),
             ("h", "List mode and thumbnail mode", "thumbs"),
             ("fig", "thumbnails", "Thumbnail mode after clicking Thumb", ()),
             ("list", (
                 "**Thumb** — shows a thumbnail for each video. The first time, generating them takes a while and a progress bar "
                 "shows the progress. Click **List** to go back.",
                 "If a thumbnail does not match its video, select the item and press {R}, or right-click → **썸네일 재생성** "
                 "(Regenerate thumbnail).",
                 "**새로고침** (Refresh, {F5}) — syncs the list with the disk again (removes videos that are gone and adds new "
                 "ones). In thumbnail mode it also regenerates the thumbnails of videos that have become newer because they were "
                 "re-rendered.",
                 "When you go to another app and come back, the list is read again automatically.",
             )),
             ("h", "Right-click menu", "menu"),
             ("fig", "mov_menu", "The menu shown when you select videos and right-click", ()),
             ("table", None, (
                 ("비디오 A 열기 (Open video A) · 비디오 B 열기 (Open video B)", "Opens that video in A or B."),
                 ("애니매틱 하나로 합치기 (Merge into one animatic)",
                  "Joins the selected videos **in name order** and saves them as one file (.mov). Even if the size, aspect ratio, "
                  "frame rate or presence of sound differ, they are merged to match the first video (black bars if the aspect "
                  "ratio differs)."),
                 ("파일 복사 (Copy files)", "Copies the selected files to another folder."),
                 ("썸네일 재생성 (Regenerate thumbnail)", "Regenerates the thumbnails of the selected videos ({R})."),
                 ("미디어 정보 (Media info)", "Shows file information such as codec, resolution and frame count."),
                 ("QuickTime Player로 열기 (Open in QuickTime Player)", "Opens the selected videos in QuickTime Player (Mac only)."),
                 ("다른 앱으로 열기 ▸ (Open in another app)", "Opens them with an app you have registered."),
             )),
             ("h", "Media info (미디어 정보)", "mediainfo"),
             ("fig", "media_info", "Media info window", ()),
             ("p", "Shows the codec (profile, tag), pixel format, color, resolution, frame rate and frame count, duration, bitrate, "
                   "audio tracks, container, file size and path. Click **Show Details** to see the raw ffprobe output; the text can "
                   "be selected with the mouse and copied."),
             ("h", "Open in another app (다른 앱으로 열기)", "openwith"),
             ("list", (
                 "**앱 등록…** (Register app…) — choose an `.app` on Mac or an `.exe` on Windows. You can register several apps, "
                 "and they appear in the menu in the order you registered them. Remove one with **앱 지우기 ▸** (Remove app).",
                 "For a video, the file itself is passed to the app; for a sequence, its **first frame file**.",
                 "If you select several items, a registered app is launched **separately for each file**. If there are more than "
                 "20, YesonCheck asks first.",
                 "Registered apps are saved **on this PC only**. If an app has been deleted or moved, it appears in the menu as "
                 "`(찾을 수 없음)` (not found) — remove it and register it again.",
             )),
         )),
    Page("library", "Shows · folders · bookmarks", "Lists & files",
         "Three ways to load the videos to review — choosing from a show, opening a folder, and bookmarks.",
         (
             ("h", "Show → season → job", "works"),
             ("fig", "controls", "Middle control panel", (
                 "**Open Video A · Open Video B** — choose a file and open it.",
                 "**▶ ROI 설정 · ▶ OCR 분석 · ▶ 결과 관리** (ROI settings · OCR analysis · Result management) — click to expand. "
                 "→ [[ocr]]",
                 "**▶ 수정 사항 주석** (Revision annotations) → [[annotations]]",
                 "**Loop Play** — loop playback.",
                 "**Volume** — sound volume.",
                 "**FPS** — the frame rate of the open video.",
                 "**Enable Wipe Effect · X/Y-Axis Wipe** → [[compare]]",
                 "**Play Selected · Selected Play** → [[playback/playlist|Play Selected playback]]",
                 "**작품선택 · 시즌선택 · job선택** (Select show · Select season · Select job) — choose in order from the top. "
                 "A feature specific to Yeson's in-house workflow.",
             )),
             ("note", "Choosing **show → season → job** and **작품 경로 관리** (Manage show paths) are features specific to Yeson's "
                      "in-house workflow — they are tailored to Yeson's show folder structure and shared settings. Open any other "
                      "folder with **Opening a folder** or **Bookmarks** below."),
             ("list", (
                 "In the three drop-down boxes at the bottom of the middle panel, choose **show → season → job** in that order; "
                 "the videos of that job come into the list.",
                 "Until you choose a season, the job box is empty. For a show without seasons, go straight from show → job.",
                 "The show list is read from the shared settings. If a show is not shown or its folder cannot be found, tell your "
                 "administrator — shows are added and paths are corrected in **작품 경로 관리** in the sidebar (password required).",
                 "On Windows, if the shared settings folder is somewhere else, choose it with **Settings → 공유 설정 폴더 변경...** "
                 "(Change shared settings folder).",
             )),
             ("h", "Opening a folder", "folder"),
             ("list", (
                 "Choose a folder with **Select Folder** in the sidebar, or drop a folder onto the window.",
                 "The videos in that folder go into the Mov tab and the image sequences into the Seq tab. If the folder contains "
                 "only sequences, the sidebar switches straight to the Seq tab.",
             )),
             ("h", "Bookmarks", "bookmarks"),
             ("fig", "bookmarks", "Bookmark manager window", ()),
             ("p", "Keep the folders you open often as bookmarks and open them directly. Bookmarks are saved separately for each "
                   "user of this PC."),
             ("list", (
                 "**Adding** — choose a folder with **Add Bookmark** in the sidebar; a folder dropped onto the window is also "
                 "added automatically.",
                 "**Opening** — open the manager window with the **Bookmarks** button or {P}, then double-click an item ({Enter} "
                 "or **폴더 열기** (Open folder) does the same).",
                 "**Editing a path** — click the selected item once more, or right-click → **경로 수정** (Edit path), to edit it in "
                 "place. Finishing with {Enter} saves it immediately; {Esc} cancels. You can also copy a path in another app and "
                 "paste it.",
                 "**Right-click menu** — 경로 복사 (Copy path) · 경로 수정 (Edit path) · 폴더 열기 (Open folder) · 삭제 (Delete).",
                 "If you change a path to a folder that does not exist right now, it is saved but a warning appears; if you "
                 "change it to a path that is already in the bookmarks, the edit is reverted.",
             )),
         )),
    Page("sequences", "Image sequences", "Lists & files",
         "Open the numbered images of a render folder (`name-0001.tga`, `name-0002.tga` …) like a video, to play and compare them.",
         (
             ("fig", "seq_tab", "A sequence opened from the Seq tab", (
                 "**Seq tab** — the list of sequences.",
                 "**Sequence list** — one row per sequence (name and frame range). Move with {↑} {↓} to open that sequence.",
                 "**Count line** — the number of sequences.",
                 "**File name** — a sequence is shown as `name.seq`.",
             )),
             ("h", "Files treated as a sequence", "names"),
             ("list", (
                 "A set of two or more files named in the form `<name>-NNNN.<ext>` (same name, extension and number of digits).",
                 "Extensions: tga · png · jpg · jpeg · tif · tiff · exr.",
                 "If the same folder has a matching `<name>.mov` (or, if there is none, `.mp4`), the FPS of that video is used; "
                 "otherwise it is 24 fps.",
                 "For a frame whose number is missing, the frame right before it is shown as is.",
             )),
             ("h", "Opening", "open"),
             ("list", (
                 "When you open a folder that contains sequences ([[library/folder|Opening a folder]]), they are listed in the "
                 "Seq tab.",
                 "If you choose a single frame file with **Open Video A/B** or drop it onto the video area, the **whole sequence** "
                 "that the frame belongs to opens from its first frame. Dropping two different sequences opens them in A and B.",
                 "An image that stands alone (only one file) is not a sequence, so it opens as a single picture.",
             )),
             ("h", "Playback · annotations · comparison", "use"),
             ("list", (
                 "Playback, frame stepping, the slider and revision annotations work exactly as with videos.",
                 "A/B wipe works only between sequences (for example `_tk1` versus `_tk2`).",
                 "OCR / cut detection, Play Selected playback and the slider preview cannot be used with sequences.",
             )),
             ("h", "Right-click menu", "menu"),
             ("fig", "seq_menu", "The menu shown when you select sequences and right-click", ()),
             ("table", None, (
                 ("비디오 A로 열기 (Open as video A) · 비디오 B로 열기 (Open as video B)", "Opens that sequence in A or B."),
                 ("선택한 시퀀스로 MOV 만들기… (Make MOV from selected sequences…)",
                  "Creates a mov file for each selected sequence (see below)."),
                 ("썸네일 다시 만들기 (Regenerate thumbnails)", "Regenerates the thumbnails of the selected sequences."),
                 ("정보 보기 (Show info)", "Shows information about that sequence."),
                 ("다른 앱으로 열기 ▸ (Open in another app)",
                  "Passes the first frame file to a registered app. → [[sidebar/openwith|Open in another app]]"),
             )),
             ("h", "Making MOV files from selected sequences (선택한 시퀀스로 MOV 만들기)", "export"),
             ("steps", (
                 "Select one or more sequences in the Seq list.",
                 "Right-click → **선택한 시퀀스로 MOV 만들기…** (Make MOV from selected sequences…)",
                 "Choose the output folder — it must be **a different folder**, not the one that contains the sequences.",
                 "A `<name>.mov` (h264) is created for each sequence. If you cancel in the progress window, the file that was "
                 "being created is deleted.",
             )),
             ("warn", "If a mov with the same name already exists in the output folder, it is overwritten without asking."),
             ("note", "Frames that could not be read (corrupt file, network drop) are filled with the frame right before them to "
                      "keep the length, and the progress window tells you how many frames were filled. Check the source frames "
                      "before delivery."),
         )),
    Page("annotations", "Revision annotations", "Review tools",
         "Leave a “please fix this” note on a specific scene of a video, as drawings and text. Annotations are saved automatically, "
         "and can be exported as a video that includes them.",
         (
             ("fig", "annotation", "Annotation mode on, with an ellipse, text and an arrow drawn", (
                 "**주석 모드** (Annotation mode) — turns red when it is on. While it is on, you draw on the video.",
                 "**도구 · 색상** (Tool · Color) — 텍스트 (text) / 사각형 (rectangle) / 타원 (ellipse) / 선 (line) / 화살표 (arrow); "
                 "빨강 (red) · 노랑 (yellow) · 초록 (green) · 하늘 (sky blue) · 흰색 (white).",
                 "**텍스트 크기 · 선 굵기 · 표시 프레임(시작 ~ 끝)** (Text size · Line width · Display frames (start ~ end)) — the "
                 "display frames are the range in which the annotation is visible.",
                 "**Annotation list** — select an annotation to go to its start frame; you can then change its display frames, "
                 "size and line width.",
                 "**Annotations on the video** — click one in annotation mode and yellow dots appear (the arrow in the picture); "
                 "drag to move or resize it.",
                 "**‘주석 모드’ badge** — indicates that the mode is on. The cursor also becomes a crosshair.",
             )),
             ("h", "Drawing", "draw"),
             ("steps", (
                 "Open a video in A and expand **▶ 수정 사항 주석** (Revision annotations) in the middle panel.",
                 "Turn on **주석 모드** (Annotation mode).",
                 "Choose a **도구** (tool) and a **색상** (color).",
                 "For shapes (rectangle, ellipse, line, arrow), **drag** on the video; for text, **click** and type the text in "
                 "the dialog that appears.",
                 "Set the range in which the annotation is visible with the start and end of **표시 프레임** (display frames). "
                 "If the start and end are the same, it is visible on that one frame only.",
             )),
             ("note", "The text input dialog appears only with the **텍스트** (text) tool. With a shape tool, clicking without "
                      "dragging draws nothing."),
             ("h", "Editing · deleting · exporting", "edit"),
             ("fig", "annotation_export", "The annotation panel scrolled down", (
                 "**선택 주석 삭제** (Delete selected annotation) — deletes the one annotation selected in the list. "
                 "**현재 프레임에 보이는 주석 전체 삭제** (Delete all annotations visible on the current frame) — deletes all the "
                 "annotations currently visible on screen at once.",
                 "**보내기 저장 폴더 선택** (Choose export folder) — the folder where the exported video is put.",
                 "**주석 포함 영상보내기** (Export video with annotations) — creates a new video file with the annotations drawn on it.",
             )),
             ("list", (
                 "The annotation panel has a fixed height; scroll down inside it to reach the delete and export buttons.",
                 "With annotation mode on, **click** an annotation you have drawn and yellow dots appear. Drag to move or resize it.",
                 "Click **주석 포함 영상보내기**, set the file name, then choose the quality — 균형 (권장) (balanced, recommended) · "
                 "고속 (fast) · 고품질 (high quality) — and **오디오 포함** (Include audio).",
             )),
             ("h", "Saving", "save"),
             ("list", (
                 "Annotations are **saved automatically** — they are kept as a file in the `.yesoncheck` folder next to the video.",
                 "When you open the same video again, its annotations are loaded automatically. The same is true when you open it "
                 "on another PC (same shared folder).",
                 "Editing the annotations of the same video from several windows or several PCs does not erase each other's work "
                 "— provided that every PC runs the latest version.",
                 "Annotations of image sequences are saved in the same folder as well.",
             )),
             ("warn", "**OCR ROI 지정** (Set OCR ROI) and **주석 모드** cannot be on at the same time — turning one on turns the "
                      "other off automatically."),
         )),
    Page("ocr", "OCR · cut detection (splitting animatics)", "Review tools",
         "Reads the slate text of an animatic (scene and panel numbers) or detects cuts to divide the video into segments, and "
         "exports each segment as a clip.",
         (
             ("fig", "ocr", "An ROI set and the three sections expanded", (
                 "**OCR ROI 지정** (Set OCR ROI) — click it, then drag over the place in the video where the text is.",
                 "**ROI 초기화 · ROI 트래킹 활성화** (Reset ROI · Enable ROI tracking) — clears the ROI / makes the ROI follow the "
                 "text when it moves.",
                 "**OCR 분석 방식** (OCR analysis mode) — choose from the table below.",
                 "**OCR 구간 추출 · 선택 구간 분석** (Extract OCR segments · Analyze selected range) — analyzes the whole video / "
                 "analyzes only the frame range you specify and merges it into the earlier result.",
                 "**OCR 오픈 · OCR 저장 · OCR 로드** (Open OCR · Save OCR · Load OCR) — reopens the review window / saves the result "
                 "to a file / loads a saved result.",
                 "**ROI** — the area you set.",
             )),
             ("h", "Analysis modes", "modes"),
             ("table", ("Mode", "Use"), (
                 ("Titmouse", "Default OCR settings."),
                 ("King", "Settings tuned for recognizing red text."),
                 ("Bento", "Settings tuned for small text and special formats (for example `Seq 02A_S09 - Panel 6`)."),
                 ("All (사용자 패턴) (custom pattern)", "You write the pattern of the text to read yourself — `#` is a letter, `W` "
                                                   "is a digit. Example: `MS101_B010` → `##WWW_#WWW`"),
                 ("애니매틱 (Auto Cut) (animatic)", "Detects **cuts (where the scene changes)** instead of text. No ROI is needed."),
                 ("애니매틱2 (TransNetV2) (animatic 2)", "Detects cuts with deep learning — including slow transitions such as "
                                                     "dissolves and fades. No ROI is needed. On PCs that do not support it, it "
                                                     "does not appear in the list."),
             )),
             ("h", "Steps", "steps"),
             ("steps", (
                 "Open an animatic in A.",
                 "(For the OCR modes) Expand **▶ ROI 설정** (ROI settings), click **OCR ROI 지정** (Set OCR ROI), and drag over the "
                 "slate text.",
                 "In **▶ OCR 분석** (OCR analysis), choose a mode and click **OCR 구간 추출** (Extract OCR segments). A progress "
                 "window appears, and you can cancel.",
                 "When the analysis finishes, the review window opens. Check the segments and correct them.",
                 "Create a clip for each segment with **전체 내보내기** (Export all) or **선택한 항목만 내보내기** (Export selected only).",
             )),
             ("h", "Review window", "review"),
             ("fig", "review", "OCR review window", (
                 "**씬 리스트** (Scene list) — the list of segments found and the details of the selected segment.",
                 "**프리뷰 영상** (Preview video) — plays the selected segment ({Space} to play/pause, {←} {→} to go one frame at "
                 "a time).",
                 "**타임라인** (Timeline) — a strip showing the segments laid out in order. Change the thumbnail size with the "
                 "slider below it.",
                 "**Table** — for each segment, the picture of the text (ROI 샘플 — ROI sample), the text that was read, the "
                 "corrected text (편집 텍스트 — edited text), and the start and end frames. You can edit the cells directly.",
                 "**Editing buttons** — merge · delete · split · rename · undo.",
                 "**Export** — only the selected segments, or all of them, as clips.",
             )),
             ("table", ("Button", "What it does"), (
                 ("선택한 구간 병합 (Merge selected segments)",
                  "Merges the selected segments into one ({D}). Segments that are not adjacent can be merged too."),
                 ("스마트 병합 (Smart merge)",
                  "Automatically merges adjacent segments that have the same Scene number. When you click it, you first choose "
                  "the mode: Standard (기본) / SCENE (확장) (기본 = default, 확장 = extended)."),
                 ("선택 구간 삭제 (Delete selected segments)", "Deletes the selected segments ({X})."),
                 ("씬 분할 (Split scene)", "Splits the selected segment in two at the frame you specify."),
                 ("일괄 리네임 (Batch rename)", "Changes the 편집 텍스트 (edited text) in bulk by a rule (for example, removing "
                                           "` - Panel A`)."),
                 ("↶ 실행 취소 (Undo) · ↷ 다시 실행 (Redo)", "Undoes or redoes the edit you just made (merge, delete, split, rename)."),
                 ("웹분석 (Web analysis)", "Turns the result into a web page (a report) and opens it in the browser. Edits made in "
                                        "the review window are reflected in the report right away."),
                 ("재분석 (Re-analyze)", "Closes the review window and returns to the main window — for analyzing again with a "
                                       "different ROI or mode."),
                 ("선택한 항목만 내보내기 (Export selected only) · 전체 내보내기 (Export all)",
                  "Creates a clip file for each segment ({R} for all). You choose the folder to save to."),
             )),
             ("list", (
                 "**사운드 포함** (Include sound) — when checked, the clips include sound.",
                 "**내보내기 모드** (Export mode) — 균형 (빠르고 정확) (balanced: fast and accurate) · 고속 (fast) · 고품질 (최고 화질) "
                 "(high quality: best picture). In 고속 mode you choose the bitrate.",
                 "The length of a segment is shown as a number of frames.",
             )),
             ("warn", "The analysis result is lost when you open a video in A (even if you open the same video again), and also "
                      "when you close the app. To keep it, save it to a file with **OCR 저장** (Save OCR) in the main window and "
                      "load it later with **OCR 로드** (Load OCR). If you only closed the review window, you can reopen it with "
                      "**OCR 오픈** (Open OCR)."),
             ("note", "OCR and cut detection cannot be used with image sequences."),
         )),
    Page("settings", "Settings (Settings menu)", "Settings & management",
         "The items under Settings in the menu bar. The items shown differ slightly between Mac and Windows.",
         (
             ("fig", "settings_menu", "Settings menu (Mac)", ()),
             ("table", ("Item", "What it does"), (
                 ("재생 디코더 (Mac) (Playback decoder)",
                  "How ProRes is opened — `VideoToolbox (기본)` (default) / `ffmpeg (예전 방식)` (old method). The choice is "
                  "applied right away to the video you are viewing. Mac only. → [[prores]]"),
                 ("화면 그리기 (Windows) (Display rendering)",
                  "How the picture is drawn — CPU (기본 — default) / GPU. If 4K playback stutters, try GPU. It applies from the "
                  "next window you open, and the `지금 이 창:` (this window:) line in the menu shows the method actually in use. "
                  "Windows only."),
                 ("축소 필터 (Windows) (Downscale filter)",
                  "The filter used when the video is **scaled down** to fit the window — `Linear (기본)` (default) / "
                  "`고품질 (면적 평균)` (high quality, area average). If thin lines look uneven (shimmering) in the scaled-down "
                  "view, try 고품질. The choice is applied to this window right away. Every frame is scaled down on the CPU, so "
                  "if 4K playback becomes slow, switch back to Linear. At 1:1 or when the view is enlarged, the two filters are "
                  "the same. Windows only."),
                 ("슬라이더 썸네일 (Slider thumbnails)", "Turns the [[playback/hover|slider preview]] on and off (on by default)."),
                 ("공유 설정 폴더 변경... (Change shared settings folder)",
                  "Chooses the folder that holds the shared settings such as the show paths. Windows only."),
             )),
             ("note", "재생 디코더, 화면 그리기, 축소 필터 and 슬라이더 썸네일 are saved **on this PC only**. Other YesonCheck windows "
                      "that are already open pick up the change the next time they are started."),
         )),
    Page("windows", "Multiple windows · default video app", "Settings & management",
         "In YesonCheck, each window is one running copy of the app. You can open several windows and review videos side by side.",
         (
             ("h", "Opening more windows", "new"),
             ("list", (
                 "**Mac** — launch YesonCheck again from the Applications folder (응용 프로그램), Launchpad or Spotlight, or "
                 "**click its icon in the Dock**, and one empty new window opens. Switching to it with ⌘Tab or by clicking a "
                 "window does not open a new window.",
                 "Windows that are already open stay as they are. To bring back a window that was minimized to the Dock, click "
                 "that window's icon on the right side of the Dock.",
                 "If you **double-click** a video (.mov, .mp4) in Finder or File Explorer, or open it with **다음으로 열기** "
                 "(Open With; on Windows, **연결 프로그램** — Open with), a new window opens that video in A. If you open several "
                 "at once, one window opens for each video.",
                 "While a window is closing (up to about 30 seconds while it finishes its work), a new window may not open — "
                 "open it again after the window has closed completely.",
             )),
             ("h", "Opening videos in YesonCheck by double-click", "default"),
             ("fig", "help_menu", "Help menu (Mac)", ()),
             ("table", None, (
                 ("Mac", "The first time you start a new version, the app asks once: “동영상(.mov·.mp4)을 더블클릭하면 YesonCheck로 "
                         "열까요?” — in English, “Open videos (.mov, .mp4) in YesonCheck when you double-click them?” To change "
                         "this later, choose **Help → 동영상 기본 앱으로 정하기…** (Set as default video app…)."),
                 ("Windows", "Right-click a video → in **연결 프로그램** (Open with), choose **Yeson Checker** and click **항상** "
                             "(Always) — once each for .mov and .mp4. **Help → 동영상 기본 앱 설정 열기…** (Open default video app "
                             "settings…) opens the default apps settings screen of Windows."),
             )),
             ("note", "On Mac, the default app cannot be set from an app opened directly from the disk image (dmg). Move the app "
                      "to the Applications folder and open it from there."),
             ("h", "Help menu", "help"),
             ("table", None, (
                 ("사용법 (Manual)", "Opens this manual ({F1})."),
                 ("업데이트 확인… (Check for updates…)", "Checks right away whether there is a new version. → [[update]]"),
                 ("동영상 기본 앱으로 정하기… (Set as default video app…) / 동영상 기본 앱 설정 열기… (Open default video app settings…)",
                  "The default app setting described above (Mac / Windows)."),
                 ("정보 (About)", "Shows the current version."),
             )),
         )),
    Page("update", "Updating", "Settings & management",
         "When a new version is released, the app tells you; when you click, it downloads and installs the update and then "
         "starts again.",
         (
             ("fig", "update_banner", "New-version notification banner", ()),
             ("h", "How to update", "do"),
             ("steps", (
                 "When there is a new version, a notification banner appears at the top of the window. The app checks when it "
                 "starts and every 3 hours while it is running; you can also check right away with **Help → 업데이트 확인…** "
                 "(Check for updates…).",
                 "Click **바뀐 점** (What's new) to see what has changed.",
                 "Click **업데이트** (Update) and it proceeds in this order: download → the app closes → install → the app starts "
                 "again. Click **나중에** (Later) to close the banner; that version is not announced again until you restart the app.",
             )),
             ("list", (
                 "Nothing changes until you click. If the update fails, the current version starts as it is and tells you the reason.",
                 "PCs without internet access get the update from the shared folder.",
                 "You can see the current version in the window title and in **Help → 정보** (About).",
             )),
             ("h", "Updating while several windows are open", "many"),
             ("list", (
                 "When you click **업데이트** (Update), the app tells you how many other YesonCheck windows there are and asks "
                 "once. Click **모두 닫고 업데이트** (Close all and update): the other windows close normally, and only the window "
                 "where you clicked starts again in the new version.",
                 "Windows that are **busy with a job** such as OCR analysis or export, and windows with **unsaved OCR results**, "
                 "are shown in the confirmation dialog. If you continue, those jobs are stopped and the unsaved results are lost "
                 "— to keep them, cancel and save first.",
                 "If there is a window that does not close, the update is stopped. Close that window and click again.",
                 "If another user account on the same computer has YesonCheck running, the update is not performed.",
                 "If you open YesonCheck while an update is in progress, it only shows “업데이트 중입니다” (Updating) for a moment "
                 "and does not open. Open it again after the update has finished.",
             )),
             ("warn", "**Please update every PC to the new version.** If an old version remains, that PC can erase the annotations "
                      "of other windows and PCs when it saves."),
             ("p", "What changed in each version is on the [[releases]] page."),
         )),
    Page("prores", "ProRes · 4K playback", "Reference",
         "ProRes mov files are opened with a faster method automatically. There is nothing you need to do; this page only lists "
         "things that are good to know.",
         (
             ("h", "How files are opened", "how"),
             ("table", None, (
                 ("Mac", "Opened with the decoder built into the Mac (VideoToolbox) and drawn straight on the GPU — all ProRes "
                         "that is not HDR."),
                 ("Windows", "Opened with the ffmpeg bundled in the app."),
                 ("Other files", "Other formats such as h264 are opened exactly as before. Frame numbers are the same with every method."),
             )),
             ("h", "Rewinding and seeking get faster after you pause (ffmpeg method)", "cache"),
             ("list", (
                 "On Windows, and on Mac for videos opened with the ffmpeg method, the whole video is read into memory once you "
                 "stop playing and navigating and stay idle for a moment. After it has all been read, rewinding, {←}, the slider "
                 "and loop playback respond without waiting.",
                 "This uses quite a lot of memory — a 4K video of about 14 seconds (334 frames) takes about 8.3 GB. The memory "
                 "comes back as soon as you close the video or open another one.",
                 "One window uses at most 20% of the PC's memory this way; if the video is larger than that or memory is short, "
                 "only the most recent frames are kept.",
                 "If you open several windows and a 4K video in each, that much more memory is used. If memory is tight, close "
                 "the windows you have finished with.",
             )),
             ("h", "Display color", "color"),
             ("p", "The app draws the values in the file as they are, without converting them for the monitor. QuickTime Player "
                   "changes the colors according to the file's color tags and the monitor, so **the picture in the app can look "
                   "different from QuickTime.**"),
             ("h", "Speed", "speed"),
             ("list", (
                 "Use the `실제` (actual) value in the info row to see whether playback is running in real time. → [[playback]]",
                 "Playing two 4K videos together with A/B wipe can be slower.",
                 "4K ProRes 4444 has to read about 130 MB per second, so on a 1 Gbps network the first playback may stutter "
                 "(after the file has been read once, it is smooth).",
                 "If 4K stutters on Windows, try **Settings → 화면 그리기 (Windows) → GPU** (Display rendering → GPU).",
             )),
             ("p", "If a problem occurs, you can go back to the old method in the way described on the [[trouble]] page."),
         )),
    Page("trouble", "Troubleshooting", "Reference",
         "Common symptoms and how to fix them, and where to find the log files to send when you report a problem.",
         (
             ("h", "By symptom", "symptoms"),
             ("table", ("Symptom", "Fix"), (
                 ("No sound on Windows", "Install K-Lite Codec Pack (Basic)."),
                 ("New videos do not appear in the list", "**새로고침** (Refresh) or {F5}."),
                 ("A thumbnail does not match its video", "Select the item and press {R}, or click **새로고침** (Refresh) in "
                                                          "thumbnail mode."),
                 ("B is black in the wipe", "A and B have different sizes (resolutions). Compare videos of the same size."),
                 ("4K playback stutters on Windows", "**Settings → 화면 그리기 (Windows) → GPU** (Display rendering → GPU)."),
                 ("Thin lines shimmer in the scaled-down view on Windows",
                  "**Settings → 축소 필터 (Windows) → 고품질 (면적 평균)** (Downscale filter → High quality, area average)."),
                 ("On Mac, the video area is empty or a drawing error dialog appears",
                  "**Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식)** (Playback decoder → ffmpeg, old method)."),
                 ("A slider preview error dialog keeps appearing", "Turn off **Settings → 슬라이더 썸네일** (Slider thumbnails)."),
                 ("ProRes videos do not open on Windows",
                  "This happens when security software blocks the local communication inside the app. Open them the old way "
                  "with the environment variable `YESONCHECK_MOVIE_SOURCE=cv2` described below."),
                 ("The app does not start on Windows after choosing GPU",
                  "Delete the `display_renderer` line in `%LOCALAPPDATA%\\YesonCheck\\prefs.json`, or start the app with the "
                  "environment variable `YESONCHECK_VIEWPORT=raster`."),
                 ("A show is not in the list or its folder cannot be found",
                  "Tell your administrator — it is fixed in **작품 경로 관리** (Manage show paths)."),
             )),
             ("h", "App logs (please send them when you report a problem)", "logs"),
             ("table", None, (
                 ("Mac", "`~/Library/Logs/YesonCheck`"),
                 ("Windows", "`%LOCALAPPDATA%\\YesonCheck\\logs`"),
             )),
             ("list", (
                 "Each window creates one `yesoncheck_<date>_<number>.log` file. Files older than 30 days are deleted automatically.",
                 "If an error dialog appeared, please send the text of that dialog as well.",
             )),
             ("h", "Going back to the old method (environment variables)", "env"),
             ("p", "Set an environment variable below and **start the app again**; that feature then goes back to the old method. "
                   "To undo this, delete the variable and start the app again."),
             ("table", ("Environment variable", "What it does"), (
                 ("`YESONCHECK_MOVIE_SOURCE=cv2`", "Turns off all the fast ProRes playback and opens files the old way."),
                 ("`YESONCHECK_FRAME_CACHE=ring`", "Does not read the whole video into memory (the fast decoder stays as it is)."),
                 ("`YESONCHECK_MAC_NATIVE=off`", "(Mac) Opens files with the ffmpeg method instead of VideoToolbox, for that run only."),
                 ("`YESONCHECK_VIDEO_ITEM=pixmap`", "(Mac) Draws the picture the old way."),
                 ("`YESONCHECK_VIEWPORT=raster`", "(Windows) Draws the picture on the CPU."),
             )),
             ("note", "**Setting an environment variable on Windows** — 설정 (Settings) → 시스템 (System) → 정보 (About) → "
                      "고급 시스템 설정 (Advanced system settings) → 환경 변수 (Environment Variables) → under 사용자 변수 (User "
                      "variables), click **새로 만들기** (New). Or run `setx YESONCHECK_MOVIE_SOURCE cv2` in Command Prompt."),
         )),
)
