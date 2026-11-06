"""사이드바 목록 아래 개수 줄: 지금 보는 탭의 개수 — Mov `12개`, Seq `시퀀스 3개`, All `15개 — mov 10 · mp4 2 · tga 2 · exr 1`.

글은 sidebar_counts.count_text(Qt 없음)가 만들고, 창은 원본 Mov·Seq 목록에서 셈 (All 목록은 보일 때만 다시 만들어지므로 거기서 세지
않음). 시퀀스 프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA.
"""

import pytest

from tests.conftest import write_test_video
from tests.test_sequence_capture import make_seq
from tests.test_sidebar_seq_tab import shot
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.sidebar_counts import count_text

# ---------------------------------------------------------------- 글 (Qt 없음)


def test_mov_tab_counts_files():
    assert count_text("mov", ["/a/x.mov", "/a/y.mp4"], []) == "2개"


def test_seq_tab_counts_sequences_not_frames():
    assert count_text("seq", [], [("a", "tga"), ("b", "exr"), ("c", "tga")]) == "시퀀스 3개"


def test_all_tab_breaks_down_by_format_movies_first_then_sequences():
    movies = ["/a/1.mov", "/a/2.mp4", "/a/3.mov", "/a/4.MOV"]
    assert count_text("all", movies, [("s1", "exr"), ("s2", "tga"), ("s3", "tga")]) == "7개 — mov 3 · mp4 1 · tga 2 · exr 1"


def test_formats_with_the_same_count_are_in_name_order():
    assert count_text("all", ["/a/1.mp4", "/a/2.mov"], [("s1", "tga"), ("s2", "exr")]) == "4개 — mov 1 · mp4 1 · exr 1 · tga 1"


def test_sequence_extension_case_is_ignored():
    assert count_text("all", [], [("s1", "TGA"), ("s2", "tga")]) == "2개 — tga 2"


def test_empty_lists():
    assert count_text("mov", [], []) == "0개"
    assert count_text("seq", [], []) == "시퀀스 0개"
    assert count_text("all", [], []) == "0개"


def test_unknown_tab_is_an_error():
    with pytest.raises(ValueError, match="tab"):
        count_text("seqs", [], [])


# ---------------------------------------------------------------- 영문 꼬리(버전)마다 (사용자 요청 2026-11-06)
# FL_106 job은 같은 샷의 _TK1.mov 225개와 _TK1_HD.mov 225개 — 450개로만 보이면 샷 수를 모름. 이름의 마지막 `_` 뒤가 영문자뿐이면(_HD·_LR·
# _PROXY …) 그 꼬리로 따로 세고, 나머지 묶음은 모두 같은 꼬리면 그 이름(TK1), 아니면 '기본'. 꼬리가 있는 목록만 나눠 보임.

FL = ["/fl/FL_106_A001_TK1.mov", "/fl/FL_106_A002_TK1.mov", "/fl/FL_106_A001_TK1_HD.mov", "/fl/FL_106_A002_TK1_HD.mov"]


def test_mov_tab_splits_letter_suffix_versions():
    assert count_text("mov", FL, []) == "4개 — TK1 2 · HD 2"


def test_several_suffixes_base_first_then_by_count():
    movies = FL + ["/fl/FL_106_A001_TK1_LR.mov"]
    assert count_text("mov", movies, []) == "5개 — TK1 2 · HD 2 · LR 1"


def test_suffix_case_is_ignored_and_shown_upper():
    assert count_text("mov", ["/a/X_TK1.mov", "/a/X_TK1_hd.mov", "/a/Y_TK1_Hd.mov"], []) == "3개 — TK1 1 · HD 2"


def test_rest_is_called_basic_when_its_suffixes_differ():
    assert count_text("mov", ["/a/X_v001.mov", "/a/Y_v002.mov", "/a/X_v001_HD.mov"], []) == "3개 — 기본 2 · HD 1"


@pytest.mark.parametrize("names", [
    ["/k/1604_004_v001.mov", "/k/1604_005_v002.mov"],                        # 버전 꼬리를 떼도 앞이 숫자 (KOTH)
    ["/a/clip.mov", "/a/other.mp4"],                                          # 밑줄 없음
    ["/a/OSAN_v01.mov", "/a/TX_v02.mov"],                                     # 버전을 떼면 밑줄이 없음
    ["/a/샷_최종.mov", "/a/샷_초안.mov"],                                        # 영문이 아닌 꼬리
])
def test_no_letter_suffix_means_just_the_total(names):
    assert count_text("mov", names, []) == "2개"


def test_kind_before_a_version_suffix_is_counted():
    """Hazbin `_OSAN_v02` — 끝의 버전 꼬리(v + 숫자, 대소문자 무시)를 떼고 그 앞 꼬리로 셈 (사용자 요청 'OSRO, OSAN으로 구분되는 것들도 따로')."""
    names = ["/h/HH0305_010_0090_OSAN_v02.mov", "/h/HH0305_010_0100_OSAN_v01.mov", "/h/HH0305_011_0010_TX_v01.mov",
             "/h/HH0305_012_0010_OSRO_V003.mov"]
    assert count_text("mov", names, []) == "4개 — OSAN 2 · OSRO 1 · TX 1"


def test_version_is_dropped_before_naming_the_rest():
    """버전을 뗀 뒤의 꼬리로 나머지 묶음의 이름을 정함 — 같으면 그 꼬리, 다르면 '기본'."""
    assert count_text("mov", ["/a/X_TK1_v01.mov", "/a/Y_TK1_v02.mov", "/a/X_TK1_HD_v01.mov"], []) == "3개 — TK1 2 · HD 1"
    assert count_text("mov", ["/k/1604_004_v001.mov", "/k/1604_005_v001.mov", "/k/1604_006_OSAN_v001.mov"], []) == \
        "3개 — 기본 2 · OSAN 1"


