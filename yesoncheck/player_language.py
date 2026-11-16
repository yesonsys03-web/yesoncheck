"""화면 언어 바꾸기 — `PlayerLanguageMixin` (`VideoPlayerBase`의 부모, 2026-11-16 UI 개편 PR 3).

**Settings → 언어 (Language)** → `한국어` / `English`. 고르면 이 PC의 prefs.json에 저장하고(`ui_language`) 글자 표(`ui_text`)의
언어를 바꾼 뒤 **이 창의 글자를 다시 그린다**(`retranslate_ui`). 창마다 프로세스가 하나라 이미 열린 다른 창은 다음에 켤 때부터.

다시 그리기는 영역마다의 함수가 한다 — 이 믹스인은 차례로 부르기만(`RETRANSLATORS`의 이름을 그 차례대로). 영역의 글자를 글자 표로
옮긴 모듈이 자기 함수를 만들고 그 이름을 여기에 덧붙인다. 이름이 없으면 AttributeError 그대로 — 조용히 건너뛰지 않는다.

환경 변수 `YESONCHECK_LANGUAGE`가 언어를 정한 창(시험·진단)에서는 두 항목이 꺼져 있고 툴팁이 까닭을 말한다. 꺼진 항목도
`QAction.trigger()`는 실행하므로 처리기(`_choose_language`)도 같은 조건으로 막는다.

딸린 창·오류 글·기록 줄은 한글로 남는다(설계 4.7) — 여기서 띄우는 저장 실패 창도.
"""

import traceback

from PyQt5.QtWidgets import QAction, QMessageBox

from yesoncheck import ui_language, ui_text
from yesoncheck.user_files import UserFileError


class PlayerLanguageMixin:
    # 영역마다의 '다시 그리기' 함수 이름 — 부르는 차례. (재생 줄·도구 패널은 위젯의 retranslate()를 retranslate_ui가 먼저 부름)
    RETRANSLATORS = ("retranslate_main_menus", "retranslate_sidebar_controls", "retranslate_playlist_end")

    def _add_language_menu(self, settings_menu):
        """Settings의 맨 끝에 구분선 + '언어 (Language)' 하위 메뉴(항목은 언어마다 — 자기 언어로 적은 이름)."""
        settings_menu.addSeparator()
        menu = settings_menu.addMenu(ui_language.MENU_TEXT)
        menu.setToolTipsVisible(True)
        self.language_menu = menu
        self.language_actions = {}  # 언어 코드 → 항목 (ui_text.LANGUAGES의 차례)
        for code in ui_text.LANGUAGES:
            action = menu.addAction(ui_language.NAMES[code])
            action.setCheckable(True)
            action.setMenuRole(QAction.NoRole)  # Mac: 글자를 보고 앱 메뉴로 옮기지 않게
            action.triggered.connect(lambda _checked=False, chosen=code: self._choose_language(chosen))
            self.language_actions[code] = action
        self._sync_language_menu()

    def _sync_language_menu(self):
        """체크를 지금 언어에, 켜짐·툴팁을 '환경 변수가 정했는지'에 맞춤 (만들 때·고른 뒤·다시 그린 뒤)."""
        override = ui_language.env_language()
        if override is None:
            tip = ui_text.text("settings.language.tip")
        else:
            tip = ui_text.text("settings.language.env_tip", value=override)
        for code, action in self.language_actions.items():
            action.setChecked(code == ui_text.language())
            action.setEnabled(override is None)
            action.setToolTip(tip)

    def _choose_language(self, code):
        """메뉴 항목의 처리기. 환경 변수가 정한 창에서는 아무것도 바꾸지 않는다(꺼진 항목의 trigger). 끝에는 늘 체크를 되맞춤 —
        Qt가 누른 항목의 체크를 먼저 뒤집어 두므로(체크된 항목을 다시 누르면 꺼짐)."""
        try:
            if ui_language.env_language() is None:
                self.set_ui_language(code)
        finally:
            self._sync_language_menu()

    def set_ui_language(self, code):
        """이 창의 화면 언어를 code('ko'·'en')로 — 설정 파일에 저장하고 글자를 다시 그린다. 모르는 값은 아무것도 하기 전에 ValueError.
        지금 언어와 같으면 체크만 맞춘다. 저장 실패(깨진 파일·쓰기 오류·잠금)면 트레이스백 + 창을 보이고 언어는 그대로.
        파일의 값이 모르는 값이었으면 고른 값으로 고쳐 쓴다(명시적 선택) — 깨진 JSON은 덮지 않는다."""
        if code not in ui_text.LANGUAGES:
            raise ValueError(f"모르는 언어: {code!r} (쓸 수 있는 값: {', '.join(ui_text.LANGUAGES)})")
        if code == ui_text.language():
            self._sync_language_menu()
            return
        try:
            ui_language.save(code)
        except (UserFileError, OSError, TimeoutError) as exc:
            traceback.print_exc()
            QMessageBox.critical(self, ui_language.SETTINGS_TITLE,
                                 f"언어 설정을 저장하지 못했습니다 — 언어를 바꾸지 않았습니다.\n\n{exc}")
            self._sync_language_menu()
            return
        at_start_width = self.sidebar_at_start_width()  # 옛 언어의 처음 폭 그대로인가 — 글자를 바꾸기 전에 봄
        ui_text.set_language(code)
        ui_language.set_source(ui_language.SOURCE_MENU)
        print(f"{ui_language.LOG_PREFIX} 설정: {ui_language.NAMES[code]} ({ui_language.SOURCE_MENU})", flush=True)
        self.retranslate_ui()
        if at_start_width:  # 손으로 맞춘 폭이 아니면 새 언어의 처음 폭으로(단추 글이 다 보이게) — sidebar_controls
            self.move_sidebar_to_start_width()

    def retranslate_ui(self):
        """글자 표의 지금 언어로 이 창의 글자를 모두 다시 그린다 (언어를 바꾼 뒤)."""
        self.transportBar.retranslate()
        self.toolPanel.retranslate()
        for name in self.RETRANSLATORS:
            getattr(self, name)()
        self._sync_language_menu()
