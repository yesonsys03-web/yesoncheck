"""변환표 자동 설정 확인 창 (Windows): 찾은 짝을 보여 주고, 넣을 짝과 후보를 고르게 한다."""

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
)


class PathMapSetupDialog(QDialog):
    def __init__(self, proposal, existing_error=None, parent=None, blocked=None):
        """blocked: {Mac 앞부분: 이유} — 기본 선택으로는 합칠 수 없는 짝 (꺼진 채로 시작, 이유 표시, 사용자가 켤 수는 있음)."""
        super().__init__(parent)
        blocked = blocked or {}
        self.setWindowTitle("변환표 자동 설정")
        self.setMinimumWidth(760)
        self._rows = []  # (QCheckBox, QComboBox, PairChoice)
        layout = QVBoxLayout(self)

        intro = QLabel(
            "이 PC에 연결된 네트워크 드라이브에서 작품 폴더가 실제로 열리는 곳을 찾았습니다.\n"
            "저장하면 공유 설정 폴더의 path_map.json에 들어가며, 같은 NAS에 연결된 다른 Windows PC도 함께 씁니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if existing_error:
            note = QLabel(
                "기존 변환표를 읽을 수 없어 새로 만듭니다 (원래 파일은 path_map.json.bak-<날짜시각>으로 보관).\n"
                f"이유: {existing_error}"
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        grid = QGridLayout()
        grid.addWidget(QLabel("넣기 / Mac 경로 앞부분"), 0, 0)
        grid.addWidget(QLabel("Windows 주소 (이 PC의 드라이브) — 확인된 작품"), 0, 1)
        for row, pair in enumerate(proposal.pairs, start=1):
            text = pair.mac_prefix
            if pair.ambiguous:
                text += f"  (후보 {len(pair.candidates)}개 — 골라 주세요)"
            reason = blocked.get(pair.mac_prefix)
            if reason:
                text += "  (넣을 수 없음 — 아래 이유 참고)"
            check = QCheckBox(text)
            check.setChecked(not reason)
            if reason:
                check.setToolTip(reason)
            check.toggled.connect(self._update_save_button)
            combo = QComboBox()
            for candidate in pair.candidates:
                combo.addItem(
                    f"{candidate.unc} ({', '.join(candidate.drives)}) — {', '.join(candidate.works)}", candidate.unc
                )
            grid.addWidget(check, row, 0)
            grid.addWidget(combo, row, 1)
            self._rows.append((check, combo, pair))
        layout.addLayout(grid)

        problems = [
            f"넣지 않음: {pair.mac_prefix} — {blocked[pair.mac_prefix]}"
            for pair in proposal.pairs if blocked.get(pair.mac_prefix)
        ]
        if not proposal.shares:
            problems.append("이 PC에 연결된 네트워크 드라이브가 없습니다. NAS 드라이브를 먼저 연결하세요.")
        elif not proposal.pairs:
            problems.append("연결된 네트워크 드라이브에서 작품 폴더가 열리는 곳을 찾지 못했습니다. NAS 드라이브를 먼저 연결하세요.")
        for work, mac_path in sorted(proposal.unmatched.items()):
            problems.append(f"못 찾음: {work} ({mac_path}) — 연결된 네트워크 드라이브 중 이 작품 폴더가 열리는 곳이 없음")
        problems.extend(f"네트워크 드라이브 문제: {problem}" for problem in proposal.share_problems)
        if problems:
            label = QLabel("\n".join(problems))
            label.setWordWrap(True)
            layout.addWidget(label)

        buttons = QDialogButtonBox()
        self._save = buttons.addButton("저장", QDialogButtonBox.AcceptRole)
        buttons.addButton("취소", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_save_button()

    @property
    def save_button(self):
        return self._save

    def _update_save_button(self, *_args):
        self._save.setEnabled(any(check.isChecked() for check, _combo, _pair in self._rows))

    def chosen(self):
        """넣기로 고른 짝 [(Mac 앞부분, UNC)]."""
        return [(pair.mac_prefix, combo.currentData()) for check, combo, pair in self._rows if check.isChecked()]
