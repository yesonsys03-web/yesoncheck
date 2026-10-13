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
