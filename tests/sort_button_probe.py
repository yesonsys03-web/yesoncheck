"""정렬 단추가 탭 줄의 어디에 놓이는지 따로 띄운 프로세스에서 재는 도우미 — 시험이 아님 (tests/test_sidebar_sort.py가 자식으로 돌림).

왜 자식 프로세스인가: Windows CI의 화면 없는(offscreen) Qt 플랫폼은 글꼴이 하나도 없음(Qt의 FreeType 글꼴 폴더가 비어 글자마다 12px 상자 —
2026-11-12 CI 실측: 탭 막대 204px·`↕` 단추 41px, 이 Mac은 155·17). 그 값으로는 실제 Windows에서 단추가 All 탭을 가리는지 알 수 없음.
환경 변수 QT_QPA_FONTDIR로 Windows 글꼴 폴더를 주면 그 플랫폼이 진짜 글꼴(Segoe UI·맑은 고딕)을 읽는데, 시험 프로세스 전체에 주면 다른 시험의
픽셀·크기 기대가 바뀌므로 이 측정만 따로 띄움.

출력: 표준 출력에 `PROBE <JSON>` 한 줄 (창을 처음 켠 폭 그대로 — 사이드바를 건드리지 않음). 창을 정리하지 않고 바로 끝냄 — 종료 때의 정리
(알려진 간헐 세그폴트)가 결과를 가리지 않게.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    sys.path.insert(0, ROOT)
    from PyQt5.QtGui import QFontInfo
    from PyQt5.QtWidgets import QApplication, QMessageBox

    app = QApplication(["sort_button_probe"])
    dialogs = []

    def record(kind):  # 모달 창이 뜨면 자식이 끝없이 기다림 — 띄우지 않고 적어 둠 (시험이 보고 실패시킴)
        def shown(*args, **_kwargs):
            dialogs.append([kind] + [str(arg) for arg in args[1:3]])
            return QMessageBox.Ok
        return staticmethod(shown)

    for kind in ("critical", "warning", "information", "question"):
        setattr(QMessageBox, kind, record(kind))

    from yesoncheck import sidebar_sort
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()
    player.resize(1400, 860)
    player.show()
    tabs, bar, button = player.sidebar_tabs, player.sidebar_tabs.tabBar(), player.sidebar_sort_button

    def row():
        """지금의 탭 줄 — All 탭 끝에서 단추까지의 틈(gap, 음수면 그만큼 All 탭 위에 겹침)과 All 탭 글자의 오른쪽 끝에서 단추까지(label_gap,
        음수면 글자를 가림 — 글자는 탭 사각형의 가운데에 놓인다고 보고 글자 폭으로 계산)."""
        for _ in range(8):
            app.processEvents()
        all_rect = bar.tabRect(2)
        all_right = bar.mapTo(tabs, all_rect.topRight()).x()
        label_width = bar.fontMetrics().horizontalAdvance(bar.tabText(2))
        label_right = bar.mapTo(tabs, all_rect.center()).x() + (label_width + 1) // 2
        left = button.mapTo(tabs, button.rect().topLeft()).x()
        return {
            "tabs_width": tabs.width(),
            "bar_x": bar.x(),
            "bar_width": bar.width(),
            "bar_wanted": bar.sizeHint().width(),
            "tab_widths": [bar.tabRect(i).width() for i in range(bar.count())],
            "all_right": all_right,
            "all_label_width": label_width,
            "button_text": button.text(),
            "button_x": left,
            "button_width": button.width(),
            "gap": left - all_right,
            "label_gap": left - label_right,
            "inside": left >= 0 and left + button.width() <= tabs.width(),
        }

    startup = row()
    player._resize_sidebar_column(100)  # 최소 폭보다 좁게 달라고 함 — 가장 좁은 사이드바가 됨
    narrowest = row()
    texts = sidebar_sort.button_texts(player.sidebar_sort_mode)
    result = {
        "platform": sys.platform,
        "qpa": app.platformName(),
        "fontdir": os.environ.get("QT_QPA_FONTDIR", ""),
        "button_font": QFontInfo(button.font()).family(),
        "tab_font": QFontInfo(bar.font()).family(),
        "candidates": list(texts),
        "candidate_widths": [player._sort_button_width(text) for text in texts],
        "startup": startup,
        "narrowest": narrowest,
        "dialogs": dialogs,
    }
    print("PROBE " + json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
