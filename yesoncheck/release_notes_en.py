"""English text of the per-version release notes for the manual's 'Release notes' page — mirrors release_notes.RELEASES
entry for entry (no Qt). The deploy notes (GitHub Release, update banner) still come from release_notes (Korean).

두 파일을 함께 고칠 것 — 배포 0번에서 release_notes.py에 항목을 더할 때 여기에도 같은 모양으로(같은 버전·날짜·묶음 수·항목 수,
같은 `코드`·**굵게** 표시). 화면에 한글로 보이는 글자(메뉴·단추·창의 글)는 한글 그대로 두고 그 버전에서 처음 나올 때 괄호로 영어 뜻을 붙임.
"""
from yesoncheck.release_notes import Release

RELEASES = (
    Release("2.2.0", "2026-11-28",
            "Choosing shows now works on a PC outside the company too — Manage show paths opens that PC's own show list. When a "
            "video you have open is rendered again, a plain notice appears instead of a long error window.",
            (
                ("Shows on a PC outside the company", (
                    "On a PC that cannot find the in-house shared settings (outside the company), Tools → Manage show paths… opens "
                    "**a show list saved only on that PC** instead of a warning (no password). Register a show name and a folder "
                    "on that PC, then choose it in the Select show group of the sidebar.",
                    "For each show you set **how many more folders to choose** — list the videos as soon as the show is chosen, "
                    "show → folder, or show → folder → folder. The videos and image sequences under the last folder you choose are "
                    "listed, including all its subfolders (the same rule as Open folder), so any folder structure works.",
                    "Choosing the same folder again only re-reads the list — the video you are watching stays.",
                    "This window and its notices follow the screen language (한국어 / English).",
                    "In-house PCs (PCs that read the shared settings) work as before — the show list and password of the shared "
                    "settings, unchanged.",
                )),
                ("Window title", (
                    "The ‘공유 설정 오류 (작품 목록 없음)’ (shared settings error — no show list) text that was added to the window "
                    "title when the shared settings were not found is gone. The reason is behind the Why the shared settings were "
                    "not found… button of the Manage show paths window.",
                    "The path map error text in the title of a Windows PC that cannot reach its saved shared settings folder (an "
                    "in-house laptop started elsewhere, for example) no longer appears in that case either.",
                )),
                ("When a video you have open is rendered again", (
                    "If a video you are reviewing is rendered again under the same name, the open video may no longer be readable. "
                    "Instead of the long technical error window, a notice starting ‘이 영상은 연 뒤에 파일이 다시 쓰였습니다 …’ (this "
                    "video's file was written again after it was opened) appears once — when the render has finished, click that "
                    "video in the list again to open it.",
                    "The notice shows the file and what changed (size and modified time); the technical details are behind its "
                    "Show Details... button and in the app log.",
                    "An error with an unchanged file shows the same window as before.",
                )),
                ("Manual", (
                    "The ‘Getting started’, ‘Shows · folders · bookmarks’ (new section ‘Shows on a PC outside the company’) and "
                    "‘Troubleshooting’ pages now describe the above.",
                )),
            )),
    Release("2.1.3", "2026-11-25",
            "The one Open folder button in the sidebar now opens folders and files. A video you drop in or open by double-click "
            "is also added to the Mov list, wherever you open it.",
            (
                ("Open folder now takes files too", (
                    "Choosing a folder replaces the list with that folder's videos as before; choosing a **file** brings in just "
                    "that file, not its whole folder — it opens in A (two files open in A and B) and is added to the Mov list. "
                    "Choosing a frame of an image sequence opens that sequence.",
                    "On a Mac you choose a folder, or one or more files, in the same dialog. One folder at a time.",
                    "On Windows the button shows Choose a folder… and Choose files… right below it. The I key and File → Open "
                    "folder… open the folder dialog as before.",
                    "Anything that could not be brought in (a file that is neither a video nor a frame of an image sequence, a "
                    "path that cannot be found) is reported in a window.",
                )),
                ("Videos you bring in are listed too", (
                    "A video file dropped anywhere on the window goes into the Mov list — dropped on the video area or elsewhere "
                    "in the window it opens and is added to the list (before, one or two files only opened); dropped on the Mov list it is "
                    "only added to the list, not opened, as before.",
                    "A video opened by double-click in Finder or File Explorer, or with Open With, is also added to that window's "
                    "Mov list.",
                    "The list you have stays and new videos are added at the end. A video chosen with Open folder, dropped on the "
                    "video area or elsewhere in the window, or opened by double-click is not added again if it is already in the "
                    "list (one dropped on the Mov list is added as it is, as before).",
                    "Fixed: a list of videos or a folder brought in right after starting the app, while the shared settings (the "
                    "show list) were still loading, was cleared the moment loading finished.",
                )),
                ("Manual", (
                    "The ‘Getting started’, ‘Sidebar (video list)’, ‘Shows · folders · bookmarks’ and ‘Multiple windows · default video app’ "
                    "pages now describe the above.",
                )),
            )),
    Release("2.1.2", "2026-11-24",
            "Preview files that Toon Boom Harmony writes into a scene's `frames` folder (`preview-…`) no longer show up in the "
            "sidebar list. Since they are not listed, the error window they caused in thumbnail mode no longer appears.",
            (
                ("Sidebar list", (
                    "Frames that Toon Boom Harmony wrote as a preview (`preview-<hex>-<number>.<ext>`) are no longer listed as "
                    "image sequences in the Seq and All tabs, whatever folder they are in.",
                    "Inside a `frames` folder, files whose names start with `preview-` are not listed, frames and videos alike — "
                    "they are not review material. Files in other folders still show even if their names start with `preview-`.",
                    "Choosing such a file directly or dragging it in still opens it as before.",
                    "Since they are not listed, the ‘썸네일을 만들지 못해 이 시퀀스는 아이콘 없이 둡니다’ (Could not make the thumbnail, "
                    "so this sequence is left without an icon) window that a broken preview frame could bring up in thumbnail "
                    "mode no longer appears.",
                )),
                ("Manual", (
                    "The image sequences page now says which files are left out of the list.",
                )),
            )),
    Release("2.1.1", "2026-11-23",
            "The ‘공유 설정 오류’ (Shared settings error) window no longer appears at every start on PCs without Yeson's in-house "
            "shared settings (outside the company) or not connected to the NAS. An ‘업데이트 확인 실패’ (Update check failed) window "
            "that could appear on such PCs is fixed too.",
            (
                ("Notice windows at startup", (
                    "When the shared settings cannot be found (a PC used outside the company, or one not connected to the NAS), the "
                    "‘공유 설정 오류’ (Shared settings error) window is no longer shown at startup. On Windows the ‘공유 설정 폴더 선택’ "
                    "(Choose the shared settings folder) notice and the folder picker no longer appear either. Only choosing shows "
                    "is unavailable; everything else works as before.",
                    "In that case only ‘shared settings error (no show list)’ is added to the end of the window title. Tools → "
                    "Manage show paths… shows the reason.",
                    "If the shared settings folder opens but the file in it is broken or missing, a window still tells you as before.",
                    "Fixed: on a PC where the shared settings were not found, the automatic update check could show an ‘업데이트 확인 "
                    "실패’ (Update check failed) window. Such PCs now check for new versions on the internet (GitHub) only.",
                )),
                ("In-house: things to know", (
                    "If you start the app while the NAS is not connected, there is no notice window: the show list is empty and the "
                    "window title shows it — check the NAS connection and start the app again.",
                    "On Windows, if the shared settings folder is not found automatically, choose it yourself with Settings → Change "
                    "shared settings folder... (before, a picker appeared at startup).",
                )),
                ("Manual", (
                    "Added pictures of the sidebar A·B buttons and of the B key text during a wipe.",
                    "Added a ‘window title ends with shared settings error’ entry to Troubleshooting.",
                )),
            )),
    Release("2.1.0", "2026-11-20",
            "A·B buttons on sidebar rows open a wipe comparison in one click (turn them on in the Compare menu). During a wipe the "
            "B key's text also shows B's file name and frame number, and B now follows A with ←/→ and while you drag the slider.",
            (
                ("Sidebar A·B buttons (new)", (
                    "Turn on Compare → Sidebar A·B buttons, and hovering a row in the list shows A and B buttons at the right end "
                    "of that row (Mov, Seq and All tabs, also in thumbnail mode). They are off at first, and your choice is saved "
                    "on this PC.",
                    "B opens that video as video B and turns on the wipe so you can compare right away. Clicking B again on the "
                    "same row turns the wipe off. The ] key works the same.",
                    "A is the same as clicking the row (it opens that video as video A).",
                    "Right-click 'Open as video B' and File → Open video B… now turn on the wipe too.",
                )),
                ("Wipe", (
                    "If you turn on the file name and frame number text with the B key during a wipe, B's text also appears at the "
                    "bottom right of the video — with B's own frame number, and neither text is cut off at the wipe line. If the "
                    "file names are long and the two texts would overlap, B's text moves one line up.",
                    "During a wipe, ←/→ now move B together with A to the same frame (before, only A moved).",
                    "Dragging the time slider during a wipe no longer flashes the B side black — B follows along if it is "
                    "1920×1080 or smaller, and otherwise (4K, etc.) stays on its last picture until you release.",
                )),
            )),
    Release("2.0.1", "2026-11-18",
            "Keys for the sidebar — C copy files · J merge · M media info · R regenerate thumbnails · [ ] open as video A/B. "
            "Turning the wipe off now closes video B.",
            (
                ("Sidebar shortcuts (new)", (
                    "Keys do the right-click menu's jobs on what you selected in the sidebar — C copy files · J merge animatics "
                    "into one · M media info (show info for a sequence) · R regenerate thumbnails · [ ] open as video A/B (to "
                    "put the videos to wipe with the keyboard). The right-click menu shows the key at the end of each item.",
                    "The keys act on what is selected in the tab you are looking at. On the All tab, C and J handle movs only; "
                    "on the Seq tab, C and J are not available.",
                    "R now also regenerates the thumbnails of what is selected on the Seq and All tabs (before, it always used "
                    "the selection in the Mov list).",
                    "During selected playback the [ ] keys do not change the video (the same as clicking the list).",
                )),
                ("Wipe", (
                    "Turning the wipe off closes video B — to compare again, open B anew (] key). Before, B stayed open and the "
                    "same B came back when you turned the wipe on again and pressed X or Y.",
                )),
                ("User manual", (
                    "New installation page — download · installing on Windows · installing on Mac · after installing · "
                    "uninstalling.",
                )),
            )),
    Release("2.0.0", "2026-11-17",
            "A redesigned window — the playback controls sit in one row under the slider, the middle column is replaced by "
            "annotation and OCR panels you open when you need them, there are new menus, and you can choose the screen "
            "language (Korean / English). Annotation, bookmark and settings files keep the same format, so it works side "
            "by side with PCs still on 1.9.x.",
            (
                ("Playback bar — the controls in one row", (
                    "The playback controls are gathered in one row under the slider — the go to start, step back, play, step "
                    "forward, go to end and loop buttons are always in the same place. Home and End go to the start and end.",
                    "Type a number in the frame number box and press Enter to go to that frame.",
                    "The FPS box in the middle column is gone — choosing a value there did nothing, and the video's fps is shown "
                    "in the playback bar.",
                )),
                ("Tool panel, sidebar and menus instead of the middle column", (
                    "The middle column is gone and the video is that much wider. Annotations and OCR are now panels you open with "
                    "the `Annotate` and `OCR` buttons at the right of the playback bar (or the N key) — closing a panel keeps "
                    "annotation mode and the values you entered.",
                    "Turn on the wipe with the `A|B Wipe`, `X` and `Y` buttons in the playback bar.",
                    "Choosing show, season and job moved to the top of the sidebar. Play selected videos in a row with the one "
                    "`Play selected in a row` button under the list (the Enter key still works); while it plays, an `End "
                    "playlist` button appears below it. Meanwhile the go-to-start button stops and rewinds only the current video (the playlist does not end).",
                    "New menus: File, View, Playback, Compare and Tools — opening video A or B is in File, managing show paths "
                    "is in Tools. Right-clicking the video also shows all the menus.",
                    "New shortcuts: O open video A · I open a folder · L loop playback · W turn on the wipe. The N key now opens "
                    "and closes the annotation/OCR panel (before, it hid the middle column).",
                )),
                ("Screen language — Korean / English (new)", (
                    "Choose Korean or English in Settings → 언어 (Language). The choice applies to that window at once; other "
                    "windows that are already open follow it the next time they start.",
                    "At first the app follows the OS language, so a PC whose OS is not Korean shows English — you can switch to "
                    "Korean in the same menu.",
                    "Secondary windows (OCR review, show path management and so on) and error messages are still in Korean.",
                    "The user manual matches the new window too — the English manual uses the names and pictures of the English "
                    "screen.",
                )),
                ("Fixes", (
                    "B's file name appears next to A's in the playback bar only while the wipe is on (before, it stayed after "
                    "you turned the wipe off).",
                    "The volume is 50 when the app starts (before, the slider showed 50 but the sound played at 100).",
                    "Fixed a rare crash when closing the app.",
                )),
            )),
    Release("1.9.4", "2026-11-13",
            "The manual now has an English version — switch between 한국어 and English with the buttons above the table of "
            "contents.",
            (
                ("Manual — English version (new feature)", (
                    "The manual (Help → 사용법 (Manual), F1) now has `한국어 | English` buttons above the table of contents — "
                    "click one and the whole manual (feature pages, keyboard shortcuts, release notes) switches to that "
                    "language. You stay on the page you were reading.",
                    "The chosen language is remembered by that browser. The first time, the manual opens in Korean if the "
                    "browser language is Korean, and in English otherwise.",
                    "The English version keeps the app's Korean button and menu names exactly as they appear on screen, with "
                    "the English meaning next to them. The screenshots are the same as in the Korean version.",
                )),
            )),
    Release("1.9.3", "2026-11-13",
            "The video list appears faster when you pick a show (job). The six buttons in the middle column are now laid out "
            "two to a row, freeing up vertical space.",
            (
                ("Sidebar — the list appears faster", (
                    "The video list appears faster when you pick a show (job) — the difference is biggest for jobs with many "
                    "scene folders (on the development Mac, what took about 1.4–2 seconds now takes 0.4–0.7 seconds).",
                    "The contents and order of the list are the same as before — scene folders that used to be read one at a "
                    "time are now read several at once.",
                )),
                ("Middle column — buttons two to a row", (
                    "`Open Video A`·`Open Video B`, `X-Axis Wipe`·`Y-Axis Wipe` and `Play Selected`·`Selected Play` now sit two "
                    "to a row — this frees up vertical space, so the items below are pushed down less when you expand a box "
                    "such as ROI 설정 (ROI settings) or OCR 분석 (OCR analysis).",
                    "The middle column opens slightly wider at first so that the button text is not cut off. If you narrow the "
                    "middle column by hand, the buttons stack vertically as before.",
                    "The initial text of the button that pauses and resumes Play Selected playback changed from "
                    "`Play/Pause Selected` to `Selected Play` (during playback it reads `Selected Pause`, as before).",
                )),
            )),
    Release("1.9.2", "2026-11-13",
            "The sidebar list can now be sorted by kind, version or time. Windows gets a new setting that removes the shimmer "
            "on thin lines when a video is shown scaled down.",
            (
                ("Sidebar — 정렬 (Sort; new feature)", (
                    "A **정렬** (Sort) button now sits next to the All tab — `이름` (Name, the default), `종류` (Kind), `버전` "
                    "(Version), `시간` (Time). The button reads `정렬: 이름 ▾` when the sidebar is wide and `이름 ▾` or `↕` when "
                    "it is narrow; hover over it to see the current sort key.",
                    "`종류` groups items by the kind at the end of the name (a letters-only suffix such as `_HD` or `_TX`), and "
                    "`버전` groups them by version or take number (`v01`, `TK2`). This makes it easy to play just one kind back "
                    "to back — click the first row of a group, Shift+click the last row, then Play Selected.",
                    "`시간` lists the most recently modified files first — re-rendered videos come to the top. The modification "
                    "times are read when you pick `시간`, so to bring up something re-rendered after that, pick `시간` once more.",
                    "It applies to the Mov, Seq and All tabs together, and the up/down arrow keys and Play Selected playback "
                    "follow the displayed order as well. The chosen sort lasts until you close the window; when you restart "
                    "the app it starts in name order.",
                )),
                ("Windows — 축소 필터 (Downscale filter; new setting)", (
                    "Settings now has **축소 필터 (Windows)** (Downscale filter) — `Linear (기본)` (Linear, the default) / "
                    "`고품질 (면적 평균)` (High quality, area average). If thin lines shimmer when a video is scaled down to fit "
                    "the window, try `고품질 (면적 평균)`. The choice applies to that window right away.",
                    "The default is `Linear`, the same as before. `고품질` takes slightly longer to draw each frame — if 4K "
                    "playback slows down, switch back to `Linear`.",
                    "The setting is saved on that PC only. Mac does not have this item, and the Mac display is unchanged.",
                )),
            )),
    Release("1.9.1", "2026-11-12",
            "In the sidebar, videos with different take or version numbers are now told apart by color. Fixed the black "
            "background in the light theme, and switching themes no longer changes the size or layout of the UI. Also removed "
            "an error dialog that appeared when moving to another video.",
            (
                ("Sidebar — take and version colors (new feature)", (
                    "When the take or version number at the end of a video name is 2 or higher, that row is shown in a "
                    "different color for each number — 2 green, 3 pink, 4 purple, 5 yellow-green (from 6 on, starting again "
                    "from green). Number 1 (`TK1`·`v01`) and names without a number use the default color.",
                    "Text such as `TK2 6` or `v02 176` in the count line below the list uses the same colors — you can see "
                    "there which color is which number.",
                    "This applies to videos on the Mov and All tabs. Image sequences on the All tab stay sky blue as before. "
                    "On the selected row and on the row being played by Play Selected playback, the selection or playback "
                    "highlight color takes precedence over the take color.",
                )),
                ("Themes (T key)", (
                    "Fixed the window background turning black in the light theme (Mac) and the collapsible boxes — ROI 설정 "
                    "(ROI settings), OCR 분석 (OCR analysis), 결과 관리 (Result management), 수정 사항 주석 (Revision "
                    "annotations) — staying dark. The 'OCR 분석 방식:' (OCR analysis mode) text is now also easy to read on the "
                    "light background.",
                    "Switching themes no longer changes the size or position of buttons, text and lists. Previously, text and "
                    "buttons grew larger and the layout changed in the light theme.",
                    "The right-click menu in the light theme now has the same white background as the list.",
                )),
                ("Switching videos", (
                    "Moving to another video no longer rewinds the video you were watching to the start. Switching is slightly "
                    "faster, and the error dialog that appeared when the file you were watching had been re-rendered in the "
                    "meantime no longer appears. The Stop button still rewinds to the start, as before.",
                )),
                ("Menu cleanup", (
                    "Removed GPU Acceleration and 4K 성능 모드 (4K performance mode) from Settings. Neither item was ever "
                    "applied when selected, so playback and seeking behave the same as before.",
                    "Removed the developer-only item '실행 및 빌드' (Run and build) from Help (Mac).",
                )),
            )),
    Release("1.9.0", "2026-11-11",
            "Hovering over the time slider now previews the picture at that position, and Help → 사용법 (Manual) is now a "
            "manual with screenshots. Also fixed B staying black after dragging and releasing the slider with the wipe on.",
            (
                ("Slider preview (new feature)", (
                    "Hover the mouse cursor over a time slider (the slider at the bottom of the window or the V-mode slider) "
                    "and the picture and frame number of the frame at that position appear above the cursor. You can find the "
                    "scene you want before clicking.",
                    "The pictures are built in the background after a video is opened, while playback and seeking are idle. "
                    "Building pauses while you play or drag the slider, so it does not get in the way of playback. Positions "
                    "not built yet show only the number and an empty box.",
                    "For long videos (over 500 frames) the pictures are built at intervals and the nearest scene is shown (the "
                    "number is exact). For long H.264 animatics, rough pictures appear first and are then replaced by exact "
                    "ones — on the development Mac, a 22-minute 720p animatic showed rough pictures after about 10 seconds "
                    "and exact pictures after about 30 seconds.",
                    "Files over 4GB show only the number, without a picture. Not yet available for image sequences (Seq).",
                    "To turn it off, uncheck Settings → 슬라이더 썸네일 (Slider thumbnails). The setting is saved on that PC "
                    "only.",
                )),
                ("Manual (Help → 사용법 · F1)", (
                    "사용법 is now a manual with a page per feature, screenshots and keyboard shortcut tables. It opens in a "
                    "web browser and needs no internet connection.",
                    "The manual's 'Release notes' (업데이트 내역) page lists what changed in each version so far.",
                )),
                ("Fixes", (
                    "Fixed the B side staying black after dragging and releasing the time slider with the A/B wipe on. On "
                    "release, B is now set to the same frame as A (while dragging, only A is shown, as before).",
                )),
            )),
    Release("1.8.1", "2026-11-09",
            "On Windows, switching files in Play Selected playback is faster, and the B-key text no longer jitters during "
            "playback. Another folder layout of one show now appears in the list as well.",
            (
                ("Playback (Windows)", (
                    "In Play Selected playback of 4K ProRes, the time to move on to the next file dropped from about 1.1 "
                    "seconds to 0.6 seconds. FPS during playback is unchanged.",
                )),
                ("B key (file name and frame number)", (
                    "The text and the white box no longer jitter as the frame number changes during playback. The white box "
                    "fits the length of the text (it grows by one character only when the number of digits changes).",
                )),
                ("Sidebar", (
                    "For one show, jobs whose video folder sits directly under the job, without scene folders, now "
                    "appear in the list too.",
                )),
                ("Sound on Windows", (
                    "To hear a video's sound on Windows, K-Lite Codec Pack (Basic) must be installed. Without it the picture "
                    "plays but there is no sound. On a new PC, install it together with YesonCheck.",
                    "If the sound cannot be opened, the reason is written to the app log.",
                )),
                ("", ("Nothing has changed on Mac other than the B-key text.",)),
            )),
    Release("1.8.0", "2026-11-06",
            "The sidebar gains a file count line and '다른 앱으로 열기' (Open in another app), and on Windows you can choose "
            "how the picture is drawn. Also fixed a pause in the middle of loop playback and a delay when Play Selected "
            "playback moves on to a shorter file.",
            (
                ("Sidebar", (
                    "Just below the list, the count for the tab you are viewing is shown. Files are counted separately by the "
                    "kind at the end of the name (e.g. HD) and by version or take (e.g. TK1, v01). Example: "
                    "`450개 — 기본 225 (TK1 225) · HD 225 (TK1 225)` (개 = files; 기본 = no kind). It updates when you refresh "
                    "(새로고침).",
                    "At the bottom of the right-click menu there are now 'QuickTime Player로 열기' (Open in QuickTime Player; "
                    "Mac) and '다른 앱으로 열기' (Open in another app). With '앱 등록…' (Register app…) you can register several "
                    "apps such as DJV and open files in them. A sequence is passed as its first frame file, and a registered "
                    "app is opened once for each selected file. Registered apps are saved on that PC only.",
                    "On the Seq tab too, moving with the up/down arrow keys now opens that sequence.",
                )),
                ("Playback", (
                    "Fixed a brief pause partway through the second or third loop when playing a single ProRes file on repeat "
                    "(it was most noticeable on Windows).",
                    "Fixed an extra wait when Play Selected playback moves on to a file shorter than the previous one. The "
                    "time it takes to open a file (about 1 second for 4K) still remains.",
                )),
                ("Windows", (
                    "In Settings → 화면 그리기 (Windows) (Display rendering) you can choose between CPU (기본 — the default) "
                    "and GPU. Choosing GPU may make 4K playback steadier. It takes effect from the next window you open.",
                    "If the app does not start after you choose GPU, delete `display_renderer` from "
                    "`%LOCALAPPDATA%\\YesonCheck\\prefs.json`, or start it with the environment variable "
                    "`YESONCHECK_VIEWPORT=raster`.",
                )),
                ("", ("Mac playback is unchanged apart from the Play Selected fix above (windows on Mac set to the ffmpeg "
                      "method also get the loop playback fix).",)),
            )),
    Release("1.7.1", "2026-11-05",
            "Corrected the playback speed. Videos that ran at 21fps on Windows and about 4% fast on Mac now play at their "
            "original speed.",
            (
                ("Playback", (
                    "Fixed 24fps videos running at about 21fps on Windows and at 25fps on Mac. The cause was the playback "
                    "timer. The same fix applies to videos at other rates, such as 30fps.",
                    "It now happens less often that sound and picture drift apart and the audio position has to be moved.",
                    "No frames are skipped, and frame numbers and annotation positions are unchanged.",
                    "As a result, videos may feel slightly slower than before. They used to run fast; this is the original "
                    "length.",
                )),
                ("Notes", (
                    "4K on Windows has improved but may still be uneven in some sections.",
                )),
            )),
    Release("1.7.0", "2026-11-05",
            "On Mac, ProRes playback, file switching and scrubbing are faster, and the app no longer freezes when you release "
            "the slider on a long video.",
            (
                ("Freeze fix (Windows and Mac)", (
                    "Fixed the app freezing for minutes at a time after dragging the slider handle quickly left and right on "
                    "a long video and releasing it. Dragging and scrubbing respond the same as before.",
                )),
                ("Mac playback (Intel and Apple Silicon)", (
                    "ProRes (except HDR) is now opened with the decoder built into the Mac (VideoToolbox) and drawn straight "
                    "on the GPU. Playback, file switching and scrubbing are faster, 4K included.",
                    "In Settings → 재생 디코더 (Mac) (Playback decoder) you can switch to ffmpeg (예전 방식), the previous "
                    "method. It takes effect immediately.",
                    "Playing two 4K videos together with the A/B wipe may not reach real time, depending on the hardware.",
                    "Display color: the 1-pixel edges where the color changes abruptly in ProRes 422, and the colors of HD "
                    "files with no color information written, may differ slightly from previous versions. QuickTime Player "
                    "converts colors according to the file's color tags and the monitor, so it may look different from the "
                    "app's display.",
                )),
                ("Annotations", (
                    "Fixed red and blue being swapped in shape annotations (rectangle, ellipse, line, arrow), both on screen "
                    "and in exports.",
                )),
                ("", ("Windows playback is unchanged apart from the freeze fix.",)),
            )),
    Release("1.6.1", "2026-11-03",
            "The 미디어 정보 (Media info) window now shows codec details, the playback FPS readout also shows the actual "
            "playback speed, and the B-key text no longer looks small at 4K.",
            (
                ("Playback", (
                    "`재생: 24 FPS` in the info line now also shows the fps actually achieved, like `재생: 24 FPS · 실제 23.8` "
                    "(재생 = playback, 실제 = actual). If the '실제' value at the end is well below the original fps, the video "
                    "is running slow. The value is measured every 1 second, so it wobbles by about ±1; when not playing, and "
                    "for the first 1 second after playback starts, only the original fps is shown.",
                    "The file name and frame number text burned into the picture with the B key now appears the same size "
                    "regardless of resolution. At 1080p it is 1.5 times the previous size, and it no longer looks half-size, "
                    "small and thin at 4K (at 1:1 zoom the 4K text is 2 times as large).",
                )),
                ("미디어 정보 (Media info)", (
                    "Right-click in the sidebar → 미디어 정보 used to show only a one-word codec name; it now shows the "
                    "details: codec profile and tag (e.g. Apple ProRes 4444 · ap4h), pixel format (4:4:4 · 12-bit · alpha), "
                    "color space and range, resolution, frame rate and frame count, duration, bitrate, audio tracks, "
                    "container, file size. Click the 'Show Details...' button to see the raw ffprobe output (JSON); the text "
                    "can be selected with the mouse and copied.",
                    "The duration is that of the video track, so it may read one frame longer than the previous value.",
                )),
                ("Notes", (
                    "4K ProRes 4444 playback speed (correction): about 22fps on a studio Windows PC, about 18fps on an Apple "
                    "Silicon Mac mini (M1, 16GB), borderline 24fps on an Intel Mac — measured with the `실제` value in the info "
                    "line and a stopwatch. The wording first posted, \"confirmed to play in real time on Windows as well\", "
                    "was a judgment by eye; the measured figures fall slightly short of real time (24). No behavior has "
                    "changed.",
                )),
            )),
    Release("1.6.0", "2026-11-02",
            "4K ProRes playback is now close to real time, and rewinding and seeking respond instantly in a video you have "
            "already watched once. Bookmark paths can now be edited right in the window.",
            (
                ("Playback", (
                    "ProRes mov files are now opened with the ffmpeg decoder bundled with the app — 1080p plays in real time, "
                    "and 4K decoding is more than twice as fast. Other files such as h264 are the same as before.",
                    "Mac: 4K frames are now uploaded directly to the graphics card (GPU) for drawing, which speeds 4K ProRes "
                    "(24fps) playback up to the edge of real time (334 frames in about 14 seconds). On Windows the drawing "
                    "method is unchanged, so 4K speed has not changed.",
                    "After you play a ProRes video through once and pause for a moment, all of its frames are loaded into "
                    "memory, so rewinding, ←, the slider and loop playback afterwards respond instantly with no waiting (only "
                    "for files that memory has room for — 4K 334 frames is about 8GB; with both A and B open, both are "
                    "loaded). The memory is filled while idle, so first-playback speed is unchanged.",
                    "At 4K, ← (one frame back) used to pause briefly every time; it now pauses only once in 8 presses.",
                )),
                ("Bookmarks", (
                    "In the bookmark manager window you can edit a path in place by clicking the selected path once more, or "
                    "with right-click → 경로 수정 (Edit path). Finish with Enter and it is saved immediately, so '폴더 열기' "
                    "(Open folder) opens the edited path. The text being edited is kept even if you switch to another app "
                    "(such as Finder) and come back, so you can copy a path there and paste it in.",
                    "Right-click menu: 경로 복사 (Copy path) · 경로 수정 (Edit path) · 폴더 열기 (Open folder) · 삭제 (Delete). "
                    "The P key (ㅔ on a Korean keyboard) opens the bookmark window.",
                )),
                ("Notes", (
                    "If you run into problems, you can go back to the previous behavior with environment variables: "
                    "`YESONCHECK_MOVIE_SOURCE=cv2` (turn off the ffmpeg decoder), `YESONCHECK_VIDEO_ITEM=pixmap` (the previous "
                    "Mac drawing method), `YESONCHECK_FRAME_CACHE=ring` (turn off loading into memory).",
                )),
            )),
    Release("1.5.0", "2026-10-28",
            "Fixed slow fullscreen (F) playback on Mac and a problem with the V-mode slider.",
            (
                ("", (
                    "Mac: fullscreen playback is now as smooth as windowed playback, at the same speed — the graphics card "
                    "(GPU) now does the upscaling of the picture (measured 13.5 → 24.8fps, at 1080p).",
                    "Fixed the overlay slider handle staying still when stepping frames with the ←/→ arrow keys in V mode "
                    "(overlay controls) (both Mac and Windows — it now follows along, as it does with the wheel).",
                    "Also fixed a one-frame offset in a rarely used fallback frame-seek path, which showed the frame after "
                    "the target.",
                    "Theme switching (dark/light), the wipe line, annotations, the zoom readout and all other on-screen "
                    "behavior are the same as before.",
                    "Windows never had the fullscreen slowdown, so its playback method has not changed.",
                    "In the rare case that OpenGL cannot be used on a Mac, the app shows a notice and keeps working the "
                    "previous way.",
                )),
            )),
    Release("1.4.0", "2026-10-28",
            "New feature: the sidebar All tab — videos and image sequences in one list",
            (
                ("New features", (
                    "The sidebar now has an **All tab** alongside Mov and Seq. It shows videos (mov) and image sequences "
                    "mixed in one list in name order, and sequence names are sky blue so you can tell them apart at a glance.",
                    "Clicking an item on the All tab opens it according to its kind, and the right-click menu matches the "
                    "kind as well. With **\"Mov만 모두 선택\"** (Select all Mov only) at the top of the right-click menu you "
                    "can select just the videos and play them all.",
                    "Play Selected playback on the All tab plays **only the mov files in the selection** one after another "
                    "and skips sequences (back-to-back sequence playback is limited by memory). If you select only sequences "
                    "and press it, a notice appears.",
                )),
                ("Fixes", (
                    "Fixed the middle control panel not coming back when you pressed N again after pressing Thumb/List while "
                    "the panel was hidden with the N key (it reappeared collapsed to 0 width — the width is now remembered "
                    "and restored).",
                    "Fixed the sidebar width growing or shrinking with every press of the Thumb/List buttons while the Seq or "
                    "All tab was showing (a bug present since the Seq tab was introduced).",
                    "Fixed the Seq list thumbnails not being cleared when returning to List mode.",
                )),
            )),
    Release("1.3.1", "2026-10-27",
            "Annotation mode (주석 모드) is easier to notice, and the N key can hide the middle control panel",
            (
                ("New features", (
                    "The N key (ㅜ on a Korean keyboard) hides and shows the middle control panel (Open Video A/B, OCR, "
                    "annotations, volume and so on). The file list and the video stay as they are, and the video gets wider "
                    "by the hidden space. It works independently of the V key (hide all controls).",
                )),
                ("Fixes", (
                    "While annotation mode is on, the '주석 모드' (Annotation mode) button turns red and a '주석 모드' badge "
                    "appears at the top right of the video — shown at a glance so that you are not caught off guard by "
                    "clicking the picture without realizing the mode is on.",
                    "When the annotation tool is 사각형 (Rectangle), 타원 (Ellipse), 선 (Line) or 화살표 (Arrow), a click "
                    "without dragging no longer draws anything. The text input dialog appears only with the '텍스트' (Text) "
                    "tool (previously a mere click with the 사각형 or 타원 tool opened the text input dialog).",
                )),
            )),
    Release("1.3.0", "2026-10-26",
            "New feature: image sequence playback",
            (
                ("New features", (
                    "The sidebar now has `Mov` and `Seq` tabs. Open a folder containing rendered image sequences (numbered "
                    "files such as `name-0001.tga`) and they appear as groups on the Seq tab; you can play them, step through "
                    "frames and annotate them just like a mov.",
                    "You can compare two sequences (takes) with the A/B wipe.",
                    "Sequence thumbnails reuse the thumbnail of the matching mov in the same folder, so they appear right "
                    "away. The playback rate (fps) is also taken from the matching mov.",
                    "Opening a single frame file (Open Video A/B, double-click in Finder) or dragging and dropping one opens "
                    "the whole sequence. Dropping thousands of frames at once is handled right away too.",
                    "Select several sequences on the Seq tab and choose \"선택한 시퀀스로 MOV 만들기\" (Make MOV from selected "
                    "sequences) to batch-create mov files in a folder you choose (they are not created in the source folder). "
                    "Progress display and cancel are supported.",
                    "Playback uses a read-ahead cache, so it does not stutter even from a NAS.",
                )),
                ("Fixes", (
                    "Dropping a video or frame file anywhere on the window now opens it (previously nothing happened when it "
                    "was dropped outside the video area and the list).",
                )),
                ("Notes", ("Please update every computer to 1.3.0.",)),
            )),
    Release("1.2.1", "2026-10-23",
            "Fixed the scrollbar handle being covered by the arrow button so that it could not be dragged.",
            (
                ("Fixes", (
                    "Sidebar list scrollbar: fixed the handle being covered by the up arrow button when it was at the very "
                    "top, so that it could not be dragged right away (it could be dragged only after scrolling down a little "
                    "with the wheel).",
                    "Fixed the same problem in the on-screen volume bar (pressing the handle at the very end pressed the "
                    "button instead).",
                )),
                ("Internal cleanup", ("Reorganized the internal code structure. The UI and behavior are unchanged.",)),
            )),
    Release("1.2.0", "2026-10-22",
            "New feature — multiple windows: open several windows to review videos side by side.",
            (
                ("New feature — multiple windows", (
                    "Mac: while YesonCheck is running, opening the app again (Finder, Launchpad) or clicking its Dock icon "
                    "opens one more new window. The windows already open stay as they are. Switching with ⌘Tab or by "
                    "clicking a window does not open a new window.",
                    "Double-clicking a video (.mov, .mp4) or opening it with \"Open With\" (다음으로 열기; on Windows "
                    "\"Open with\", 연결 프로그램) opens that video in a new window even when YesonCheck is already running. "
                    "Opening several at once gives one window per file.",
                    "Mac: the first time you start the app, it asks once whether to open videos with YesonCheck. You can set "
                    "this at any time with Help → 동영상 기본 앱으로 정하기… (Set as default video app…).",
                    "Windows: once installed, YesonCheck appears under \"Open with\" for videos. Choose \"Always\" (항상) once "
                    "and double-clicking opens them in YesonCheck. Help → 동영상 기본 앱 설정 열기… (Open default video app "
                    "settings…)",
                )),
                ("Using several windows together", (
                    "Editing annotations on the same video in two windows (or on two computers) no longer erases each "
                    "other's changes. Bookmarks and settings are likewise no longer overwritten by the window that saved "
                    "last.",
                    "A web report connects only to its own window.",
                    "If other YesonCheck windows are open when you update, the app asks once, closes them all and then "
                    "updates. Tasks running in those windows are stopped, and you are told if there are unsaved OCR results. "
                    "If a window does not close, the update is stopped.",
                    "If a video passed to the app cannot be opened, an error dialog tells you.",
                )),
                ("Before updating", (
                    "This update is carried out by the current version (1.1.x), so please close all other YesonCheck windows "
                    "before clicking [업데이트] (Update).",
                    "Every computer must be upgraded to 1.2.0 so that annotations do not erase each other (earlier versions "
                    "can erase annotations made in other windows or on other computers).",
                )),
            )),
    Release("1.1.1", "2026-10-20",
            "Fixed problems with 애니매틱 하나로 합치기 (Merge into one animatic).",
            (
                ("Fixes", (
                    "애니매틱 하나로 합치기: fixed merging videos with different track orders (a file with the sound stored "
                    "first and a file with the picture stored first), where the later video's part came out as noise with no "
                    "picture.",
                    "Merging now also handles videos that differ in size, aspect ratio, frame rate or presence of sound, "
                    "conforming them to the first video (black bars if the aspect ratio differs).",
                    "The duration and frame count of the merged result are now checked; if they do not match, an error "
                    "dialog is shown instead of '완료' (Done) and the bad file is deleted.",
                )),
            )),
    Release("1.1.0", "2026-10-20",
            "The first version with automatic updates.",
            (
                ("New features", (
                    "Automatic updates: when a new version is released, a notification banner at the top of the window tells "
                    "you. Click '업데이트' (Update) and the app downloads it, replaces itself and restarts. If the new version "
                    "does not start properly, it rolls back to the previous version and tells you. PCs without internet "
                    "access get it from the shared folder (NAS).",
                    "The current version is shown in the window title and in Help → 정보 (About). You can check manually "
                    "with Help → 업데이트 확인… (Check for updates…).",
                    "An app for Apple Silicon Macs is now released as well.",
                )),
                ("Changes in the meantime", (
                    "새로고침 (Refresh; button or F5) now re-syncs the list with the disk and also rebuilds the thumbnails "
                    "of re-rendered videos.",
                    "The show → season → job order is now enforced (the job list is empty until a season is picked).",
                    "Windows and Mac now share the same thumbnails.",
                    "Macs that mount the share at a different location now find the show folders too.",
                    "Fixed the 정보 (About) and help windows not opening on English Windows, and OCR hanging on Apple Silicon.",
                )),
                ("Installation", (
                    "Please install this version by hand once on each computer. From the next version on, updates happen "
                    "inside the app.",
                )),
            )),
)
