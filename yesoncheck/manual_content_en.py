"""English text of the user manual (Help → User guide) — mirrors manual_content.PAGES block for block (no Qt, data only).

`manual_content`(한글)의 쪽·블록을 **같은 차례·같은 모양**으로 옮긴 영어 글. 한쪽을 고치면 다른 쪽도 함께 고칠 것 —
서로 같아야 하는 것: 쪽 key와 차례, 블록 종류와 차례, 닻, 그림 이름, 그림 설명 수(그림 위의 번호 표지와 짝), 단축키 표의 줄 수,
표의 줄·칸 수, 목록 항목 수, 글 안의 링크 대상(`[[쪽/닻|글]]`의 쪽·닻), `{키}`, 화면 글자 표시 `{{키}}`.
`Page`와 `RELEASES_KEY`는 `manual_content`의 것을 그대로 씀(여기서 다시 정하지 않음). `GROUPS`는 한글 `GROUPS`와 같은 자리끼리 짝.

화면 글자 규칙 (2026-11-16 UI 개편 PR 4부터 — 메인 창은 한국어 / English 두 언어):
- 메인 창의 이름(메뉴·재생 줄·사이드바·도구 패널·우클릭 메뉴·Settings 항목 …)은 한글 쪽과 **같은 `{{키}}`** 로 적음 — English 화면
  글자가 글자 표(`ui_text`)에서 나와 굵게 보임. 따로 굵게 하거나 한글 이름을 덧붙이지 않음. 한글 쪽이 `{{키}}` 없이 적은 메인 창 이름은
  (표시가 서로 같아야 하므로) English 화면 글자를 손으로 적음(주석 패널의 `Tool · Color` — 글자 표의 글에 쌍점이 붙어 있어 표시로 쓰지 않음). 값 자리가 든 글(개수 줄
  `3 sequences`, 정렬 단추 `Sort: Name ▾`, fps 칸의 `real`)도 English 화면의 글로.
- 딸린 창(OCR 검토 창·북마크 관리 창·내보내기 창·알림 창 …)의 이름은 화면에 한글로 남으므로 **한글 그대로** 적고, 그 쪽에서 처음 나올 때
  괄호 안에 영어 뜻을 붙임. 메인 창과 같은 낱말이 든 이름(북마크 관리 창의 ‘폴더 열기’, ‘모두 닫고 업데이트’ …)은 ‘…’ 안에 적음 — 가드
  시험(`test_english_manual_has_no_korean_main_window_text`)이 ‘…’ 안은 보지 않음.
- Settings의 `언어 (Language)`는 두 언어에서 같은 글이라 그대로.
- OS의 화면 글자(Finder·Windows — 앱이 아니라 OS 언어를 따름)는 거꾸로 **영어를 앞에, 한글을 괄호에**: `Open With (다음으로 열기)`·
  `Settings (설정)` — 영문 매뉴얼을 읽는 사람의 OS는 영문일 가능성이 큼.
- 키 표시(`{N}`, 단축키 표의 "F (ㄹ)")는 한글 쪽과 같은 글자. 한글 낱말이 든 키만 옮김("마우스 휠" → "Mouse wheel").
- 코드 표시 안의 자리 이름(`<이름>.mov` → `<name>.mov`)은 옮김.
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
             ("fig", "overview", "Main window (with the annotation panel open)", (
                 "**Menus** — {{menu.file}}, {{menu.view}}, {{menu.playback}}, {{menu.compare}}, {{menu.tools}}, **Settings** and **Help**. "
                 "On Mac they are in the menu bar at the top of the screen. → [[start/menus|Menus]]",
                 "**Sidebar** — choosing a show, the folder and bookmark buttons, the video list (Mov, Seq and All tabs) and the "
                 "button for playing selected videos. → [[sidebar]]",
                 "**Video area** — where the video is shown. Use the mouse wheel to step one frame at a time; when zoomed in, drag "
                 "to pan. Right-click it for all the menus. → [[view]]",
                 "**Tool panel** — {{panel.annotation}} and {{panel.ocr}}. Open and close it with {{transport.annotate}} or "
                 "{{transport.ocr}} on the playback bar, or with {N}.",
                 "**Time slider** — click or drag to move; hover the mouse over it to preview the picture at that position.",
                 "**Playback bar** — file name, playback buttons, frame number, time, fps, wipe and panel toggles, volume. → [[playback]]",
             )),
             ("h", "Menus", "menus"),
             ("fig", "menus", "The Playback menu opened", ()),
             ("p", "The menu bar has {{menu.file}} · {{menu.view}} · {{menu.playback}} · {{menu.compare}} · {{menu.tools}} · "
                   "**Settings** · **Help**. The parentheses at the end of an item show its shortcut — you can just press the key without "
                   "opening the menu ({Enter} only while the list has focus). Right-clicking the video area brings up all the same menus too. → [[view/context|Right-click menu]]"),
             ("table", ("Menu", "What it contains"), (
                 ("{{menu.file}}", "Open video A and B, open a folder, add and manage bookmarks"),
                 ("{{menu.view}}", "Fit, original size, zoom in and out, full screen, hide controls, theme, file name text → [[view]]"),
                 ("{{menu.playback}}", "Play/pause, step one frame, go to start and end, loop playback, play the selected videos in a "
                                       "row → [[playback]]"),
                 ("{{menu.compare}}", "Enable wipe, X axis and Y axis → [[compare]]"),
                 ("{{menu.tools}}", "Annotation panel, OCR panel, open/close the tool panel, manage show paths → [[annotations]] · "
                                    "[[ocr]]"),
                 ("Settings · Help", "Settings, and the user guide and updates → [[settings]] · [[update]]"),
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
                 ("{{menu.file}} → {{menu.file.open_a}} · {{menu.file.open_b}}", "Choose a file and open it in A or B."),
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
                 "If something needs fixing, open the {{panel.annotation}} panel with {{transport.annotate}} on the playback bar and "
                 "mark it on the video. → [[annotations]]",
                 "Use {{annot.export}} to create a video that includes the annotations, and pass it on.",
             )),
             ("tip", "You can open this manual again at any time with {F1} or Help → {{help.manual}}. For a quick look at the "
                     "shortcuts only, see the [[shortcuts]] page."),
         )),
    Page("install", "Installation", "Getting started",
         "How to install YesonCheck on a new computer. Once it is installed, the app tells you about each new version and downloads and installs it.",
         (
             ("h", "Download", "download"),
             ("p", "The installers for each version are on the Releases page on GitHub (`github.com/yesonsys03-web/yesoncheck/releases`). "
                   "The one marked **Latest** is the newest version."),
             ("table", ("Computer", "File"), (
                 ("Windows", "`YesonCheck_Setup_<version>.exe`"),
                 ("Mac (Apple Silicon)", "`YesonCheck_Autocut_AppleSilicon_<version>.dmg`"),
                 ("Mac (Intel)", "`YesonCheck_Autocut_Intel_<version>.dmg`"),
             )),
             ("p", "The Mac version needs macOS 12.3 or later. To see which file you need, open Apple menu → **About This Mac** "
                   "(이 Mac에 관하여): if **Chip** shows something like Apple M1 or M2, it is Apple Silicon; if **Processor** shows Intel, it is Intel."),
             ("h", "Windows", "windows"),
             ("steps", (
                 "Run the downloaded `YesonCheck_Setup_<version>.exe`. It installs without administrator rights (no UAC prompt).",
                 "The default install folder is `C:\\YesonCheck` (right under the system drive) — it is best to keep it. Some features such as OCR "
                 "fail in a path that contains non-ASCII characters (such as Korean) or spaces. If that folder cannot be created on the PC, choose "
                 "another folder you can write to whose whole path has no non-ASCII characters or spaces — but not inside "
                 "`%LOCALAPPDATA%\\YesonCheck`, the app's settings and log folder: an app installed there cannot be updated.",
                 "You can choose **Create a desktop shortcut**. A **Yeson Checker** entry is added to the Start menu.",
                 "If you finish with ‘Yeson Checker 실행’ (Run Yeson Checker) checked on the last screen, the app starts right away.",
             )),
             ("p", "Running the installer again on a PC where it is already installed installs over the same folder, and your settings stay."),
             ("warn", "To hear the sound of videos, also install **K-Lite Codec Pack** (the Basic edition is enough). Without it the picture shows "
                      "but there is no sound. → [[playback/sound|Sound]]"),
             ("h", "Mac", "mac"),
             ("steps", (
                 "Double-click the downloaded `.dmg` to open it.",
                 "In the window that opens, drag the `YesonCheck_Autocut_AppleSilicon` app (`YesonCheck_Autocut_Intel` for the Intel file) onto the "
                 "**Applications** folder next to it.",
                 "Open the app from the **Applications** folder in Finder (응용 프로그램 on a Korean Mac). An app opened directly inside the dmg "
                 "cannot install updates and cannot be set as the default app for videos.",
             )),
             ("note", "When you open an app downloaded from the internet or a messenger for the first time, macOS may block it — this app has no "
                      "Apple signature or notarization. After it is blocked once, click **Open Anyway** (그래도 열기) near the bottom of "
                      "**System Settings → Privacy & Security** (시스템 설정 → 개인정보 보호 및 보안) (on macOS 12: System Preferences → Security "
                      "& Privacy, General tab). Or run "
                      "`xattr -dr com.apple.quarantine /Applications/YesonCheck_Autocut_AppleSilicon.app` in Terminal (for Intel, end it with "
                      "`YesonCheck_Autocut_Intel.app`) and then open the app. From macOS 15, right-click → Open in Finder no longer gets past the block."),
             ("h", "After installing", "after"),
             ("list", (
                 "On a **Mac**, the first time you start it, YesonCheck asks once whether double-clicking a video (.mov, .mp4) should open it in "
                 "YesonCheck. → [[windows/default|Default app for videos]]",
                 "After that, when a new version comes out a notice bar appears at the top of the window; click it to download and install — you "
                 "do not need to reinstall by hand. → [[update]]",
                 "On a PC without Yeson's in-house shared settings folder (outside the company), a ‘공유 설정 오류’ (Shared settings error) window "
                 "appears at every start (on Windows it is preceded by a ‘공유 설정 폴더 선택’ (Choose the shared settings folder) notice and a "
                 "folder picker — just cancel). After you close it, everything works except choosing shows and managing show paths. "
                 "→ [[library/works|Choosing a show]]",
             )),
             ("h", "Uninstalling", "remove"),
             ("list", (
                 "**Windows** — remove **Yeson Checker** in Settings → Apps (설정 → 앱).",
                 "**Mac** — move the app in the Applications folder to the Trash.",
                 "Either way, settings and logs stay in your user folder, so they carry over if you install again.",
             )),
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
                 ("Home", "Stop and go to the first frame — while playing selected videos, stop at the start of the current "
                          "video; the playlist does not end"),
                 ("End", "Stop and go to the last frame"),
                 ("L (ㅣ)", "Loop playback on ↔ off"),
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
                 ("N (ㅜ)", "Open ↔ close the tool panel (annotations, OCR) — the annotation panel the first time, after that the one "
                            "you used last"),
                 ("W (ㅈ)", "Wipe on ↔ off (when B is open)"),
                 ("T (ㅅ)", "Dark theme ↔ light theme"),
                 ("B (ㅠ)", "Show ↔ hide the file name and frame number text"),
                 ("Ctrl+O", "Reset the position and size of the overlay controls (⌘+O on Mac)"),
             )),
             ("note", "After you click in the list and the list has focus, {T} and {B} do not respond. Click once on the video side "
                      "and then press the key (the other keys work even while the list has focus — {Home} and {End} also step to "
                      "the first or last frame, not to the first or last row of the list)."),
             ("h", "List (after clicking in the sidebar, while the list has focus)", "list"),
             ("keys", (
                 (("↑", "↓"), "Move to the item above / below and open it in A (Mov · Seq · All)"),
                 ("Enter", "Start playing the selected videos — plays them one after another (Mov · All)"),
                 ("\\", "Pause ↔ resume playing the selected videos — starts it if it is not running (Mov · All)"),
                 ("Ctrl+Click", "Add items to the selection one at a time (⌘+Click on Mac)"),
                 ("Shift+Click", "Select everything in between as well"),
             )),
             ("h", "App windows · other", "misc"),
             ("keys", (
                 ("O (ㅐ)", "Open video A"),
                 ("I (ㅑ)", "Open a folder"),
                 ("P (ㅔ)", "Open the bookmark manager window (if there are no bookmarks at all, only a notice appears)"),
                 ("R (ㄱ)", "Regenerate the thumbnails of the items selected in the list — same as {{side_menu.thumbnails}} in the "
                            "right-click menu on the Mov tab and {{side_menu.seq.thumbnails}} on the Seq tab; on the All tab, both "
                            "the selected videos and sequences"),
                 ("C (ㅊ)", "Copy the videos selected in the list to another folder — same as {{side_menu.copy}} in the right-click menu "
                            "(on the All tab, movs only; not available on the Seq tab)"),
                 ("J (ㅓ)", "Merge the videos selected in the list into one — same as {{side_menu.merge}} in the right-click menu "
                            "(on the All tab, movs only; not available on the Seq tab)"),
                 ("M (ㅡ)", "Show information about the item selected in the list — same as {{side_menu.info}} for a video and "
                            "{{side_menu.seq.info}} for a sequence"),
                 ("[", "Open the item selected in the list as video A — same as {{side_menu.open_a}} in the right-click menu (not during selected playback)"),
                 ("]", "Open the item selected in the list as video B — for putting the video to wipe against in B (same as "
                       "{{side_menu.open_b}} in the right-click menu; not during selected playback)"),
                 ("F5", "Refresh the list"),
                 ("F1", "User guide (this manual)"),
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
             ("fig", "playbar", "Playback bar and time slider", (
                 "**File name** — the file open in A. While the wipe is on, B's name is shown as well.",
                 "**Playback buttons** — go to start ({Home}) · step back one frame ({←}) · play/pause ({Space}) · step forward one "
                 "frame ({→}) · go to end ({End}). The go-to-start and go-to-end buttons stop playback.",
                 "{{transport.loop}} — after reaching the end, starts again from the beginning.",
                 "**Frame number** — the current frame (starting from 1) / the total number of frames and the length in feet and "
                 "frames (16 frames = 1 foot; `3F 00f` means 3 feet 0 frames). Click the box, type a number and press {Enter} to "
                 "go to that frame.",
                 "**Time · length** — current time / total length.",
                 "**fps** — the frame rate of the video. During playback, the speed actually achieved (`real`) is shown as well.",
                 "**Toggles** — {{transport.wipe}}, {{transport.wipe.x}}, {{transport.wipe.y}}, {{transport.annotate}}, "
                 "{{transport.ocr}}. → [[compare]]",
                 "**Volume** — sound volume. In a narrow window only the icon remains.",
                 "**Time slider** — click to go to that position; drag to scrub through quickly.",
             )),
             ("h", "Playback", "play"),
             ("keys", (
                 ("Space", "Play / pause"),
                 (("←", ","), "Previous frame"),
                 (("→", "."), "Next frame"),
                 ("Home", "First frame"),
                 ("End", "Last frame"),
                 ("Mouse wheel", "Step one frame at a time (anywhere in the window except over the list)"),
             )),
             ("list", (
                 "Turn on the {{transport.loop}} button on the playback bar to repeat from the beginning after reaching the end.",
                 "The fps box on the playback bar shows the frame rate of the video.",
                 "If the `real` value in the fps box during playback is far below the original fps, playback is slow. The value is "
                 "measured once per second, so it fluctuates by about ±1; while playback is stopped and during the first second "
                 "after it starts, only the original FPS is shown.",
             )),
             ("h", "Going to a frame number", "frame"),
             ("p", "Click the frame box on the playback bar, type a number and press {Enter} to go to that frame. A number outside "
                   "the range goes to the nearest end, and {Esc} reverts the number you were typing. You can also click the box and "
                   "type a number during playback (playback does not stop)."),
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
                 "To turn it off, uncheck Settings → {{settings.hover_thumbs}} — it is on by default, and the setting is saved on "
                 "this PC only.",
             )),
             ("h", "Playing selected videos in a row", "playlist"),
             ("p", "Plays the videos selected in the list one after another."),
             ("steps", (
                 "Select several videos in the list — Ctrl+click (⌘+click on Mac) to add one at a time, Shift+click to include "
                 "everything in between.",
                 "Click the {{playlist.play}} button at the bottom of the sidebar, or press {Enter} in the list (it is also in the "
                 "{{menu.playback}} menu).",
                 "To pause or resume, click the same button or press {\\} — while playing, the button reads {{playlist.pause}}.",
                 "To finish, click the {{playlist.end}} button that appears below it — playback stops and returns to the first frame.",
             )),
             ("list", (
                 "Videos that are not on disk at that moment are skipped.",
                 "In the All tab, **only the videos (mov)** among the selected items are played and sequences are skipped. "
                 "Right-click → {{side_menu.all.select_movs}} selects only the videos.",
                 "In the Seq tab, the {{playlist.play}} button is disabled.",
                 "While the selected videos are playing, the go-to-start button on the playback bar ({Home}) stops and goes only to "
                 "the start of the current video — the playlist does not end, so playing again plays that video from the start and then moves on to the next one.",
             )),
             ("h", "Sound", "sound"),
             ("p", "Adjust it with the volume slider at the right end of the playback bar (hover the mouse over it to see the "
                   "percentage)."),
             ("warn", "On **Windows**, K-Lite Codec Pack (Basic) must be installed to hear the sound of a video. Without it, the "
                      "picture plays but there is no sound."),
         )),
    Page("view", "Viewing", "Viewing & playback",
         "Zooming, full screen, hiding the controls, themes, and the file name / frame number display.",
         (
             ("h", "Right-click menu", "context"),
             ("fig", "context_menu", "Right-clicking the video area", ()),
             ("p", "Right-click the video area and all the menus of the menu bar ({{menu.file}} … Help) appear — so every feature is "
                   "within reach even when the controls are hidden with {V} or the video is in video-only full screen."),
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
                 "{N} — opens and closes the tool panel (annotations, OCR). The first time it opens the annotation panel; after "
                 "that, the panel you used last. Closing it keeps the annotation mode, the ROI and the values you entered.",
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
                 "{{transport.wipe}} — turns the wipe on ({W}).",
                 "{{transport.wipe.x}} · {{transport.wipe.y}} — split left and right with a vertical line / split top and bottom "
                 "with a horizontal line. Both can be on at the same time.",
                 "**Wipe line** — drag it to move it. A is to the left of (above) the line and B is to the right of (below) it.",
                 "**File name** — while the wipe is on, the names of A and B are shown together.",
             )),
             ("h", "Steps", "steps"),
             ("steps", (
                 "Open a video in A.",
                 "Open B with {{menu.file}} → {{menu.file.open_b}}, or select a video in the list and press {]} (same as right-click "
                 "→ {{side_menu.open_b}}).",
                 "Turn on {{transport.wipe}} on the playback bar ({W}) and click {{transport.wipe.x}} or {{transport.wipe.y}}. The "
                 "{{menu.compare}} menu has the same items.",
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
                 "{{sidebar.works}} — choose show → season → job to put that job's videos into the list (shown only on PCs that "
                 "have loaded the shows). → [[library/works|Shows]]",
                 "{{sidebar.open_folder}} · {{sidebar.bookmarks}} ▾ · {{sidebar.refresh}} — choose a folder and put the videos and "
                 "sequences in it into the list ({I}) / {{sidebar.bookmark.add}} · {{sidebar.bookmark.manage}} "
                 "([[library/bookmarks|Bookmarks]]) / read the list again ({F5}).",
                 "{{sidebar.mode.list}} · {{sidebar.mode.thumb}} — change how the list looks.",
                 "**Mov · Seq · All tabs** — videos / image sequences / both. The button next to the All tab (`Name ▾` in the picture) is the **Sort** button. "
                 "→ [[sidebar/sort|Sorting]]",
                 "**Video list** — click an item to open it in A. Selected items are orange.",
                 "**Count line** — the number of items in the tab you are viewing.",
                 "{{playlist.play}} — plays the selected videos one after another. → [[playback/playlist|Playing selected videos]]",
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
                 "Items are counted per kind at the end of the name (a suffix of letters only, such as `_HD` or `_TX`; `Base` "
                 "when there is none), and the **versions/takes** (`TK1`, `v01`) within each kind are shown in parentheses. "
                 "Example: `450 items — Base 225 (TK1 225) · HD 225 (TK1 225)`",
                 "The Seq tab counts sequences, not frames. Example: `3 sequences`",
                 "The All tab shows the count per format on the first line (`10 items — mov 7 · png 3`) and the kinds and versions "
                 "on the second line.",
             )),
             ("h", "Sorting", "sort"),
             ("p", "Click the **Sort** button next to the All tab to choose the order of the list. The button reads `Sort: Name ▾` "
                   "when the sidebar is wide, and `Name ▾` or `↕` when it is narrow (hover the mouse over it to see the current "
                   "sort mode). Grouping by kind or version makes it easy to pick just one kind and play it in a row — click the "
                   "first row of the group, {Shift}+click the last row, then {{playlist.play}}."),
             ("table", ("Sort by", "Order"), (
                 ("{{sort.name}}", "Name order (the default)."),
                 ("{{sort.kind}}", "Groups items by the kind at the end of the name (a suffix of letters only, such as `_HD` or `_TX`). "
                                   "Names without a kind come first, then the kinds in name order. Within a group, items are in "
                                   "name order."),
                 ("{{sort.version}}", "Groups items by version/take number (`v01`, `TK2`). Names without a number come first, then "
                                      "in number order. Within a group, items are in name order."),
                 ("{{sort.time}}", "**Most recently modified files first** — re-rendered videos come to the top. The times are read "
                                   "when you choose {{sort.time}}, so to bring up something that was re-rendered after that, choose {{sort.time}} "
                                   "once more. For an image sequence, the time of its first frame file is used."),
             )),
             ("list", (
                 "The sort applies to the Mov, Seq and All tabs together. The up/down arrow keys and playing the selected videos "
                 "also follow the order shown.",
                 "The rules for reading the kind and version are the same as for the count line below the list — the groups in "
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
                 "For selected rows and the row being played while playing the selected videos (red), those colors take precedence.",
             )),
             ("h", "List mode and thumbnail mode", "thumbs"),
             ("fig", "thumbnails", "Thumbnail mode after clicking {{sidebar.mode.thumb}}", ()),
             ("list", (
                 "{{sidebar.mode.thumb}} — shows a thumbnail for each video. The first time, generating them takes a while, and "
                 "while they are being generated a progress bar below the list shows the progress. Click {{sidebar.mode.list}} to "
                 "go back.",
                 "If a thumbnail does not match its video, select the item and press {R}, or choose {{side_menu.thumbnails}} from the "
                 "right-click menu.",
                 "{{sidebar.refresh}} ({F5}) — syncs the list with the disk again (removes videos that are gone and adds new ones). "
                 "In thumbnail mode it also regenerates the thumbnails of videos that have become newer because they were "
                 "re-rendered.",
                 "When you go to another app and come back, the list is read again automatically.",
             )),
             ("h", "Right-click menu", "menu"),
             ("fig", "mov_menu", "The menu shown when you select videos and right-click", ()),
             ("table", None, (
                 ("{{side_menu.open_a}} · {{side_menu.open_b}}", "Opens that video in A or B."),
                 ("{{side_menu.merge}}",
                  "Joins the selected videos **in name order** and saves them as one file (.mov). Even if the size, aspect ratio, "
                  "frame rate or presence of sound differ, they are merged to match the first video (black bars if the aspect "
                  "ratio differs)."),
                 ("{{side_menu.copy}}", "Copies the selected files to another folder."),
                 ("{{side_menu.thumbnails}}", "Regenerates the thumbnails of the selected videos."),
                 ("{{side_menu.info}}", "Shows file information such as codec, resolution and frame count."),
                 ("Open with QuickTime Player", "Opens the selected videos in QuickTime Player (Mac only)."),
                 ("{{open_with.menu}} ▸", "Opens them with an app you have registered."),
             )),
             ("h", "Media info", "mediainfo"),
             ("fig", "media_info", "Media info window", ()),
             ("p", "Shows the codec (profile, tag), pixel format, color, resolution, frame rate and frame count, duration, bitrate, "
                   "audio tracks, container, file size and path. Click **Show Details** to see the raw ffprobe output; the text can "
                   "be selected with the mouse and copied."),
             ("h", "Opening with another app", "openwith"),
             ("list", (
                 "{{open_with.register}} — choose an `.app` on Mac or an `.exe` on Windows. You can register several apps, and "
                 "they appear in the menu in the order you registered them. Remove one with {{open_with.remove}} ▸.",
                 "For a video, the file itself is passed to the app; for a sequence, its **first frame file**.",
                 "If you select several items, a registered app is launched **separately for each file**. If there are more than "
                 "20, YesonCheck asks first.",
                 "Registered apps are saved **on this PC only**. If an app has been deleted or moved, it appears in the menu with "
                 "`(not found)` — remove it and register it again.",
             )),
         )),
    Page("library", "Shows · folders · bookmarks", "Lists & files",
         "Three ways to load the videos to review — choosing from a show, opening a folder, and bookmarks.",
         (
             ("h", "Show → season → job", "works"),
             ("note", "Choosing **show → season → job** and managing show paths are features specific to Yeson's in-house "
                      "workflow — they are tailored to Yeson's show folder structure and shared settings. Open any other folder "
                      "with [[library/folder|Opening a folder]] or [[library/bookmarks|Bookmarks]] below."),
             ("list", (
                 "In the {{sidebar.works}} group at the top of the sidebar, choose **show → season → job** in that order; the "
                 "videos of that job come into the list. This group is shown only on PCs that have loaded the shows at least once. "
                 "→ [[sidebar]]",
                 "Until you choose a season, the job box only shows {{picker.job}}. For a show without seasons, go straight from show → job.",
                 "The show list is read from the shared settings. If a show is not shown or its folder cannot be found, tell your "
                 "administrator — shows are added and paths are corrected in {{menu.tools}} → {{menu.tools.work_paths}} (password "
                 "required).",
                 "On Windows, if the shared settings folder is somewhere else, choose it with Settings → {{settings.shared_config}}.",
             )),
             ("h", "Opening a folder", "folder"),
             ("list", (
                 "Choose a folder with {{sidebar.open_folder}} in the sidebar ({I} — also in the {{menu.file}} menu), or drop a "
                 "folder onto the window.",
                 "The videos in that folder go into the Mov tab and the image sequences into the Seq tab. If the folder contains "
                 "only sequences, the sidebar switches straight to the Seq tab.",
             )),
             ("h", "Bookmarks", "bookmarks"),
             ("fig", "bookmarks", "Bookmark manager window", ()),
             ("p", "Keep the folders you open often as bookmarks and open them directly. Bookmarks are saved separately for each "
                   "user of this PC."),
             ("list", (
                 "**Adding** — choose a folder with {{sidebar.bookmarks}} ▾ → {{sidebar.bookmark.add}} in the sidebar; a folder "
                 "dropped onto the window is also added automatically.",
                 "**Opening** — open the manager window with {{sidebar.bookmarks}} ▾ → {{sidebar.bookmark.manage}}, then "
                 "double-click an item ({Enter} or the window's ‘폴더 열기’ (Open folder) button does the same).",
                 "**Editing a path** — click the selected item once more, or right-click → **경로 수정** (Edit path), to edit it in "
                 "place. Finishing with {Enter} saves it immediately; {Esc} cancels. You can also copy a path in another app and "
                 "paste it.",
                 "**Right-click menu** — ‘경로 복사’ (Copy path) · ‘경로 수정’ (Edit path) · ‘폴더 열기’ (Open folder) · "
                 "‘삭제’ (Delete).",
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
                 "If you choose a single frame file with {{menu.file}} → {{menu.file.open_a}} or {{menu.file.open_b}}, or drop it "
                 "onto the video area, the **whole sequence** that the frame belongs to opens from its first frame. Dropping two "
                 "different sequences opens them in A and B.",
                 "An image that stands alone (only one file) is not a sequence, so it opens as a single picture.",
             )),
             ("h", "Playback · annotations · comparison", "use"),
             ("list", (
                 "Playback, frame stepping, the slider and revision annotations work exactly as with videos.",
                 "A/B wipe works only between sequences (for example `_tk1` versus `_tk2`).",
                 "OCR / cut detection, playing the selected videos in a row and the slider preview cannot be used with sequences.",
             )),
             ("h", "Right-click menu", "menu"),
             ("fig", "seq_menu", "The menu shown when you select sequences and right-click", ()),
             ("table", None, (
                 ("{{side_menu.seq.open_a}} · {{side_menu.seq.open_b}}", "Opens that sequence in A or B."),
                 ("{{side_menu.seq.export}}", "Creates a mov file for each selected sequence (see below)."),
                 ("{{side_menu.seq.thumbnails}}", "Regenerates the thumbnails of the selected sequences."),
                 ("{{side_menu.seq.info}}", "Shows information about that sequence."),
                 ("{{open_with.menu}} ▸",
                  "Passes the first frame file to a registered app. → [[sidebar/openwith|Opening with another app]]"),
             )),
             ("h", "Making MOV files from selected sequences", "export"),
             ("steps", (
                 "Select one or more sequences in the Seq list.",
                 "Right-click → {{side_menu.seq.export}}",
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
                 "{{annot.mode}} — turns red when it is on. While it is on, you draw on the video.",
                 "**Tool · Color** — Text / Rectangle / Ellipse / Line / Arrow; Red · Yellow · Green · Sky blue · White.",
                 "**Text size · Line width · Frames (from ~ to)** — the frames are the range in which the annotation is visible.",
                 "**Annotation list** — select an annotation to go to its start frame; you can then change its display frames, "
                 "size and line width.",
                 "**Annotations on the video** — click one in annotation mode and yellow dots appear (the arrow in the picture); "
                 "drag to move or resize it.",
                 "**{{badge.annotation}} badge** — indicates that the mode is on. The cursor also becomes a crosshair.",
             )),
             ("h", "Drawing", "draw"),
             ("steps", (
                 "Open a video in A and click {{transport.annotate}} on the playback bar to open the {{panel.annotation}} panel "
                 "({N} opens the panel you used last, so it may open the OCR panel instead).",
                 "Turn on {{annot.mode}}.",
                 "Choose a **Tool** and a **Color**.",
                 "For shapes (rectangle, ellipse, line, arrow), **drag** on the video; for text, **click** and type the text in "
                 "the dialog that appears.",
                 "Set the range in which the annotation is visible with the start and end of **Frames**. If the start and end are "
                 "the same, it is visible on that one frame only.",
             )),
             ("note", "The text input dialog appears only with the {{annot.tool.text}} tool. With a shape tool, clicking without "
                      "dragging draws nothing."),
             ("h", "Editing · deleting · exporting", "edit"),
             ("fig", "annotation_export", "The bottom of the annotation panel", (
                 "{{annot.delete}} — deletes the one annotation selected in the list. {{annot.clear_frame}} — deletes all the "
                 "annotations currently visible on screen at once.",
                 "{{annot.export_dir.choose}} — the folder where the exported video is put.",
                 "{{annot.export}} — creates a new video file with the annotations drawn on it.",
             )),
             ("list", (
                 "If the window is short, scroll down inside the panel to reach the delete and export buttons.",
                 "Closing the panel keeps annotation mode on — the badge at the top right of the video tells you so.",
                 "With annotation mode on, **click** an annotation you have drawn and yellow dots appear. Drag to move or resize it.",
                 "Click {{annot.export}}, set the file name, then choose the quality — 균형 (권장) (balanced, recommended) · "
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
             ("warn", "{{ocr.roi.select}} and {{annot.mode}} cannot be on at the same time — turning one on turns the other off "
                      "automatically."),
         )),
    Page("ocr", "OCR · cut detection (splitting animatics)", "Review tools",
         "Reads the slate text of an animatic (scene and panel numbers) or detects cuts to divide the video into segments, and "
         "exports each segment as a clip.",
         (
             ("fig", "ocr", "An ROI set in the OCR panel", (
                 "{{ocr.roi.select}} — click it, then drag over the place in the video where the text is.",
                 "{{ocr.roi.clear}} · {{ocr.roi.tracking}} — clears the ROI / makes the ROI follow the text when it moves.",
                 "**OCR method** — choose from the table below.",
                 "{{ocr.analyze}} · {{ocr.analyze_range}} — analyzes the whole video / analyzes only the frame range you specify and "
                 "merges it into the earlier result.",
                 "{{ocr.reopen}} · {{ocr.save}} · {{ocr.load}} — reopens the review window / saves the result to a file / loads a "
                 "saved result.",
                 "**ROI** — the area you set.",
             )),
             ("h", "Analysis methods", "modes"),
             ("table", ("Method", "Use"), (
                 ("Titmouse", "Default OCR settings."),
                 ("King", "Settings tuned for recognizing red text."),
                 ("Bento", "Settings tuned for small text and special formats (for example `Seq 02A_S09 - Panel 6`)."),
                 ("{{ocr.mode.all}}", "You write the pattern of the text to read yourself — `#` is a letter, `W` is a digit. "
                                      "Example: `AB101_C010` → `##WWW_#WWW`"),
                 ("{{ocr.mode.animatic}}", "Detects **cuts (where the scene changes)** instead of text. No ROI is needed."),
                 ("{{ocr.mode.animatic2}}", "Detects cuts with deep learning — including slow transitions such as dissolves and "
                                            "fades. No ROI is needed. On PCs that do not support it, it does not appear in the list."),
             )),
             ("h", "Steps", "steps"),
             ("steps", (
                 "Open an animatic in A.",
                 "Click {{transport.ocr}} on the playback bar to open the {{panel.ocr}} panel.",
                 "(For the OCR methods) Click {{ocr.roi.select}} and drag over the slate text.",
                 "Choose a method and click {{ocr.analyze}}. A progress window appears, and you can cancel.",
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
                 "corrected text (‘편집 텍스트’ — edited text), and the start and end frames. You can edit the cells directly.",
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
                 ("일괄 리네임 (Batch rename)", "Changes the ‘편집 텍스트’ (edited text) in bulk by a rule (for example, removing ` - Panel A`)."),
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
                      "when you close the app. To keep it, save it to a file with {{ocr.save}} in the OCR panel and load it later "
                      "with {{ocr.load}}. If you only closed the review window, you can reopen it with {{ocr.reopen}}."),
             ("note", "OCR and cut detection cannot be used with image sequences."),
         )),
    Page("settings", "Settings (Settings menu)", "Settings & management",
         "The items under Settings in the menu bar. The items shown differ slightly between Mac and Windows.",
         (
             ("fig", "settings_menu", "Settings menu (Mac)", ()),
             ("table", ("Item", "What it does"), (
                 ("{{settings.decoder}}",
                  "How ProRes is opened — {{settings.decoder.videotoolbox}} / {{settings.decoder.ffmpeg}}. The choice is applied "
                  "right away to the video you are viewing. Mac only. → [[prores]]"),
                 ("{{settings.display}}",
                  "How the picture is drawn — {{settings.display.cpu}} / {{settings.display.gpu}}. If 4K playback stutters, try "
                  "GPU. It applies from the next window you open, and the `This window:` line in the menu shows the method actually "
                  "in use. Windows only."),
                 ("{{settings.downscale}}",
                  "The filter used when the video is **scaled down** to fit the window — {{settings.downscale.linear}} / "
                  "{{settings.downscale.area}}. If thin lines look uneven (shimmering) in the scaled-down view, try High quality. "
                  "The choice is applied to this window right away. Every frame is scaled down on the CPU, so if 4K playback "
                  "becomes slow, switch back to Linear. At 1:1 or when the view is enlarged, the two filters are the same. "
                  "Windows only."),
                 ("{{settings.hover_thumbs}}", "Turns the [[playback/hover|slider preview]] on and off (on by default)."),
                 ("{{settings.shared_config}}",
                  "Chooses the folder that holds the shared settings such as the show paths. Windows only."),
                 ("언어 (Language)",
                  "Switches the text of the main window between 한국어 / English. The choice is applied to this window right away. "
                  "At first it follows the language of the OS. Secondary windows (OCR review, bookmark manager and so on) and "
                  "error messages are in Korean."),
             )),
             ("note", "The playback decoder, display rendering, downscale filter, slider thumbnail and language settings are saved "
                      "**on this PC only**. Other YesonCheck windows that are already open pick up the change the next time they "
                      "are started."),
         )),
    Page("windows", "Multiple windows · default video app", "Settings & management",
         "In YesonCheck, each window is one running copy of the app. You can open several windows and review videos side by side.",
         (
             ("h", "Opening more windows", "new"),
             ("list", (
                 "**Mac** — launch YesonCheck again from the Applications folder (응용 프로그램 on a Korean Mac), Launchpad or Spotlight, or "
                 "**click its icon in the Dock**, and one empty new window opens. Switching to it with ⌘Tab or by clicking a "
                 "window does not open a new window.",
                 "Windows that are already open stay as they are. To bring back a window that was minimized to the Dock, click "
                 "that window's icon on the right side of the Dock.",
                 "If you **double-click** a video (.mov, .mp4) in Finder or File Explorer, or open it with **Open With** "
                 "(다음으로 열기; on Windows, **Open with** — 연결 프로그램), a new window opens that video in A. If you open several "
                 "at once, one window opens for each video.",
                 "While a window is closing (up to about 30 seconds while it finishes its work), a new window may not open — "
                 "open it again after the window has closed completely.",
             )),
             ("h", "Opening videos in YesonCheck by double-click", "default"),
             ("fig", "help_menu", "Help menu (Mac)", ()),
             ("table", None, (
                 ("Mac", "The first time you start a new version, the app asks once: “동영상(.mov·.mp4)을 더블클릭하면 YesonCheck로 "
                         "열까요?” — in English, “Open videos (.mov, .mp4) in YesonCheck when you double-click them?” To change "
                         "this later, choose Help → {{help.default_app}}."),
                 ("Windows", "Right-click a video → in **Open with** (연결 프로그램), choose **Yeson Checker** and click **Always** "
                             "(항상) — once each for .mov and .mp4. Help → {{help.default_apps_settings}} opens the default apps "
                             "settings screen of Windows."),
             )),
             ("note", "On Mac, the default app cannot be set from an app opened directly from the disk image (dmg). Move the app "
                      "to the Applications folder and open it from there."),
             ("h", "Help menu", "help"),
             ("table", None, (
                 ("{{help.manual}}", "Opens this manual ({F1})."),
                 ("{{help.update_check}}", "Checks right away whether there is a new version. → [[update]]"),
                 ("{{help.default_app}} / {{help.default_apps_settings}}", "The default app setting described above (Mac / Windows)."),
                 ("{{help.about}}", "Shows the current version."),
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
                 "starts and every 3 hours while it is running; you can also check right away with Help → {{help.update_check}}.",
                 "Click {{update.notes}} to see what has changed.",
                 "Click {{update.update}} and it proceeds in this order: download → the app closes → install → the app starts "
                 "again. Click {{update.later}} to close the banner; that version is not announced again until you restart the app.",
             )),
             ("list", (
                 "Nothing changes until you click. If the update fails, the current version starts as it is and tells you the reason.",
                 "PCs without internet access get the update from the shared folder.",
                 "You can see the current version in the window title and in Help → {{help.about}}.",
             )),
             ("h", "Updating while several windows are open", "many"),
             ("list", (
                 "When you click {{update.update}}, the app tells you how many other YesonCheck windows there are and asks once. "
                 "Click ‘모두 닫고 업데이트’ (Close all and update): the other windows close normally, and "
                 "only the window where you clicked starts again in the new version.",
                 "Windows that are **busy with a job** such as OCR analysis or export, and windows with **unsaved OCR results**, "
                 "are shown in the confirmation dialog. If you continue, those jobs are stopped and the unsaved results are lost "
                 "— to keep them, cancel and save first.",
                 "If there is a window that does not close, the update is stopped. Close that window and click again.",
                 "If another user account on the same computer has YesonCheck running, the update is not performed.",
                 "If you open YesonCheck while an update is in progress, it only shows ‘업데이트 중입니다’ (Updating) for a "
                 "moment and does not open. Open it again after the update has finished.",
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
                 "Use the `real` value in the fps box of the playback bar to see whether playback is running in real time. "
                 "→ [[playback]]",
                 "Playing two 4K videos together with A/B wipe can be slower.",
                 "4K ProRes 4444 has to read about 130 MB per second, so on a 1 Gbps network the first playback may stutter "
                 "(after the file has been read once, it is smooth).",
                 "If 4K stutters on Windows, try Settings → {{settings.display}} → {{settings.display.gpu}}.",
             )),
             ("p", "If a problem occurs, you can go back to the old method in the way described on the [[trouble]] page."),
         )),
    Page("trouble", "Troubleshooting", "Reference",
         "Common symptoms and how to fix them, and where to find the log files to send when you report a problem.",
         (
             ("h", "By symptom", "symptoms"),
             ("table", ("Symptom", "Fix"), (
                 ("No sound on Windows", "Install K-Lite Codec Pack (Basic)."),
                 ("New videos do not appear in the list", "{{sidebar.refresh}} or {F5}."),
                 ("A thumbnail does not match its video", "Select the item and press {R}, or click {{sidebar.refresh}} in "
                                                          "thumbnail mode."),
                 ("B is black in the wipe", "A and B have different sizes (resolutions). Compare videos of the same size."),
                 ("4K playback stutters on Windows", "Settings → {{settings.display}} → {{settings.display.gpu}}."),
                 ("Thin lines shimmer in the scaled-down view on Windows",
                  "Settings → {{settings.downscale}} → {{settings.downscale.area}}."),
                 ("On Mac, the video area is empty or a drawing error dialog appears",
                  "Settings → {{settings.decoder}} → {{settings.decoder.ffmpeg}}."),
                 ("A slider preview error dialog keeps appearing", "Turn off Settings → {{settings.hover_thumbs}}."),
                 ("ProRes videos do not open on Windows",
                  "This happens when security software blocks the local communication inside the app. Open them the old way "
                  "with the environment variable `YESONCHECK_MOVIE_SOURCE=cv2` described below."),
                 ("The app does not start on Windows after choosing GPU",
                  "Delete the `display_renderer` line in `%LOCALAPPDATA%\\YesonCheck\\prefs.json`, or start the app with the "
                  "environment variable `YESONCHECK_VIEWPORT=raster`."),
                 ("A show is not in the list or its folder cannot be found",
                  "Tell your administrator — it is fixed in {{menu.tools}} → {{menu.tools.work_paths}}."),
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
             ("note", "**Setting an environment variable on Windows** — Settings (설정) → System (시스템) → About (정보) → "
                      "Advanced system settings (고급 시스템 설정) → Environment Variables (환경 변수) → under User variables "
                      "(사용자 변수), click **New** (새로 만들기). Or run `setx YESONCHECK_MOVIE_SOURCE cv2` in Command Prompt."),
         )),
)
