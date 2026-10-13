from PyQt5.QtWidgets import QLabel

from yesoncheck.path_map_setup import Candidate, PairChoice, Proposal, Share
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog


def make_proposal():
    return Proposal(
        pairs=[
            PairChoice("/usadata2", [Candidate("/usadata2", "\\\\203.0.113.3\\usadata2", ["Y:"], ["KOTH"])]),
            PairChoice("/Volumes/colordata", [
                Candidate("/Volumes/colordata", "\\\\203.0.113.19\\colordata", ["Z:"], ["FL_Animatic"]),
                Candidate("/Volumes/colordata", "\\\\backup\\mirror", ["M:"], ["FL_Animatic"]),
            ]),
        ],
        unmatched={"BM_Animatic": "/Volumes/bgfinal/colordata/BIG_MOUTH"},
        shares=[Share("\\\\203.0.113.3\\usadata2", ["Y:"])],
        share_problems=["W: — 연결 정보를 읽지 못했습니다"],
    )


def label_text(dialog):
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


def test_default_choices_and_candidate_change(qapp):
    dialog = PathMapSetupDialog(make_proposal())
    assert dialog.chosen() == [
        ("/usadata2", "\\\\203.0.113.3\\usadata2"),
        ("/Volumes/colordata", "\\\\203.0.113.19\\colordata"),
    ]
    dialog._rows[1][1].setCurrentIndex(1)
    assert dialog.chosen()[1] == ("/Volumes/colordata", "\\\\backup\\mirror")
    dialog._rows[0][0].setChecked(False)
    assert dialog.chosen() == [("/Volumes/colordata", "\\\\backup\\mirror")]
    assert dialog.save_button.isEnabled()
    dialog._rows[1][0].setChecked(False)
    assert not dialog.save_button.isEnabled()
    text = label_text(dialog)
    assert "못 찾음: BM_Animatic" in text and "W: — 연결 정보를 읽지 못했습니다" in text
    assert "후보 2개" in dialog._rows[1][0].text()


def test_no_shares_disables_save(qapp):
    dialog = PathMapSetupDialog(Proposal(pairs=[], unmatched={"A": "/a/b"}, shares=[]))
    assert not dialog.save_button.isEnabled()
    text = label_text(dialog)
    assert "NAS 드라이브를 먼저 연결하세요" in text and "못 찾음: A" in text


def test_existing_error_note(qapp):
    dialog = PathMapSetupDialog(make_proposal(), existing_error="변환표 형식 오류: 여기에_붙여넣기")
    assert "path_map.json.bak-" in label_text(dialog)


def test_blocked_row_starts_unchecked_with_reason(qapp):
    reason = "같은 Windows 주소가 이미 다른 Mac 경로(/usadata2)에 쓰여 있어 넣을 수 없음 — 작품 경로를 Mac에서 같은 경로로 맞추세요"
    dialog = PathMapSetupDialog(make_proposal(), blocked={"/Volumes/colordata": reason})
    assert dialog._rows[0][0].isChecked()
    assert not dialog._rows[1][0].isChecked()
    assert dialog.chosen() == [("/usadata2", "\\\\203.0.113.3\\usadata2")]
    assert reason in label_text(dialog)
    dialog._rows[1][0].setChecked(True)  # 사용자가 그래도 고를 수 있음 (저장할 때 검증)
    assert dialog.chosen()[1] == ("/Volumes/colordata", "\\\\203.0.113.19\\colordata")
