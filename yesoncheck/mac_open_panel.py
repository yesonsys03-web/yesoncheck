"""(Mac) 기본 열기 창(NSOpenPanel)을 직접 띄움 — 한 창에서 폴더도 파일도, 파일은 여러 개도 ('폴더 열기' 단추, 2026-11-25).

왜 Qt의 QFileDialog가 아닌가 (이 Mac, Qt 5.15.14에서 창을 띄워 NSOpenPanel의 값을 읽어 확인): 정적 함수는 한쪽만 고르게 하고,
인스턴스의 AnyFile + 열기 모드는 파일도 폴더도 되지만 하나만(여러 개 False — 처음에 이걸로 만들었다가 "파일 다중 선택이 안돼"),
ExistingFiles는 여러 개지만 파일만 — '둘 다'와 '여러 개'를 함께 켜는 조합이 없음. 직접 띄운 창은 셋 다 True이고, 창이 떠 있는
동안 Qt 타이머가 돎(재생이 멈추지 않음).

AppKit(PyObjC)은 창을 띄우는 함수 안에서만 불러옴 — Windows 빌드에는 PyObjC가 없고(이 모듈은 어디서나 불림), Mac 빌드에는
lock의 pyobjc-framework-Cocoa로 들어감(check_frozen_imports가 앱에 들어갔는지 대조). Qt를 쓰지 않음.
"""

import unicodedata

_running = []  # 지금 떠 있는 창들 (runModal 안) — cancel_running이 닫음


def pick_folders_or_files(title):
    """창을 띄워 고른 경로 목록을 돌려줌 (취소면 빈 목록). title은 창 위쪽에 보이는 안내 글.

    - 답이 '확인'일 때만 URLs를 읽음: 취소한 창도 URLs에 그때 보던 폴더를 돌려줌(확인함) — 안 보고 읽으면 취소가 그 폴더를 불러옴.
    - 경로는 NFC로: Qt의 기본 창·끌어다 놓기가 주는 경로와 같은 모양. NSURL의 path()는 URL이 만들어진 길에 따라 한글을 자모로 푼
      NFD일 수 있고(fileURLWithPath로 만든 URL — 확인함), NFD 경로는 NFS 공유에서 다른 이름이며 주석 파일 이름도 달라짐.
      디스크의 이름이 NFD라 NFC 경로가 없을 때는 부른 쪽이 paths.find_unicode_variant로 찾음.
    - 파일 경로가 없는 URL은 ValueError (글자 'None'을 경로로 돌려주지 않음).
    """
    import AppKit  # 여기서만: Windows 빌드에는 PyObjC가 없음

    panel = AppKit.NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(True)
    panel.setMessage_(title)
    _running.append(panel)
    try:
        response = panel.runModal()
    finally:
        _running.remove(panel)
    if response != AppKit.NSModalResponseOK:
        return []
    chosen = []
    for url in panel.URLs():
        path = url.path()
        if path is None:
            raise ValueError(f"열기 창이 파일 경로가 없는 것을 돌려주었습니다: {url}")
        chosen.append(unicodedata.normalize("NFC", str(path)))
    return chosen


def cancel_running():
    """떠 있는 열기 창을 취소로 닫음 → 닫은 수 (없으면 0, AppKit을 불러오지 않음).

    다른 창의 업데이트가 이 창을 닫을 때(player_base.close_for_update) 부름: runModal로 띄운 창은 Qt의 대화 상자가 아니라
    reject()로 닫히지 않음 — 그대로 두면 이 프로세스가 창 안에 머물러 그 업데이트가 기다리다 멈춤.
    """
    panels = list(_running)
    for panel in panels:
        panel.cancel_(None)
    return len(panels)