def test_only_suffixed_files():
    assert count_text("mov", ["/a/X_TK1_HD.mov", "/a/Y_TK1_HD.mov"], []) == "2개 — HD 2"


def test_seq_tab_splits_by_base_name_suffix():
    assert count_text("seq", [], [("FL_A001_TK1", "tga"), ("FL_A002_TK1", "tga"), ("FL_A001_TK1_HD", "tga")]) == \
        "시퀀스 3개 — TK1 2 · HD 1"


def test_all_tab_splits_inside_each_format():
    sequences = [("FL_A001_TK1", "tga"), ("FL_A002_TK1", "tga")]
    assert count_text("all", FL + ["/fl/FL_106_A003_TK1.mp4"], sequences) == \
        "7개 — mov 4 (TK1 2 · HD 2) · mp4 1 · tga 2"


# ---------------------------------------------------------------- 창


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def label_after(player, qapp, widget):
    """탭을 widget으로 바꾸고 미룬 갱신이 돈 뒤의 개수 줄."""
    player.sidebar_tabs.setCurrentWidget(widget)
    qapp.processEvents()
    return player.sidebar_count_label.text()


def test_label_sits_right_under_the_tabs(player):
    layout = player.sidebar_tabs.parentWidget().layout()
    index = layout.indexOf(player.sidebar_tabs)
    assert layout.itemAt(index + 1).widget() is player.sidebar_count_label


def test_label_starts_at_zero(player, qapp):
    qapp.processEvents()
    assert player.sidebar_count_label.text() == "0개"


def test_label_follows_the_visible_tab(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))  # tk1.mov + 시퀀스 tk1(tga)·tk2(tga)
    assert label_after(player, qapp, player.sidebar) == "1개"
    assert label_after(player, qapp, player.seq_sidebar) == "시퀀스 2개"
    assert label_after(player, qapp, player.all_sidebar) == "3개 — mov 1 · tga 2"


def test_label_updates_when_the_lists_change(player, qapp, tmp_path):
    folder = shot(tmp_path)
    write_test_video(str(folder / "tk3.mp4"))
    make_seq(str(folder), "tk4", range(1, 4), ext="png")
    drop_folder(player, "video", folder)
    assert label_after(player, qapp, player.all_sidebar) == "5개 — mov 1 · mp4 1 · tga 2 · png 1"

    player.sidebar.takeItem(0)
    qapp.processEvents()
    assert player.sidebar_count_label.text().startswith("4개 — ")

    player.sidebar.clear()  # Mov 목록을 비우면 Seq 목록도 비움 (job을 바꿈·폴더를 불러옴)
    qapp.processEvents()
    assert player.sidebar_count_label.text() == "0개"


def test_counts_come_from_source_lists_even_before_all_list_is_rebuilt(player, qapp, tmp_path):
    """All 목록은 보일 때만(미뤄서) 다시 만들어짐 — 개수는 원본에서 세므로 다시 만들기를 기다리지 않음."""
    player.sidebar_tabs.setCurrentWidget(player.all_sidebar)
    drop_folder(player, "video", shot(tmp_path))
    qapp.processEvents()  # 미룬 개수 갱신(0ms)만 돎 — All 목록 다시 만들기(80ms)는 아직
    assert player.sidebar_count_label.text() == "3개 — mov 1 · tga 2"


def test_a_long_breakdown_does_not_widen_the_sidebar(player, qapp):
    """포맷이 많아 줄이 길어져도 사이드바의 최소 너비가 늘지 않음 (줄을 바꿈) — 창 최소 너비를 묶지 않게."""
    container = player.sidebar_tabs.parentWidget()
    before = container.minimumSizeHint().width()
    suffixes = ["TK1", "TK1_HD", "TK1_LR", "TK1_PROXY"]
    player.sidebar_count_label.setText(count_text("all", [f"/a/S{i}_{suffixes[i % 4]}.{ext}" for i, ext in enumerate(
        ["mov", "mp4", "mkv", "avi", "webm", "m4v", "mts", "m2ts"] * 30)],
        [(f"S{i}_{suffixes[i % 4]}", ext) for i, ext in enumerate(["tga", "png", "jpg", "tif", "exr"] * 30)]))
    qapp.processEvents()
    assert container.minimumSizeHint().width() == before


def test_refresh_button_updates_the_count(player, qapp, tmp_path):
    """새로고침(F5와 같은 길 — 디스크를 다시 읽어 없어진 영상은 빼고 새 영상은 넣음)이 목록을 바꾸면 개수 줄도 따라 바뀜 (사용자 질문)."""
    from tests.test_sidebar_refresh import wait_refreshed

    folder = tmp_path / "job"
    for name in ("S01_TK1.mov", "S02_TK1.mov", "S01_TK1_HD.mov"):
        write_test_video(str(folder / name), frames=2, size=(32, 24))
    player.load_videos_from_folder(str(folder))
    assert label_after(player, qapp, player.sidebar) == "3개 — TK1 2 · HD 1"

    write_test_video(str(folder / "S02_TK1_HD.mov"), frames=2, size=(32, 24))  # 다른 PC가 넣음
    (folder / "S01_TK1.mov").unlink()  # 다른 PC가 지움
    player._refresh_sidebar_by_user()
    wait_refreshed(player)
    qapp.processEvents()
    assert player.sidebar_count_label.text() == "3개 — TK1 1 · HD 2"
